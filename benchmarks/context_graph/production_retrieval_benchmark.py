from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

try:  # Package import under pytest.
    from .real_project_answerability_limit import REAL_GRAPHS, edge_key, make_tasks, recall
except ImportError:  # Direct script execution from benchmarks/context_graph.
    from real_project_answerability_limit import REAL_GRAPHS, edge_key, make_tasks, recall  # type: ignore[no-redef]

from graphgraph.analysis.eval import estimate_tokens  # noqa: E402
from graphgraph.graph.ontology import relation_spec  # noqa: E402
from graphgraph.graph.traversal import (  # noqa: E402
    BLAST_IMPACT_RELATIONS,
    BLAST_OUTGOING_RELATIONS,
    BLAST_SUPPORT_RELATIONS,
    relation_rank,
    traversal_policy,
)
from graphgraph.io import load_any  # noqa: E402
from graphgraph.packets import render_packet  # noqa: E402
from graphgraph.planning import plan_context  # noqa: E402
from graphgraph.retrieval.context import apply_shape_budget, expand_context  # noqa: E402

OUT = ROOT / "benchmarks" / "context_graph" / "out" / "real_projects"
REPORT_JSON = OUT / "production_retrieval.json"
REPORT_MD = OUT / "production_retrieval.md"


def main() -> None:
    rows = []
    for graph_path in sorted(REAL_GRAPHS.glob("*.json")):
        graph = load_any(graph_path)
        for task in make_tasks(graph):
            plan = plan_context(task.query_class)
            plan = apply_shape_budget(graph, plan, "")
            nodes, edges = expand_context(graph, task.starts, plan)
            returned_edges = {edge_key(edge) for edge in edges}
            required_groups = production_evidence_requirements(graph, task)
            evidence_group_recall = (
                float(path_connected(task.starts, returned_edges, plan.hops))
                if task.query_class == "multi_hop_path"
                else requirement_recall(required_groups, returned_edges)
            )
            anchor_recall = recall(frozenset(task.starts), nodes)
            raw_node_recall = recall(task.expected_nodes, nodes)
            raw_edge_recall = recall(task.expected_edges, returned_edges)
            negative_ok = (not edges) if task.negative else True
            packet = render_packet(graph, nodes, edges, plan.packet)
            rows.append(
                {
                    "project": graph_path.stem,
                    "query_class": task.query_class,
                    "nodes": len(nodes),
                    "edges": len(edges),
                    "tokens": estimate_tokens(packet),
                    "anchor_recall": anchor_recall,
                    "evidence_group_recall": evidence_group_recall,
                    "raw_node_recall": raw_node_recall,
                    "raw_edge_recall": raw_edge_recall,
                    "negative_ok": negative_ok,
                    "minimum_evidence_met": anchor_recall >= 1.0 and evidence_group_recall >= 1.0 and negative_ok,
                    "full_raw_coverage": raw_node_recall >= 1.0 and raw_edge_recall >= 1.0 and negative_ok,
                }
            )

    report = summarize(rows)
    OUT.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(json.dumps(report, indent=2), encoding="utf-8")
    REPORT_MD.write_text(render_markdown(report), encoding="utf-8")
    print(REPORT_MD.read_text(encoding="utf-8"))


def production_evidence_requirements(graph, task) -> tuple[frozenset[tuple[str, str, str]], ...]:
    """Return alternative edge groups required by the query's semantic contract.

    Each group is satisfied when retrieval returns at least one member. Path
    and non-isolated negative tasks use singleton groups because their exact
    edges are the evidence; fanout/summary tasks use relation or direction
    groups so graph insertion order does not define correctness.
    """
    if task.query_class == "multi_hop_path":
        return ()
    if task.query_class == "negative_query":
        return tuple(frozenset({edge}) for edge in sorted(task.expected_edges))

    policy = traversal_policy(task.query_class)
    outgoing = [edge for start in task.starts for edge in graph.outgoing().get(start, ()) if edge.active]
    incoming = [edge for start in task.starts for edge in graph.incoming().get(start, ()) if edge.active]

    if task.query_class == "direct_lookup":
        groups = [_edge_group(_preferred_edges(outgoing, policy))]
    elif task.query_class == "reverse_lookup":
        groups = [_edge_group(_preferred_edges(incoming, policy))]
    elif task.query_class == "subsystem_summary":
        by_family: dict[str, list] = defaultdict(list)
        for edge in _preferred_edges(outgoing + incoming, policy):
            by_family[relation_spec(edge.type).family].append(edge)
        groups = [_edge_group(edges) for _family, edges in list(by_family.items())[:4]]
    elif task.query_class == "blast_radius":
        groups = [
            _edge_group(edge for edge in incoming if edge.type in BLAST_IMPACT_RELATIONS),
            _edge_group(edge for edge in outgoing + incoming if edge.type in BLAST_SUPPORT_RELATIONS),
            _edge_group(edge for edge in outgoing if edge.type in BLAST_OUTGOING_RELATIONS),
        ]
    else:
        groups = []
    return tuple(group for group in groups if group)


