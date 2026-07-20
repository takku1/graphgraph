from __future__ import annotations

import json
import math
import statistics
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from ..graph.core import Graph
from ..io import load_any
from ..packets import estimate_tokens
from .compiler import GraphProgram, GraphRuntime
from .source_planner import QuerySourcePlanner


@dataclass(frozen=True)
class BenchmarkCase:
    project: str
    query: str
    expected_nodes: tuple[str, ...] = ()
    expected_relations: tuple[str, ...] = ()
    query_class: str = "auto"
    packet: str = "gg"
    max_nodes: int | None = None
    min_recall: float | None = None
    max_latency_ms: float | None = None
    max_tokens: int | None = None


@dataclass(frozen=True)
class BenchmarkGates:
    min_projects: int = 2
    min_pass_rate: float = 1.0
    min_mean_recall: float = 0.8
    min_relation_recall: float = 0.8
    max_p95_latency_ms: float = 3000.0
    max_mean_tokens: float = 2000.0
    require_valid: bool = True


@dataclass(frozen=True)
class BenchmarkConfig:
    projects: dict[str, Path]
    cases: tuple[BenchmarkCase, ...]
    gates: BenchmarkGates
    repeats: int = 1
    warmups: int = 0
    source_mode: str = "off"


def load_benchmark_config(path: Path) -> BenchmarkConfig:
    data = json.loads(path.read_text(encoding="utf-8"))
    raw_projects = data.get("projects", {})
    if isinstance(raw_projects, list):
        projects = {
            str(item["name"]): _resolve(path, str(item["graph"]))
            for item in raw_projects
        }
    else:
        projects = {
            str(name): _resolve(path, str(graph_path))
            for name, graph_path in raw_projects.items()
        }
    cases = tuple(
        BenchmarkCase(
            project=str(item["project"]),
            query=str(item["query"]),
            expected_nodes=tuple(str(value) for value in item.get("expected_nodes", item.get("expected", []))),
            expected_relations=tuple(str(value) for value in item.get("expected_relations", [])),
            query_class=str(item.get("query_class", "auto")),
            packet=str(item.get("packet", "gg")),
            max_nodes=int(item["max_nodes"]) if item.get("max_nodes") is not None else None,
            min_recall=float(item["min_recall"]) if item.get("min_recall") is not None else None,
            max_latency_ms=float(item["max_latency_ms"])
            if item.get("max_latency_ms") is not None
            else None,
            max_tokens=int(item["max_tokens"]) if item.get("max_tokens") is not None else None,
        )
        for item in data.get("cases", [])
    )
    raw_gates = data.get("gates", {})
    gate_defaults = asdict(BenchmarkGates())
    gate_defaults.update(raw_gates)
    gates = BenchmarkGates(**gate_defaults)
    return BenchmarkConfig(
        projects=projects,
        cases=cases,
        gates=gates,
        repeats=max(1, int(data.get("repeats", 1))),
        warmups=max(0, int(data.get("warmups", 0))),
        source_mode=str(data.get("source_mode", "off")),
    )


