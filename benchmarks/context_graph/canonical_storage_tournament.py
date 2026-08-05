"""GGB3-to-GGB4 canonical storage promotion tournament."""

from __future__ import annotations

import argparse
import json
import math
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from graphgraph.io import load_any  # noqa: E402
from graphgraph.retrieval.relations import query_relations, query_saved_relations  # noqa: E402
from graphgraph.storage.backends import (  # noqa: E402
    _save_graph_binary_v3,
    load_graph_binary,
    save_graph_binary,
)

DEFAULT_GRAPH = ROOT / ".graphgraph" / "graph.gg"
DEFAULT_OUT = ROOT / "benchmarks" / "context_graph" / "out" / "canonical_storage_tournament"


def _percentile(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(quantile * len(ordered)) - 1)]


def _median_upper_bound(values: list[float], confidence: float = 0.95) -> float:
    """Distribution-free one-sided confidence bound for the population median."""
    ordered = sorted(values)
    denominator = 2 ** len(ordered)
    cumulative = 0
    for rank in range(1, len(ordered) + 1):
        cumulative += math.comb(len(ordered), rank - 1)
        if cumulative / denominator >= confidence:
            return ordered[rank - 1]
    return ordered[-1]


def _ratio_evidence(
    control: list[float],
    candidate: list[float],
    *,
    confidence: float = 0.95,
) -> dict[str, float | int]:
    ratios = [new / old for old, new in zip(control, candidate, strict=True)]
    return {
        "pairs": len(ratios),
        "median_ratio": round(statistics.median(ratios), 6),
        "upper_median_ratio": round(_median_upper_bound(ratios, confidence), 6),
        "confidence": confidence,
    }


def _summary(values: list[float]) -> dict[str, float | int]:
    return {
        "samples": len(values),
        "median_ms": round(statistics.median(values), 3),
        "p95_ms": round(_percentile(values, 0.95), 3),
        "min_ms": round(min(values), 3),
        "max_ms": round(max(values), 3),
    }


def _time(call: Callable[[], object], repeats: int) -> list[float]:
    result = []
    for _ in range(repeats):
        started = time.perf_counter()
        call()
        result.append((time.perf_counter() - started) * 1000)
    return result


def _targets(graph: Any, count: int) -> list[str]:
    degree: dict[str, int] = {}
    for edge in graph.edges:
        if edge.active and edge.type == "calls":
            degree[edge.source] = degree.get(edge.source, 0) + 1
            degree[edge.target] = degree.get(edge.target, 0) + 1
    return [node_id for node_id, _degree in sorted(degree.items(), key=lambda item: (-item[1], item[0]))[:count]]


def _resident_workload(graph: Any, targets: list[str]) -> list[dict[str, Any]]:
    return [
        query_relations(graph, target, direction=direction, details=True, freshness="fresh")
        for target in targets
        for direction in ("callers", "callees")
    ]


def _saved_workload(path: Path, targets: list[str]) -> list[dict[str, Any]]:
    return [
        query_saved_relations(path, target, direction=direction, details=True, freshness="fresh")
        for target in targets
        for direction in ("callers", "callees")
    ]


def _worker(args: argparse.Namespace) -> int:
    targets = json.loads(args.targets)
    started = time.perf_counter()
    if args.operation == "full":
        graph = load_graph_binary(args.path)
        receipt = [len(graph.nodes), len(graph.edges), len(graph.metadata)]
    elif args.backend == "ggb3":
        receipt = _resident_workload(load_graph_binary(args.path), targets)
    else:
        receipt = _saved_workload(args.path, targets)
    print(json.dumps({"elapsed_ms": (time.perf_counter() - started) * 1000, "receipt": receipt}, separators=(",", ":")))
    return 0