def _edge_group(edges) -> frozenset[tuple[str, str, str]]:
    return frozenset(edge_key(edge) for edge in edges)


def requirement_recall(
    required_groups: tuple[frozenset[tuple[str, str, str]], ...],
    returned_edges: set[tuple[str, str, str]],
) -> float:
    if not required_groups:
        return 1.0
    satisfied = sum(bool(group & returned_edges) for group in required_groups)
    return satisfied / len(required_groups)


def path_connected(
    starts: tuple[str, ...],
    returned_edges: set[tuple[str, str, str]],
    max_hops: int,
) -> bool:
    if len(starts) < 2:
        return bool(starts)
    adjacency: dict[str, set[str]] = defaultdict(set)
    for source, target, _relation in returned_edges:
        adjacency[source].add(target)
        adjacency[target].add(source)
    targets = set(starts[1:])
    frontier = {starts[0]}
    visited = set(frontier)
    for _ in range(max_hops):
        frontier = {
            neighbor
            for node_id in frontier
            for neighbor in adjacency.get(node_id, ())
            if neighbor not in visited
        }
        if targets <= visited | frontier:
            return True
        visited.update(frontier)
    return targets <= visited


def _preferred_edges(edges, policy) -> list:
    recognized = [edge for edge in edges if edge.type in policy.preferred_relations]
    eligible = recognized or edges
    return sorted(eligible, key=lambda edge: (*relation_rank(edge.type, policy), edge.source, edge.target))


def summarize(rows: list[dict[str, object]]) -> dict[str, object]:
    grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["query_class"])].append(row)

    def average(items: list[dict[str, object]], key: str) -> float:
        return sum(float(item[key]) for item in items) / max(1, len(items))

    by_class = {}
    for query_class, items in sorted(grouped.items()):
        by_class[query_class] = {
            "cases": len(items),
            "minimum_evidence_met": sum(bool(item["minimum_evidence_met"]) for item in items),
            "full_raw_coverage": sum(bool(item["full_raw_coverage"]) for item in items),
            "avg_tokens": average(items, "tokens"),
            "avg_anchor_recall": average(items, "anchor_recall"),
            "avg_evidence_group_recall": average(items, "evidence_group_recall"),
            "avg_raw_node_recall": average(items, "raw_node_recall"),
            "avg_raw_edge_recall": average(items, "raw_edge_recall"),
        }
    return {
        "cases": len(rows),
        "minimum_evidence_met": sum(bool(row["minimum_evidence_met"]) for row in rows),
        "full_raw_coverage": sum(bool(row["full_raw_coverage"]) for row in rows),
        "avg_tokens": average(rows, "tokens"),
        "by_class": by_class,
        "evidence_failures": [row for row in rows if not row["minimum_evidence_met"]],
    }


def render_markdown(report: dict[str, object]) -> str:
    lines = [
        "# Production Retrieval Benchmark",
        "",
        "This runs the actual policy-bounded production expansion. Query-semantic",
        "requirements are derived independently from graph topology and traversal",
        "contracts; raw-neighborhood coverage separately measures pruning aggressiveness.",
        "",
        f"- Minimum query-semantic evidence met: `{report['minimum_evidence_met']}/{report['cases']}`",
        f"- Full raw-neighborhood coverage: `{report['full_raw_coverage']}/{report['cases']}`",
        f"- Average tokens: `{report['avg_tokens']:.1f}`",
        "",
        "| Query class | Minimum evidence | Full raw coverage | Avg tokens | Anchor recall | Evidence-group recall |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for query_class, row in report["by_class"].items():
        lines.append(
            f"| {query_class} | {row['minimum_evidence_met']}/{row['cases']} | "
            f"{row['full_raw_coverage']}/{row['cases']} | {row['avg_tokens']:.1f} | "
            f"{row['avg_anchor_recall']:.3f} | {row['avg_evidence_group_recall']:.3f} |"
        )
    if report["evidence_failures"]:
        lines.extend(["", "## Evidence Failures", "", "| Project | Class | Anchor recall | Evidence-group recall |", "| --- | --- | ---: | ---: |"])
        for row in report["evidence_failures"]:
            lines.append(
                f"| {row['project']} | {row['query_class']} | "
                f"{row['anchor_recall']:.3f} | {row['evidence_group_recall']:.3f} |"
            )
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
