from __future__ import annotations

import csv
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from graphgraph.core import Edge, Graph  # noqa: E402
from graphgraph.eval import estimate_tokens  # noqa: E402
from graphgraph.graph.traversal import traversal_policy  # noqa: E402
from graphgraph.io import load_any  # noqa: E402
from graphgraph.packets import render_packet  # noqa: E402
from graphgraph.planning import (  # noqa: E402
    PacketChoice,
    choose_packet_for_subgraph,
    compute_subgraph_stats,
    plan_context,
)

OUT = ROOT / "benchmarks" / "context_graph" / "out"
REAL_GRAPHS = OUT / "real_projects" / "graphs"
RESULTS_CSV = OUT / "real_projects" / "real_project_answerability_limit.csv"
SUMMARY_MD = OUT / "real_projects" / "real_project_answerability_limit.md"

MAX_NODES = 120
NODE_BUDGETS: tuple[int | None, ...] = (80, 120, 160, 240, None)
QUERY_CLASSES = ("direct_lookup", "reverse_lookup", "subsystem_summary", "blast_radius", "multi_hop_path", "negative_query")


@dataclass(frozen=True)
class Task:
    query_class: str
    starts: tuple[str, ...]
    expected_nodes: frozenset[str]
    expected_edges: frozenset[tuple[str, str, str]]
    negative: bool = False


@dataclass(frozen=True)
class Candidate:
    name: str
    hops: int
    packet: str
    max_nodes: int | None = MAX_NODES
    direction: str = "both"


def make_tasks(graph: Graph) -> list[Task]:
    active_nodes = [nid for nid, node in graph.nodes.items() if node.active]
    if not active_nodes:
        return []
    outgoing = graph.outgoing()
    incoming = graph.incoming()
    degree = graph.degree()

    def first_with(index: dict[str, list[Edge]]) -> str:
        return max((nid for nid in active_nodes if index.get(nid)), key=lambda nid: len(index.get(nid, ())), default=active_nodes[0])

    hub = max(active_nodes, key=lambda nid: degree.get(nid, 0))
    sparse = min(active_nodes, key=lambda nid: degree.get(nid, 0))
    isolated = next((nid for nid in active_nodes if degree.get(nid, 0) == 0), None)
    direct = first_with(outgoing)
    reverse = first_with(incoming)
    path_start, path_edges = two_edge_path(
        graph,
        direct,
        allowed_relations=frozenset(traversal_policy("multi_hop_path").preferred_relations),
    )
    if not path_edges:
        path_start = direct
        path_edges = tuple(edge_key(edge) for edge in outgoing.get(direct, [])[:1])
    path_anchors = path_anchor_nodes(path_start, path_edges)

    blast_nodes, blast_edges = graph.expand([hub], hops=2, max_nodes=MAX_NODES)
    summary_nodes, summary_edges = graph.expand([hub], hops=1, max_nodes=MAX_NODES)

    direct_edges = tuple(edge_key(edge) for edge in outgoing.get(direct, [])[:3])
    reverse_edges = tuple(edge_key(edge) for edge in incoming.get(reverse, [])[:3])

    if isolated is not None:
        negative_start = isolated
        negative_edges: tuple[tuple[str, str, str], ...] = ()
        negative = True
    else:
        negative_start = sparse
        incident = outgoing.get(sparse, []) + incoming.get(sparse, [])
        negative_edges = tuple(dict.fromkeys(edge_key(edge) for edge in incident[:3]))
        negative = False

    return [
        Task("direct_lookup", (direct,), nodes_from_edges(direct, direct_edges), frozenset(direct_edges)),
        Task("reverse_lookup", (reverse,), nodes_from_edges(reverse, reverse_edges), frozenset(reverse_edges)),
        Task("subsystem_summary", (hub,), frozenset(summary_nodes), frozenset(edge_key(edge) for edge in summary_edges)),
        Task("blast_radius", (hub,), frozenset(blast_nodes), frozenset(edge_key(edge) for edge in blast_edges)),
        Task("multi_hop_path", path_anchors, nodes_from_edge_keys(path_start, path_edges), frozenset(path_edges)),
        Task(
            "negative_query",
            (negative_start,),
            nodes_from_edges(negative_start, negative_edges),
            frozenset(negative_edges),
            negative=negative,
        ),
    ]


