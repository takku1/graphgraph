from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from .graph.core import Edge, Graph
from .io import load_any
from .packets import render_packet
from .planning import choose_packet, choose_packet_for_subgraph, compute_subgraph_stats
from .retrieval import retrieve_context


@dataclass(frozen=True)
class EvalTask:
    query: str
    query_class: str
    expected_nodes: tuple[str, ...] = ()
    expected_edges: tuple[tuple[str, ...], ...] = ()


@dataclass(frozen=True)
class EvalResult:
    query: str
    query_class: str
    node_recall: float
    edge_recall: float
    returned_nodes: int
    returned_edges: int
    token_estimate: int
    mrr: float = 0.0
    ndcg_at_5: float = 0.0
    ndcg_at_10: float = 0.0


def load_eval_tasks(path: Path) -> list[EvalTask]:
    data = json.loads(path.read_text(encoding="utf-8"))
    tasks = _iter_task_records(data)
    out: list[EvalTask] = []
    for task in tasks:
        query = task.get("query", task.get("question"))
        if not query:
            continue
        out.append(EvalTask(
            query=str(query),
            query_class=str(task.get("query_class", "blast_radius")),
            expected_nodes=tuple(str(item) for item in task.get("expected_nodes", [])),
            expected_edges=tuple(tuple(str(part) for part in edge) for edge in task.get("expected_edges", [])),
        ))
    return out


def _iter_task_records(data: object) -> list[dict[str, object]]:
    if isinstance(data, list):
        return [task for task in data if isinstance(task, dict)]
    if not isinstance(data, dict):
        return []
    tasks = data.get("tasks")
    if isinstance(tasks, list):
        return [task for task in tasks if isinstance(task, dict)]
    projects = data.get("projects")
    if isinstance(projects, dict):
        out: list[dict[str, object]] = []
        for project_tasks in projects.values():
            if isinstance(project_tasks, list):
                out.extend(task for task in project_tasks if isinstance(task, dict))
        return out
    return []


def evaluate_graph(graph_path: Path, tasks: list[EvalTask], max_nodes: int | None = None) -> list[EvalResult]:
    graph = load_any(graph_path)
    results: list[EvalResult] = []
    for task in tasks:
        choice = choose_packet(task.query_class, task.query)
        retrieved = retrieve_context(graph, task.query, task.query_class, hops=choice.hops, max_nodes=max_nodes)
        choice = choose_packet_for_subgraph(
            choice,
            compute_subgraph_stats(graph, retrieved.nodes, retrieved.edges),
            query_class=task.query_class,
        )
        packet = render_packet(graph, retrieved.nodes, retrieved.edges, choice.packet)
        returned_labels = {graph.nodes[nid].label for nid in retrieved.nodes if nid in graph.nodes}
        returned_paths = {graph.nodes[nid].path for nid in retrieved.nodes if nid in graph.nodes}
        returned_label_stems = {_strip_known_suffix(label) for label in returned_labels}
        returned_path_stems = {_strip_known_suffix(Path(path).name) for path in returned_paths if path}
        returned_ids = set(retrieved.nodes)
        returned_node_keys = returned_ids | returned_labels | returned_paths | returned_label_stems | returned_path_stems
        returned_edges = {(edge.source, edge.target, edge.type) for edge in retrieved.edges}

        # Rank retrieved nodes by subgraph PageRank for rank-aware metrics
        ranked_nodes = rank_nodes_by_subgraph_pagerank(graph, retrieved.nodes, retrieved.edges)
        
        # Map expected node names/paths to resolved node IDs in ranked_nodes
        expected_ids = set()
        for item in task.expected_nodes:
            norm_item = _norm_node_key(item)
            for nid in retrieved.nodes:
                node = graph.nodes.get(nid)
                if node:
                    if _norm_node_key(nid) == norm_item or _norm_node_key(node.label) == norm_item or _norm_node_key(node.path) == norm_item:
                        expected_ids.add(nid)
                    elif node.path and (node.path.replace("\\", "/").endswith("/" + item) or node.path.replace("\\", "/").endswith("/" + item.replace("\\", "/"))):
                        expected_ids.add(nid)

        mrr_val = reciprocal_rank(ranked_nodes, expected_ids)
        ndcg_5 = ndcg_at_k(ranked_nodes, expected_ids, 5)
        ndcg_10 = ndcg_at_k(ranked_nodes, expected_ids, 10)

        results.append(EvalResult(
            query=task.query,
            query_class=task.query_class,
            node_recall=_node_recall(task.expected_nodes, returned_node_keys),
            edge_recall=_edge_recall(task.expected_edges, returned_edges),
            returned_nodes=len(retrieved.nodes),
            returned_edges=len(retrieved.edges),
            token_estimate=estimate_tokens(packet),
            mrr=round(mrr_val, 4),
            ndcg_at_5=round(ndcg_5, 4),
            ndcg_at_10=round(ndcg_10, 4),
        ))
    return results