def _cold_once(
    backend: str,
    operation: str,
    path: Path,
    targets: list[str],
) -> tuple[float, object]:
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--worker",
        "--backend",
        backend,
        "--operation",
        operation,
        "--path",
        str(path),
        "--targets",
        json.dumps(targets, separators=(",", ":")),
    ]
    started = time.perf_counter()
    completed = subprocess.run(command, check=True, capture_output=True, text=True)
    timing = (time.perf_counter() - started) * 1000
    receipt = json.loads(completed.stdout.strip().splitlines()[-1])["receipt"]
    return timing, receipt


def _cold_pairs(
    operation: str,
    ggb3: Path,
    ggb4: Path,
    targets: list[str],
    repeats: int,
) -> tuple[list[float], list[object], list[float], list[object]]:
    """Measure matched trials while alternating order to limit temporal drift."""
    timings: dict[str, list[float]] = {"ggb3": [], "ggb4": []}
    receipts: dict[str, list[object]] = {"ggb3": [], "ggb4": []}
    paths = {"ggb3": ggb3, "ggb4": ggb4}
    for index in range(repeats):
        order = ("ggb3", "ggb4") if index % 2 == 0 else ("ggb4", "ggb3")
        for backend in order:
            timing, receipt = _cold_once(backend, operation, paths[backend], targets)
            timings[backend].append(timing)
            receipts[backend].append(receipt)
    return timings["ggb3"], receipts["ggb3"], timings["ggb4"], receipts["ggb4"]