def run_benchmark(config: BenchmarkConfig) -> dict[str, object]:
    graphs: dict[str, Graph] = {}
    errors: list[str] = []
    for name, path in config.projects.items():
        try:
            graphs[name] = load_any(path)
        except (OSError, ValueError, KeyError) as exc:
            errors.append(f"project {name}: {type(exc).__name__}: {exc}")
    results: list[dict[str, object]] = []
    all_latencies: list[float] = []
    for case in config.cases:
        graph = graphs.get(case.project)
        graph_path = config.projects.get(case.project)
        if graph is None or graph_path is None:
            results.append({**asdict(case), "passed": False, "error": "project graph missing"})
            continue
        for _ in range(config.warmups):
            _run_case(graph, graph_path, case, config.source_mode)
        samples = [
            _run_case(graph, graph_path, case, config.source_mode)
            for _ in range(config.repeats)
        ]
        all_latencies.extend(float(sample["latency_ms"]) for sample in samples)
        best = min(samples, key=lambda sample: float(sample["latency_ms"]))
        latency_ms = statistics.median(float(sample["latency_ms"]) for sample in samples)
        tokens = int(best["tokens"])
        recall = float(best["recall"])
        relation_recall = float(best["relation_recall"])
        valid = bool(best["valid"])
        min_recall = case.min_recall if case.min_recall is not None else config.gates.min_mean_recall
        max_latency = (
            case.max_latency_ms
            if case.max_latency_ms is not None
            else config.gates.max_p95_latency_ms
        )
        max_tokens = case.max_tokens if case.max_tokens is not None else math.inf
        passed = (
            recall >= min_recall
            and relation_recall >= config.gates.min_relation_recall
            and latency_ms <= max_latency
            and tokens <= max_tokens
            and (valid or not config.gates.require_valid)
        )
        results.append({
            **asdict(case),
            **best,
            "latency_ms": round(latency_ms, 3),
            "latency_samples_ms": [round(float(sample["latency_ms"]), 3) for sample in samples],
            "passed": passed,
        })
    completed = [result for result in results if "error" not in result]
    pass_rate = sum(bool(result.get("passed")) for result in results) / max(1, len(results))
    mean_recall = statistics.mean(float(result["recall"]) for result in completed) if completed else 0.0
    mean_relation_recall = (
        statistics.mean(float(result["relation_recall"]) for result in completed)
        if completed
        else 0.0
    )
    mean_tokens = statistics.mean(float(result["tokens"]) for result in completed) if completed else 0.0
    p95_latency = _percentile(all_latencies, 0.95)
    projects_covered = len({str(result["project"]) for result in completed})
    valid_packets = all(bool(result["valid"]) for result in completed) if completed else False
    gates = {
        "projects": projects_covered >= config.gates.min_projects,
        "pass_rate": pass_rate >= config.gates.min_pass_rate,
        "mean_recall": mean_recall >= config.gates.min_mean_recall,
        "relation_recall": mean_relation_recall >= config.gates.min_relation_recall,
        "p95_latency": p95_latency <= config.gates.max_p95_latency_ms,
        "mean_tokens": mean_tokens <= config.gates.max_mean_tokens,
        "valid_packets": valid_packets or not config.gates.require_valid,
        "load_errors": not errors,
    }
    return {
        "ok": all(gates.values()) and all(bool(result.get("passed")) for result in results),
        "projects": projects_covered,
        "cases": len(results),
        "passed": sum(bool(result.get("passed")) for result in results),
        "pass_rate": round(pass_rate, 4),
        "mean_recall": round(mean_recall, 4),
        "mean_relation_recall": round(mean_relation_recall, 4),
        "p95_latency_ms": round(p95_latency, 3),
        "mean_tokens": round(mean_tokens, 3),
        "gates": gates,
        "thresholds": asdict(config.gates),
        "errors": errors,
        "results": results,
    }


def _run_case(
    graph: Graph,
    graph_path: Path,
    case: BenchmarkCase,
    source_mode: str,
) -> dict[str, object]:
    started = time.perf_counter()
    compiled = GraphRuntime(
        graph,
        source_planner=QuerySourcePlanner(graph_path.parent, graph_path=graph_path),
        source_mode=source_mode,
    ).compile(GraphProgram(
        query=case.query,
        query_class=case.query_class,
        packet=case.packet,
        max_nodes=case.max_nodes,
    ))
    latency_ms = (time.perf_counter() - started) * 1000
    retrieved = compiled.retrieval
    handles: set[str] = set(retrieved.nodes)
    for node_id in retrieved.nodes:
        node = compiled.graph.nodes[node_id]
        handles.update((node.label, node.path))
    expected = set(case.expected_nodes)
    relations = {edge.type for edge in retrieved.edges}
    expected_relations = set(case.expected_relations)
    return {
        "query_class_actual": compiled.route.query_class,
        "latency_ms": round(latency_ms, 3),
        "tokens": estimate_tokens(compiled.packet),
        "recall": len(expected & handles) / max(1, len(expected)) if expected else 1.0,
        "relation_recall": (
            len(expected_relations & relations) / max(1, len(expected_relations))
            if expected_relations
            else 1.0
        ),
        "valid": compiled.receipt.valid,
        "nodes": len(retrieved.nodes),
        "edges": len(retrieved.edges),
        "found_expected": sorted(expected & handles),
        "missing_expected": sorted(expected - handles),
        "found_relations": sorted(expected_relations & relations),
        "missing_relations": sorted(expected_relations - relations),
        "source_receipt": compiled.receipt.source_receipt,
    }


def _percentile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(quantile * len(ordered)) - 1))
    return ordered[index]


def _resolve(config_path: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else (config_path.parent / path).resolve()