def reciprocal_rank(ranked_list: list[str], expected_nodes: set[str]) -> float:
    for idx, node_id in enumerate(ranked_list, start=1):
        if node_id in expected_nodes:
            return 1.0 / idx
    return 0.0


def ndcg_at_k(ranked_list: list[str], expected_nodes: set[str], k: int) -> float:
    import math
    k = min(len(ranked_list), k)
    if k <= 0 or not expected_nodes:
        return 0.0
    dcg = sum(
        1.0 / math.log2(idx + 1)
        for idx, node_id in enumerate(ranked_list[:k], start=1)
        if node_id in expected_nodes
    )
    idcg = sum(
        1.0 / math.log2(idx + 1)
        for idx in range(1, min(k, len(expected_nodes)) + 1)
    )
    return dcg / idcg if idcg > 0.0 else 0.0


def rank_nodes_by_subgraph_pagerank(graph: Graph, retrieved_nodes: set[str], retrieved_edges: list[Edge]) -> list[str]:
    active_nodes = {nid: graph.nodes[nid] for nid in retrieved_nodes if nid in graph.nodes}
    if not active_nodes:
        return []
    subgraph = Graph(
        nodes=active_nodes,
        edges=retrieved_edges,
    )
    pr = subgraph.pagerank(damping=0.85, max_iter=20, use_cache=False)
    return sorted(retrieved_nodes, key=lambda nid: pr.get(nid, 0.0), reverse=True)


def estimate_tokens(text: str) -> int:
    # Cheap deterministic proxy; replace with tokenizer-specific count in model benchmarks.
    return len(re.findall(r"\w+|[^\s\w]", text))


def results_to_json(results: list[EvalResult]) -> str:
    return json.dumps([result.__dict__ for result in results], indent=2, ensure_ascii=False)


def _recall(expected: set[object], returned: set[object]) -> float:
    if not expected:
        return 1.0
    return len(expected & returned) / len(expected)


def _edge_recall(expected: tuple[tuple[str, ...], ...], returned: set[tuple[str, str, str]]) -> float:
    if not expected:
        return 1.0
    returned_pairs = {(source, target) for source, target, _type in returned}
    hits = 0
    for edge in expected:
        if len(edge) >= 3:
            if (edge[0], edge[1], edge[2]) in returned:
                hits += 1
        elif len(edge) == 2 and (edge[0], edge[1]) in returned_pairs:
            hits += 1
    return hits / len(expected)


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
    value = _strip_known_suffix(value)
    return value.lower()


def _strip_known_suffix(value: str) -> str:
    return re.sub(r"\.(py|pyi|js|jsx|ts|tsx|rs|go|java|c|h|hpp|cpp|cs|md|rst|txt|json|yaml|yml|toml)$", "", value, flags=re.IGNORECASE)