def _write_report(result: dict[str, Any], out: Path) -> None:
    (out / "result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    c = result["control"]
    n = result["candidate"]
    lines = [
        "# Canonical Storage Tournament",
        "",
        f"Verdict: **{result['verdict']['decision']}** — {result['verdict']['reason']}",
        "",
        "| Metric | GGB3 | GGB4 | Ratio |",
        "| --- | ---: | ---: | ---: |",
        f"| Bytes | {c['bytes']} | {n['bytes']} | {n['bytes'] / c['bytes']:.3f}x |",
        f"| Save p95 | {c['save']['p95_ms']} ms | {n['save']['p95_ms']} ms | {n['save']['p95_ms'] / c['save']['p95_ms']:.3f}x |",
        f"| Full cold median | {c['full_cold']['median_ms']} ms | {n['full_cold']['median_ms']} ms | {result['decision_statistics']['full_load']['median_ratio']:.3f}x |",
        f"| Relation cold median | {c['relation_cold']['median_ms']} ms | {n['relation_cold']['median_ms']} ms | {result['decision_statistics']['direct_relation']['median_ratio']:.3f}x |",
        f"| Relation warm median | {c['relation_warm']['median_ms']} ms | {n['relation_warm']['median_ms']} ms | {n['relation_warm']['median_ms'] / c['relation_warm']['median_ms']:.3f}x |",
        "",
        f"Full-load paired median-ratio 95% upper bound: {result['decision_statistics']['full_load']['upper_median_ratio']:.3f}x (limit {result['decision_statistics']['full_load']['margin']:.3f}x).",
        f"Direct-relation paired median-ratio 95% upper bound: {result['decision_statistics']['direct_relation']['upper_median_ratio']:.3f}x (limit {result['decision_statistics']['direct_relation']['margin']:.3f}x).",
        "Trials are matched and execution order alternates; gates use a distribution-free binomial order-statistic bound for the population median.",
        "",
        "All result objects and full Graph fields must be exactly equal before performance is considered.",
    ]
    (out / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(args: argparse.Namespace) -> dict[str, Any]:
    args.out.mkdir(parents=True, exist_ok=True)
    graph = load_any(args.graph)
    targets = _targets(graph, args.samples)
    ggb3 = args.out / "control.ggb3.gg"
    ggb4 = args.out / "candidate.ggb4.gg"
    save_v3 = _time(lambda: _save_graph_binary_v3(graph, ggb3), args.repeats)
    save_v4 = _time(lambda: save_graph_binary(graph, ggb4), args.repeats)
    loaded_v3 = load_graph_binary(ggb3)
    loaded_v4 = load_graph_binary(ggb4)
    full_fidelity = (
        loaded_v3.nodes == loaded_v4.nodes == graph.nodes
        and loaded_v3.edges == loaded_v4.edges == graph.edges
        and loaded_v3.metadata == loaded_v4.metadata == graph.metadata
    )
    expected = _resident_workload(graph, targets)
    actual = _saved_workload(ggb4, targets)
    relation_equivalent = expected == actual
    warm_rounds = max(9, args.repeats)
    warm_v3 = _time(lambda: _resident_workload(loaded_v3, targets), warm_rounds)
    warm_v4 = _time(lambda: _saved_workload(ggb4, targets), warm_rounds)
    full_v3, full_v3_receipts, full_v4, full_v4_receipts = _cold_pairs(
        "full", ggb3, ggb4, targets, args.repeats
    )
    relation_v3, relation_v3_receipts, relation_v4, relation_v4_receipts = _cold_pairs(
        "relations", ggb3, ggb4, targets, args.repeats
    )
    exact = (
        full_fidelity
        and relation_equivalent
        and set(map(json.dumps, full_v3_receipts)) == set(map(json.dumps, full_v4_receipts))
        and set(map(json.dumps, relation_v3_receipts)) == set(map(json.dumps, relation_v4_receipts))
    )
    size_ratio = ggb4.stat().st_size / ggb3.stat().st_size
    full_evidence = _ratio_evidence(full_v3, full_v4)
    relation_evidence = _ratio_evidence(relation_v3, relation_v4)
    full_margin = 1.05
    relation_margin = 0.75
    gates = {
        "exact_fidelity": exact,
        "single_store_footprint": size_ratio <= 1.15,
        "full_load_no_material_regression": full_evidence["upper_median_ratio"] <= full_margin,
        "direct_relation_material_win": relation_evidence["upper_median_ratio"] < relation_margin,
    }
    promote = all(gates.values())
    failed = [name for name, passed in gates.items() if not passed]
    result = {
        "schema": "canonical_storage_tournament_v2",
        "graph_shape": {"nodes": len(graph.nodes), "edges": len(graph.edges)},
        "workload": {"targets": targets, "queries": len(targets) * 2, "repeats": args.repeats},
        "control": {
            "format": "GGB3",
            "bytes": ggb3.stat().st_size,
            "save": _summary(save_v3),
            "full_cold": _summary(full_v3),
            "relation_cold": _summary(relation_v3),
            "relation_warm": _summary(warm_v3),
        },
        "candidate": {
            "format": "GGB4",
            "bytes": ggb4.stat().st_size,
            "save": _summary(save_v4),
            "full_cold": _summary(full_v4),
            "relation_cold": _summary(relation_v4),
            "relation_warm": _summary(warm_v4),
        },
        "correctness": {"full_fidelity": full_fidelity, "relation_equivalent": relation_equivalent},
        "decision_statistics": {
            "method": "alternating matched trials with a distribution-free one-sided median bound",
            "full_load": {**full_evidence, "margin": full_margin},
            "direct_relation": {**relation_evidence, "margin": relation_margin},
        },
        "verdict": {
            "decision": "promote" if promote else "hold",
            "reason": "all gates passed" if promote else f"failed gates: {', '.join(failed)}",
            "gates": gates,
        },
    }
    _write_report(result, args.out)
    return result


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    result.add_argument("--graph", type=Path, default=DEFAULT_GRAPH)
    result.add_argument("--out", type=Path, default=DEFAULT_OUT)
    result.add_argument("--samples", type=int, default=5)
    result.add_argument("--repeats", type=int, default=15)
    result.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    result.add_argument("--backend", choices=("ggb3", "ggb4"), help=argparse.SUPPRESS)
    result.add_argument("--operation", choices=("full", "relations"), help=argparse.SUPPRESS)
    result.add_argument("--path", type=Path, help=argparse.SUPPRESS)
    result.add_argument("--targets", help=argparse.SUPPRESS)
    return result


def main() -> int:
    args = parser().parse_args()
    if args.worker:
        return _worker(args)
    print(json.dumps(run(args), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
