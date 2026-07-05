from __future__ import annotations

import csv
import heapq
import sys
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from graphgraph.core import Edge, Graph  # noqa: E402
from graphgraph.eval import estimate_tokens  # noqa: E402
from graphgraph.io import load_any  # noqa: E402
from graphgraph.ontology import is_weak_relation, provenance_confidence, traversal_strength  # noqa: E402
from graphgraph.packets import render_packet  # noqa: E402
from graphgraph.retrieval.text import tokenize  # noqa: E402


OUT = ROOT / "benchmarks" / "context_graph" / "out" / "real_projects"
GRAPHS = OUT / "graphs"
RESULTS_CSV = OUT / "frontier_policy_results.csv"
SUMMARY_MD = OUT / "frontier_policy_report.md"

POLICIES = (
    "current_expand",
    "current_out",
    "current_in",
    "relation_strength",
    "degree_penalty",
    "query_overlap",
    "marginal_gain",
)


@dataclass(frozen=True)
class FrontierTask:
    project: str
    kind: str
    query: str
    starts: tuple[str, ...]
    expected_nodes: frozenset[str]
    expected_edges: frozenset[tuple[str, str, str]]
    hops: int
    max_nodes: int


def edge_key(edge: Edge) -> tuple[str, str, str]:
    return edge.source, edge.target, edge.type


def node_terms(graph: Graph, node_id: str) -> set[str]:
    node = graph.nodes.get(node_id)
    if not node:
        return set()
    text = " ".join(part for part in (node.id, node.label, node.path, node.summary, " ".join(node.facts)) if part)
    return set(tokenize(text, keep_stopwords=True))


def query_from_nodes(graph: Graph, node_ids: tuple[str, ...]) -> str:
    terms: list[str] = []
    for node_id in node_ids:
        node = graph.nodes.get(node_id)
        if not node:
            continue
        terms.extend(tokenize(node.label or node.path or node.id, keep_stopwords=True))
    deduped = [term for term in dict.fromkeys(terms) if len(term) >= 3]
    return " ".join(deduped[:8]) or " ".join(node_ids)


def make_tasks(project: str, graph: Graph) -> list[FrontierTask]:
    tasks: list[FrontierTask] = []
    tasks.extend(make_path_tasks(project, graph))
    tasks.extend(make_hub_tasks(project, graph))
    return tasks


def make_path_tasks(project: str, graph: Graph, limit: int = 4) -> list[FrontierTask]:
    outgoing = graph.outgoing()
    degree = graph.degree()
    starts = sorted(
        (node_id for node_id, edges in outgoing.items() if graph.nodes.get(node_id) and graph.nodes[node_id].active and edges),
        key=lambda node_id: (degree.get(node_id, 0), node_id),
        reverse=True,
    )
    tasks: list[FrontierTask] = []
    seen: set[tuple[str, str]] = set()
    for start in starts:
        path = best_two_hop_path(graph, start)
        if not path:
            continue
        end = path[-1].target
        if (start, end) in seen or end == start:
            continue
        expected_edges = frozenset(edge_key(edge) for edge in path)
        expected_nodes = frozenset({start, *(edge.source for edge in path), *(edge.target for edge in path)})
        
        # Verify baseline answerability before including the task
        nodes_ret, edges_ret = graph.expand([start, end], hops=2, max_nodes=80)
        ret_edge_keys = {edge_key(e) for e in edges_ret}
        if not (expected_nodes <= nodes_ret and expected_edges <= ret_edge_keys):
            continue

        seen.add((start, end))
        query = query_from_nodes(graph, (start, end))
        tasks.append(
            FrontierTask(
                project=project,
                kind="hard_path_2hop",
                query=query,
                starts=(start, end),
                expected_nodes=expected_nodes,
                expected_edges=expected_edges,
                hops=2,
                max_nodes=80,
            )
        )
        if len(tasks) >= limit:
            break
    return tasks


def best_two_hop_path(graph: Graph, start: str) -> tuple[Edge, Edge] | None:
    outgoing = graph.outgoing()
    degree = graph.degree()
    candidates: list[tuple[float, Edge, Edge]] = []
    for first in outgoing.get(start, []):
        if first.target == start:
            continue
        for second in outgoing.get(first.target, []):
            if second.target in {start, first.source}:
                continue
            score = edge_score(graph, first, set()) + edge_score(graph, second, set())
            score += 0.01 * degree.get(second.target, 0)
            candidates.append((score, first, second))
    if not candidates:
        return None
    _score, first, second = max(candidates, key=lambda item: item[0])
    return first, second