def two_edge_path(
    graph: Graph,
    start: str,
    allowed_relations: frozenset[str] | None = None,
) -> tuple[str, tuple[tuple[str, str, str], ...]]:
    outgoing = graph.outgoing()

    def eligible(node_id: str) -> list[Edge]:
        edges = outgoing.get(node_id, [])
        if allowed_relations is None:
            return edges
        return [edge for edge in edges if edge.type in allowed_relations]

    for first in eligible(start):
        for second in eligible(first.target):
            if second.target != start:
                return start, (edge_key(first), edge_key(second))
    for node_id in graph.nodes:
        for first in eligible(node_id):
            for second in eligible(first.target):
                if second.target != node_id:
                    return node_id, (edge_key(first), edge_key(second))
    return start, ()


def edge_key(edge: Edge) -> tuple[str, str, str]:
    return (edge.source, edge.target, edge.type)


def nodes_from_edges(start: str, edges: tuple[tuple[str, str, str], ...]) -> frozenset[str]:
    return nodes_from_edge_keys(start, edges)


def path_anchor_nodes(start: str, edges: tuple[tuple[str, str, str], ...]) -> tuple[str, ...]:
    if not edges:
        return (start,)
    target = edges[-1][1]
    return (start,) if target == start else (start, target)


def nodes_from_edge_keys(start: str, edges: tuple[tuple[str, str, str], ...]) -> frozenset[str]:
    nodes = {start}
    for source, target, _kind in edges:
        nodes.add(source)
        nodes.add(target)
    return frozenset(nodes)


def candidates_for(query_class: str) -> list[Candidate]:
    current = plan_context(query_class)
    candidates = [
        Candidate("current_default", current.hops, current.packet, current.node_budget, current.direction),
        Candidate("current_120", current.hops, current.packet, MAX_NODES, current.direction),
        Candidate("current_unbounded", current.hops, current.packet, None, current.direction),
        Candidate("gg_max_0hop", 0, "gg_max"),
        Candidate("gg_max_1hop", 1, "gg_max"),
        Candidate("gg_max_2hop", 2, "gg_max"),
        Candidate("gg_max_3hop", 3, "gg_max"),
        Candidate("semantic_0hop", 0, "semantic_arrow"),
        Candidate("semantic_1hop", 1, "semantic_arrow"),
        Candidate("semantic_2hop", 2, "semantic_arrow"),
    ]
    for budget in NODE_BUDGETS:
        label = "unbounded" if budget is None else str(budget)
        candidates.append(Candidate(f"current_budget_{label}", current.hops, current.packet, budget, current.direction))
    if query_class == "direct_lookup":
        for budget in NODE_BUDGETS:
            label = "unbounded" if budget is None else str(budget)
            candidates.append(Candidate(f"directional_out_budget_{label}", current.hops, current.packet, budget, "out"))
    if query_class == "reverse_lookup":
        for budget in NODE_BUDGETS:
            label = "unbounded" if budget is None else str(budget)
            candidates.append(Candidate(f"directional_in_budget_{label}", current.hops, current.packet, budget, "in"))
    if query_class != "negative_query":
        candidates.append(Candidate("doc_summary_1hop", 1, "doc_summary"))
    return dedupe_candidates(candidates)


def dedupe_candidates(candidates: list[Candidate]) -> list[Candidate]:
    seen: set[tuple[str, int, str, int | None, str]] = set()
    out = []
    for candidate in candidates:
        key = (candidate.name, candidate.hops, candidate.packet, candidate.max_nodes, candidate.direction)
        if key not in seen:
            seen.add(key)
            out.append(candidate)
    return out


