from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from .io import load_any
from .packets import render_packet
from .planner import choose_packet
from .retrieval import retrieve_context


@dataclass(frozen=True)
class EvalTask:
    query: str
    query_class: str
    expected_nodes: tuple[str, ...] = ()
    expected_edges: tuple[tuple[str, str, str], ...] = ()


@dataclass(frozen=True)
class EvalResult:
    query: str
    query_class: str
    node_recall: float
    edge_recall: float
    returned_nodes: int
    returned_edges: int
    token_estimate: int


def load_eval_tasks(path: Path) -> list[EvalTask]:
    data = json.loads(path.read_text(encoding="utf-8"))
    tasks = data.get("tasks", data) if isinstance(data, dict) else data
    out: list[EvalTask] = []
    for task in tasks:
        out.append(EvalTask(
            query=str(task["query"]),
            query_class=str(task.get("query_class", "blast_radius")),
            expected_nodes=tuple(str(item) for item in task.get("expected_nodes", [])),
            expected_edges=tuple(tuple(edge) for edge in task.get("expected_edges", [])),
        ))
    return out


def evaluate_graph(graph_path: Path, tasks: list[EvalTask], max_nodes: int | None = None) -> list[EvalResult]:
    graph = load_any(graph_path)
    results: list[EvalResult] = []
    for task in tasks:
        choice = choose_packet(task.query_class, task.query)
        retrieved = retrieve_context(graph, task.query, task.query_class, hops=choice.hops, max_nodes=max_nodes)
        packet = render_packet(graph, retrieved.nodes, retrieved.edges, choice.packet)
        returned_labels = {graph.nodes[nid].label for nid in retrieved.nodes if nid in graph.nodes}
        returned_paths = {graph.nodes[nid].path for nid in retrieved.nodes if nid in graph.nodes}
        returned_ids = set(retrieved.nodes)
        returned_node_keys = returned_ids | returned_labels | returned_paths
        returned_edges = {(edge.source, edge.target, edge.type) for edge in retrieved.edges}
        results.append(EvalResult(
            query=task.query,
            query_class=task.query_class,
            node_recall=_node_recall(task.expected_nodes, returned_node_keys),
            edge_recall=_recall(set(task.expected_edges), returned_edges),
            returned_nodes=len(retrieved.nodes),
            returned_edges=len(retrieved.edges),
            token_estimate=estimate_tokens(packet),
        ))
    return results


def estimate_tokens(text: str) -> int:
    # Cheap deterministic proxy; replace with tokenizer-specific count in model benchmarks.
    return len(re.findall(r"\w+|[^\s\w]", text))


def results_to_json(results: list[EvalResult]) -> str:
    return json.dumps([result.__dict__ for result in results], indent=2, ensure_ascii=False)


def _recall(expected: set[object], returned: set[object]) -> float:
    if not expected:
        return 1.0
    return len(expected & returned) / len(expected)


def _node_recall(expected: tuple[str, ...], returned: set[str]) -> float:
    if not expected:
        return 1.0
    returned_norm = {_norm_node_key(item) for item in returned if item}
    hits = 0
    for item in expected:
        norm = _norm_node_key(item)
        if norm in returned_norm:
            hits += 1
            continue
        # Also allow expected leaf names to match returned paths.
        if any(path.endswith("/" + item) or path.endswith("\\" + item) for path in returned):
            hits += 1
    return hits / len(expected)


def _norm_node_key(value: str) -> str:
    value = value.strip()
    value = re.sub(r"\(\)$", "", value)
    value = value.replace("\\", "/")
    value = value.rsplit("/", 1)[-1]
    return value.lower()