def make_hub_tasks(project: str, graph: Graph, limit: int = 4) -> list[FrontierTask]:
    outgoing = graph.outgoing()
    degree = graph.degree()
    hubs = sorted(
        (node_id for node_id, edges in outgoing.items() if graph.nodes.get(node_id) and graph.nodes[node_id].active and len(edges) >= 4),
        key=lambda node_id: (len(outgoing.get(node_id, ())), degree.get(node_id, 0), node_id),
        reverse=True,
    )
    tasks: list[FrontierTask] = []
    for hub in hubs:
        query_terms = node_terms(graph, hub)
        best_edges = sorted(outgoing[hub], key=lambda edge: edge_score(graph, edge, query_terms), reverse=True)[:4]
        expected_edges = frozenset(edge_key(edge) for edge in best_edges)
        expected_nodes = frozenset({hub, *(edge.target for edge in best_edges)})
        
        # Verify baseline answerability before including the task
        nodes_ret, edges_ret = graph.expand([hub], hops=1, max_nodes=32)
        ret_edge_keys = {edge_key(e) for e in edges_ret}
        if not (expected_nodes <= nodes_ret and expected_edges <= ret_edge_keys):
            continue

        tasks.append(
            FrontierTask(
                project=project,
                kind="hub_precision",
                query=query_from_nodes(graph, (hub,)),
                starts=(hub,),
                expected_nodes=expected_nodes,
                expected_edges=expected_edges,
                hops=1,
                max_nodes=32,
            )
        )
        if len(tasks) >= limit:
            break
    return tasks


def edge_score(graph: Graph, edge: Edge, query_terms: set[str]) -> float:
    target_terms = node_terms(graph, edge.target)
    overlap = len(query_terms & target_terms) / max(1, len(query_terms)) if query_terms else 0.0
    weak_penalty = 0.35 if is_weak_relation(edge.type) else 1.0
    confidence = edge.confidence * provenance_confidence(edge.provenance)
    return traversal_strength(edge.type) * confidence * weak_penalty + overlap


def expand_policy(graph: Graph, task: FrontierTask, policy: str) -> tuple[set[str], list[Edge]]:
    if policy == "current_expand":
        return graph.expand(list(task.starts), hops=task.hops, max_nodes=task.max_nodes)
    if policy == "current_out":
        return graph.expand(list(task.starts), hops=task.hops, max_nodes=task.max_nodes, direction="out")
    if policy == "current_in":
        return graph.expand(list(task.starts), hops=task.hops, max_nodes=task.max_nodes, direction="in")
    if policy == "relation_strength":
        return scored_expand(graph, task, use_degree_penalty=False, use_query_overlap=False, marginal=False)
    if policy == "degree_penalty":
        return scored_expand(graph, task, use_degree_penalty=True, use_query_overlap=False, marginal=False)
    if policy == "query_overlap":
        return scored_expand(graph, task, use_degree_penalty=False, use_query_overlap=True, marginal=False)
    if policy == "marginal_gain":
        return scored_expand(graph, task, use_degree_penalty=True, use_query_overlap=True, marginal=True)
    raise ValueError(f"unknown policy: {policy}")


def scored_expand(
    graph: Graph,
    task: FrontierTask,
    *,
    use_degree_penalty: bool,
    use_query_overlap: bool,
    marginal: bool,
) -> tuple[set[str], list[Edge]]:
    outgoing = graph.outgoing()
    incoming = graph.incoming()
    degree = graph.degree()
    query_terms = set(tokenize(task.query, keep_stopwords=True))
    included = {start for start in task.starts if start in graph.nodes and graph.nodes[start].active}
    frontier = set(included)
    selected_edges: list[Edge] = []
    seen_edges: set[tuple[str, str, str]] = set()

    for depth in range(task.hops):
        heap: list[tuple[float, str, str, str, str, Edge]] = []
        for node_id in frontier:
            for edge in outgoing.get(node_id, []) + incoming.get(node_id, []):
                neighbor = edge.target if edge.source == node_id else edge.source
                if neighbor not in graph.nodes or not graph.nodes[neighbor].active:
                    continue
                score = traversal_strength(edge.type) * edge.confidence * provenance_confidence(edge.provenance)
                if is_weak_relation(edge.type):
                    score *= 0.35
                if use_query_overlap:
                    terms = node_terms(graph, neighbor)
                    score += 1.5 * (len(query_terms & terms) / max(1, len(query_terms)))
                if use_degree_penalty:
                    score /= 1.0 + (degree.get(neighbor, 0) ** 0.5 / 6.0)
                if marginal and neighbor in included:
                    score *= 0.25
                if marginal:
                    score /= 1.0 + len(selected_edges) / max(8.0, task.max_nodes / 2.0)
                heapq.heappush(heap, (-score, neighbor, edge.source, edge.target, edge.type, edge))

        next_frontier: set[str] = set()
        while heap and len(included | next_frontier) < task.max_nodes:
            _neg_score, neighbor, _source, _target, _type, edge = heapq.heappop(heap)
            key = edge_key(edge)
            if key not in seen_edges:
                seen_edges.add(key)
                selected_edges.append(edge)
            if neighbor not in included:
                next_frontier.add(neighbor)
        included |= next_frontier
        frontier = next_frontier
        if not frontier:
            break

    closed_edges = [edge for edge in selected_edges if edge.source in included and edge.target in included]
    return included, closed_edges