def run() -> list[dict[str, object]]:
    if not REAL_GRAPHS.exists():
        return []

    rows: list[dict[str, object]] = []
    for graph_path in sorted(REAL_GRAPHS.glob("*.json")):
        graph = load_any(graph_path)
        for task in make_tasks(graph):
            for candidate in candidates_for(task.query_class):
                nodes, edges = expand_directional(graph, list(task.starts), candidate.hops, candidate.max_nodes, candidate.direction)
                choice = PacketChoice(candidate.hops, candidate.packet, candidate.name)
                if candidate.name.startswith("current"):
                    choice = choose_packet_for_subgraph(choice, compute_subgraph_stats(graph, nodes, edges))
                packet = render_packet(graph, nodes, edges, choice.packet)
                returned_edges = {edge_key(edge) for edge in edges}
                node_recall = recall(task.expected_nodes, nodes)
                edge_recall = recall(task.expected_edges, returned_edges)
                negative_ok = (len(edges) == 0) if task.negative else True
                answerable = node_recall >= 1.0 and edge_recall >= 1.0 and negative_ok
                rows.append(
                    {
                        "project": graph_path.stem,
                        "query_class": task.query_class,
                        "starts": ";".join(task.starts),
                        "candidate": candidate.name,
                        "hops": candidate.hops,
                        "max_nodes": "" if candidate.max_nodes is None else candidate.max_nodes,
                        "direction": candidate.direction,
                        "packet": choice.packet,
                        "nodes": len(nodes),
                        "edges": len(edges),
                        "tokens": estimate_tokens(packet),
                        "expected_nodes": len(task.expected_nodes),
                        "expected_edges": len(task.expected_edges),
                        "node_recall": node_recall,
                        "edge_recall": edge_recall,
                        "negative_ok": negative_ok,
                        "answerable": answerable,
                    }
                )
    return rows