def score_task(graph: Graph, task: FrontierTask, policy: str) -> dict[str, object]:
    nodes, edges = expand_policy(graph, task, policy)
    edge_keys = {edge_key(edge) for edge in edges}
    node_recall = len(task.expected_nodes & nodes) / max(1, len(task.expected_nodes))
    edge_recall = len(task.expected_edges & edge_keys) / max(1, len(task.expected_edges))
    hits = len(task.expected_nodes & nodes)
    irrelevant_ratio = (len(nodes) - hits) / max(1, len(nodes))
    packet = render_packet(graph, nodes, edges, "gg_max")
    return {
        "project": task.project,
        "task_kind": task.kind,
        "policy": policy,
        "query": task.query,
        "starts": ";".join(task.starts),
        "expected_nodes": len(task.expected_nodes),
        "expected_edges": len(task.expected_edges),
        "node_recall": round(node_recall, 4),
        "edge_recall": round(edge_recall, 4),
        "answerable": node_recall >= 1.0 and edge_recall >= 1.0,
        "returned_nodes": len(nodes),
        "returned_edges": len(edges),
        "irrelevant_ratio": round(irrelevant_ratio, 4),
        "tokens": estimate_tokens(packet),
    }


def run() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for graph_path in sorted(GRAPHS.glob("*.json")):
        graph = load_any(graph_path)
        project = graph_path.stem
        for task in make_tasks(project, graph):
            for policy in POLICIES:
                rows.append(score_task(graph, task, policy))
    return rows


def write(rows: list[dict[str, object]]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    fields = [
        "project",
        "task_kind",
        "policy",
        "query",
        "starts",
        "expected_nodes",
        "expected_edges",
        "node_recall",
        "edge_recall",
        "answerable",
        "returned_nodes",
        "returned_edges",
        "irrelevant_ratio",
        "tokens",
    ]
    with RESULTS_CSV.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})

    lines = [
        "# Frontier Policy Benchmark",
        "",
        "Harder expansion-only benchmark over saved real-project graphs.",
        "",
        "Path tasks require exact two-hop edge containment. Hub tasks require the strongest local hub edges while penalizing broad irrelevant expansion.",
        "",
        f"Tasks: `{len({(row['project'], row['task_kind'], row['query'], row['starts']) for row in rows})}`",
        "",
        "## Policy Summary",
        "",
        "| Policy | Answerable | Node recall | Edge recall | Avg tokens | Irrelevant ratio | Avg nodes | Avg edges |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for policy in POLICIES:
        items = [row for row in rows if row["policy"] == policy]
        answerable = sum(1 for row in items if str(row["answerable"]).lower() == "true")
        lines.append(
            f"| `{policy}` | {answerable}/{len(items)} | {avg(items, 'node_recall'):.3f} | "
            f"{avg(items, 'edge_recall'):.3f} | {avg(items, 'tokens'):.1f} | "
            f"{avg(items, 'irrelevant_ratio'):.3f} | {avg(items, 'returned_nodes'):.1f} | {avg(items, 'returned_edges'):.1f} |"
        )

    lines.extend([
        "",
        "## By Task Kind",
        "",
        "| Kind | Policy | Answerable | Edge recall | Avg tokens | Irrelevant ratio |",
        "| --- | --- | ---: | ---: | ---: | ---: |",
    ])
    for kind in sorted({str(row["task_kind"]) for row in rows}):
        for policy in POLICIES:
            items = [row for row in rows if row["task_kind"] == kind and row["policy"] == policy]
            answerable = sum(1 for row in items if str(row["answerable"]).lower() == "true")
            lines.append(
                f"| {kind} | `{policy}` | {answerable}/{len(items)} | {avg(items, 'edge_recall'):.3f} | "
                f"{avg(items, 'tokens'):.1f} | {avg(items, 'irrelevant_ratio'):.3f} |"
            )

    failures = [row for row in rows if row["policy"] == "current_expand" and str(row["answerable"]).lower() != "true"]
    if failures:
        lines.extend([
            "",
            "## Current Expand Failures",
            "",
            "| Project | Kind | Query | Node recall | Edge recall | Nodes | Edges |",
            "| --- | --- | --- | ---: | ---: | ---: | ---: |",
        ])
        for row in failures[:20]:
            lines.append(
                f"| {row['project']} | {row['task_kind']} | {row['query']} | {row['node_recall']} | "
                f"{row['edge_recall']} | {row['returned_nodes']} | {row['returned_edges']} |"
            )

    lines.extend([
        "",
        "## Read",
        "",
        "- This isolates frontier expansion after anchors are known; it does not measure lexical search.",
        "- A runtime promotion requires improving recall or noise without breaking current answerability tests.",
        f"- CSV: `{RESULTS_CSV.relative_to(ROOT)}`",
    ])
    SUMMARY_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def avg(rows: list[dict[str, object]], key: str) -> float:
    values = [float(row[key]) for row in rows if row.get(key) not in {"", None}]
    return sum(values) / max(1, len(values))


def main() -> None:
    rows = run()
    if not rows:
        SUMMARY_MD.write_text(
            "# Frontier Policy Benchmark\n\n"
            "Skipped: no saved real-project graphs found. Run `real_project_packet_balance.py` first.\n",
            encoding="utf-8",
        )
        print(SUMMARY_MD.read_text(encoding="utf-8"))
        return
    write(rows)
    print(SUMMARY_MD.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