def write(rows: list[dict[str, object]]) -> None:
    RESULTS_CSV.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "project",
        "query_class",
        "starts",
        "candidate",
        "hops",
        "max_nodes",
        "direction",
        "packet",
        "nodes",
        "edges",
        "tokens",
        "expected_nodes",
        "expected_edges",
        "node_recall",
        "edge_recall",
        "negative_ok",
        "answerable",
    ]
    with RESULTS_CSV.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    current_rows = [row for row in rows if row["candidate"] == "current_default"]
    current_120_rows = [row for row in rows if row["candidate"] == "current_120"]
    current_unbounded_rows = [row for row in rows if row["candidate"] == "current_unbounded"]
    winners = cheapest_answerable(rows)
    winner_rows = list(winners.values())
    current_answerable = sum(1 for row in current_rows if truthy(row["answerable"]))
    current_120_answerable = sum(1 for row in current_120_rows if truthy(row["answerable"]))
    current_unbounded_answerable = sum(1 for row in current_unbounded_rows if truthy(row["answerable"]))
    current_token_avg = avg(current_rows, "tokens")
    current_120_token_avg = avg(current_120_rows, "tokens")
    current_unbounded_token_avg = avg(current_unbounded_rows, "tokens")
    winner_token_avg = avg(winner_rows, "tokens")

    lines = [
        "# Raw Structural Policy Limit",
        "",
        "This benchmark applies raw Graph.expand candidates to synthetic exact-edge",
        "fixtures. It fits planner lower bounds; it does not execute the production",
        "retrieval pipeline. See production_retrieval_benchmark.py for that gate.",
        "",
        f"Cases: `{len(current_rows)}` tasks",
        f"Planner-default raw expansion contains fixture evidence: `{current_answerable}/{len(current_rows)}` (`{pct(current_answerable, len(current_rows)):.1f}%`)",
        f"Uniform `{MAX_NODES}` node policy answerable: `{current_120_answerable}/{len(current_120_rows)}` (`{pct(current_120_answerable, len(current_120_rows)):.1f}%`)",
        f"Unbounded policy answerable: `{current_unbounded_answerable}/{len(current_unbounded_rows)}` (`{pct(current_unbounded_answerable, len(current_unbounded_rows)):.1f}%`)",
        f"Planner-default raw expansion avg tokens: `{current_token_avg:.1f}`",
        f"Uniform `{MAX_NODES}` avg tokens: `{current_120_token_avg:.1f}`",
        f"Current unbounded avg tokens: `{current_unbounded_token_avg:.1f}`",
        f"Cheapest answerable avg tokens: `{winner_token_avg:.1f}`",
        f"Planner-default premium vs cheapest fixture-complete candidate: `{((current_token_avg / winner_token_avg) - 1.0) * 100.0 if winner_token_avg else 0.0:.3f}%`",
        "",
        "## Cheapest Answerable By Query Class",
        "",
        "| Query class | Winner candidates | Avg winner tokens | Default tokens | Default answerable | Current 120 tokens | Current 120 answerable | Current unbounded answerable |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for query_class in QUERY_CLASSES:
        qc_winners = [row for key, row in winners.items() if key[1] == query_class]
        qc_current = [row for row in current_rows if row["query_class"] == query_class]
        qc_120 = [row for row in current_120_rows if row["query_class"] == query_class]
        qc_unbounded = [row for row in current_unbounded_rows if row["query_class"] == query_class]
        names = ", ".join(
            f"{row['candidate']}:{row['packet']}:{row['hops']}hop:{row['max_nodes'] or 'unbounded'}"
            for row in sorted(qc_winners, key=lambda row: (str(row["project"]), str(row["candidate"])))[:4]
        )
        if len(qc_winners) > 4:
            names += ", ..."
        lines.append(
            f"| {query_class} | {names} | {avg(qc_winners, 'tokens'):.1f} | "
            f"{avg(qc_current, 'tokens'):.1f} | {sum(1 for row in qc_current if truthy(row['answerable']))}/{len(qc_current)} | "
            f"{avg(qc_120, 'tokens'):.1f} | {sum(1 for row in qc_120 if truthy(row['answerable']))}/{len(qc_120)} | "
            f"{sum(1 for row in qc_unbounded if truthy(row['answerable']))}/{len(qc_unbounded)} |"
        )

    lines.extend([
        "",
        "## Current Budget Sweep",
        "",
        "| Budget | Answerable | Avg tokens |",
        "| ---: | ---: | ---: |",
    ])
    for budget in NODE_BUDGETS:
        label = "unbounded" if budget is None else str(budget)
        candidate_rows = [row for row in rows if row["candidate"] == f"current_budget_{label}"]
        lines.append(
            f"| {label} | {sum(1 for row in candidate_rows if truthy(row['answerable']))}/{len(candidate_rows)} | "
            f"{avg(candidate_rows, 'tokens'):.1f} |"
        )

    lines.extend([
        "",
        "## Budget Sweep By Query Class",
        "",
        "| Query class | Budget | Answerable | Avg tokens |",
        "| --- | ---: | ---: | ---: |",
    ])
    for query_class in QUERY_CLASSES:
        for budget in NODE_BUDGETS:
            label = "unbounded" if budget is None else str(budget)
            candidate_rows = [
                row for row in rows
                if row["query_class"] == query_class and row["candidate"] == f"current_budget_{label}"
            ]
            lines.append(
                f"| {query_class} | {label} | {sum(1 for row in candidate_rows if truthy(row['answerable']))}/{len(candidate_rows)} | "
                f"{avg(candidate_rows, 'tokens'):.1f} |"
            )

    lines.extend([
        "",
        "## Directional Lookup Sweep",
        "",
        "| Query class | Direction | Budget | Answerable | Avg tokens |",
        "| --- | --- | ---: | ---: | ---: |",
    ])
    for query_class, direction, prefix in (
        ("direct_lookup", "out", "directional_out_budget"),
        ("reverse_lookup", "in", "directional_in_budget"),
    ):
        for budget in NODE_BUDGETS:
            label = "unbounded" if budget is None else str(budget)
            candidate_rows = [
                row for row in rows
                if row["query_class"] == query_class and row["candidate"] == f"{prefix}_{label}"
            ]
            lines.append(
                f"| {query_class} | {direction} | {label} | "
                f"{sum(1 for row in candidate_rows if truthy(row['answerable']))}/{len(candidate_rows)} | "
                f"{avg(candidate_rows, 'tokens'):.1f} |"
            )

    failures = [row for row in current_rows if not truthy(row["answerable"])]
    if failures:
        lines.extend([
            "",
            "## Current Policy Failures",
            "",
            "| Project | Query class | Hops | Packet | Node recall | Edge recall | Negative OK |",
            "| --- | --- | ---: | --- | ---: | ---: | --- |",
        ])
        for row in failures:
            lines.append(
                f"| {row['project']} | {row['query_class']} | {row['hops']} | {row['packet']} | "
                f"{float(row['node_recall']):.3f} | {float(row['edge_recall']):.3f} | {row['negative_ok']} |"
            )

    lines.extend([
        "",
        "## Operational Read",
        "",
        "- This is a raw-expansion fixture-containment oracle, not production retrieval or live model comprehension.",
        "- If current routing is answerable and near the cheapest answerable policy, the token frontier is structurally defensible.",
        "- Any cheaper failing policy is below the mathematical limit because it omits required answer evidence.",
        "",
        f"CSV: `{RESULTS_CSV.relative_to(ROOT)}`",
    ])
    SUMMARY_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def cheapest_answerable(rows: list[dict[str, object]]) -> dict[tuple[str, str], dict[str, object]]:
    grouped: dict[tuple[str, str], list[dict[str, object]]] = {}
    for row in rows:
        key = (str(row["project"]), str(row["query_class"]))
        grouped.setdefault(key, []).append(row)
    winners = {}
    for key, items in grouped.items():
        answerable = [row for row in items if truthy(row["answerable"])]
        if answerable:
            winners[key] = min(answerable, key=lambda row: (float(row["tokens"]), int(row["hops"]), str(row["packet"])))
    return winners


def expand_directional(
    graph: Graph,
    starts: list[str],
    hops: int,
    max_nodes: int | None,
    direction: str,
) -> tuple[set[str], list[Edge]]:
    if direction == "both":
        return graph.expand(starts, hops=hops, max_nodes=max_nodes)
    outgoing = graph.outgoing()
    incoming = graph.incoming()
    index = outgoing if direction == "out" else incoming
    included = {start for start in starts if start in graph.nodes and graph.nodes[start].active}
    frontier = set(included)
    seen_edges: set[tuple[str, str, str]] = set()
    out_edges: list[Edge] = []
    for _hop in range(hops):
        next_frontier: set[str] = set()
        for node_id in frontier:
            for edge in index.get(node_id, []):
                neighbor = edge.target if direction == "out" else edge.source
                if neighbor not in graph.nodes or not graph.nodes[neighbor].active:
                    continue
                if max_nodes is not None and neighbor not in included and len(included) + len(next_frontier) >= max_nodes:
                    continue
                next_frontier.add(neighbor)
                key = edge_key(edge)
                if key not in seen_edges:
                    seen_edges.add(key)
                    out_edges.append(edge)
        included |= next_frontier
        frontier = next_frontier
        if not frontier:
            break
    return included, out_edges


def recall(expected: frozenset[object], returned: set[object]) -> float:
    if not expected:
        return 1.0
    return len(expected & returned) / len(expected)


def avg(rows: list[dict[str, object]], key: str) -> float:
    values = [float(row[key]) for row in rows if row.get(key) not in {"", None}]
    return sum(values) / max(1, len(values))


def pct(numerator: int, denominator: int) -> float:
    return numerator / max(1, denominator) * 100.0


def truthy(value: object) -> bool:
    return value is True or str(value).lower() == "true"


def main() -> None:
    rows = run()
    if not rows:
        RESULTS_CSV.parent.mkdir(parents=True, exist_ok=True)
        RESULTS_CSV.write_text("", encoding="utf-8")
        SUMMARY_MD.write_text(
            "# Raw Structural Policy Limit\n\n"
            "Skipped: no saved real-project graph files were found. "
            "Run `real_project_packet_balance.py` first.\n",
            encoding="utf-8",
        )
        print(SUMMARY_MD.read_text(encoding="utf-8"))
        return
    write(rows)
    print(SUMMARY_MD.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
