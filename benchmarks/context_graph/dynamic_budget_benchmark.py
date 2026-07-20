from __future__ import annotations

import csv
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from real_project_answerability_limit import (  # noqa: E402
    QUERY_CLASSES,
    REAL_GRAPHS,
    Task,
    avg,
    edge_key,
    expand_directional,
    make_tasks,
    recall,
    truthy,
)

from graphgraph.analysis.eval import estimate_tokens  # noqa: E402
from graphgraph.graph.core import Graph  # noqa: E402
from graphgraph.io import load_any  # noqa: E402
from graphgraph.packets import render_packet  # noqa: E402
from graphgraph.planning import (  # noqa: E402  # noqa: E402
    PacketChoice,
    choose_packet_for_subgraph,
    compute_subgraph_stats,
    plan_context,
    profile_graph_shape,
    recommend_context_window,
    recommend_node_budget,
    recommend_observed_context_window,
)

OUT = ROOT / "benchmarks" / "context_graph" / "out" / "real_projects"
RESULTS_CSV = OUT / "dynamic_budget_results.csv"
SUMMARY_MD = OUT / "dynamic_budget_report.md"


@dataclass(frozen=True)
class DynamicCandidate:
    name: str
    max_nodes: int | None
    reason: str
    target_tokens: int | None = None
    estimated_tokens: int | None = None
    saturation: float | None = None
    page_node_budget: int | None = None
    mode: str = ""


def candidates_for(graph: Graph, query_class: str) -> list[DynamicCandidate]:
    plan = plan_context(query_class)
    shape = profile_graph_shape(graph)
    recommended = recommend_node_budget(query_class, "", shape)
    window = recommend_context_window(query_class, "", shape)
    candidates = [
        DynamicCandidate("current_default", plan.node_budget, "measured production default"),
        DynamicCandidate("shape_recommended", recommended.recommended_budget, recommended.reason),
        DynamicCandidate(
            "context_window",
            window.recommended_budget,
            window.reason,
            window.target_tokens,
            window.estimated_tokens,
            window.saturation,
            window.page_node_budget,
            window.mode,
        ),
        DynamicCandidate("observed_window", plan.node_budget, "calibrated from first rendered packet"),
    ]
    return dedupe(candidates)


def dedupe(candidates: list[DynamicCandidate]) -> list[DynamicCandidate]:
    seen: set[tuple[str, int | None]] = set()
    out: list[DynamicCandidate] = []
    for candidate in candidates:
        key = (candidate.name, candidate.max_nodes)
        if key not in seen:
            seen.add(key)
            out.append(candidate)
    return out


def score_candidate(graph: Graph, task: Task, candidate: DynamicCandidate) -> dict[str, object]:
    plan = plan_context(task.query_class)
    if candidate.name == "observed_window":
        candidate = observed_window_candidate(graph, task, plan)
    nodes, edges = expand_directional(graph, list(task.starts), plan.hops, candidate.max_nodes, plan.direction)
    choice = PacketChoice(plan.hops, plan.packet, candidate.name)
    choice = choose_packet_for_subgraph(choice, compute_subgraph_stats(graph, nodes, edges), query_class=task.query_class)
    packet = render_packet(graph, nodes, edges, choice.packet)
    tokens = estimate_tokens(packet)
    actual_saturation = tokens / candidate.target_tokens if candidate.target_tokens else None
    returned_edges = {edge_key(edge) for edge in edges}
    node_recall = recall(task.expected_nodes, nodes)
    edge_recall = recall(task.expected_edges, returned_edges)
    negative_ok = (len(edges) == 0) if task.negative else True
    answerable = node_recall >= 1.0 and edge_recall >= 1.0 and negative_ok
    irrelevant_ratio = (len(nodes) - len(task.expected_nodes & nodes)) / max(1, len(nodes))
    return {
        "query_class": task.query_class,
        "candidate": candidate.name,
        "max_nodes": "" if candidate.max_nodes is None else candidate.max_nodes,
        "reason": candidate.reason,
        "target_tokens": "" if candidate.target_tokens is None else candidate.target_tokens,
        "estimated_tokens": "" if candidate.estimated_tokens is None else candidate.estimated_tokens,
        "estimated_saturation": "" if candidate.saturation is None else candidate.saturation,
        "actual_saturation": "" if actual_saturation is None else round(actual_saturation, 4),
        "page_node_budget": "" if candidate.page_node_budget is None else candidate.page_node_budget,
        "window_mode": candidate.mode,
        "packet": choice.packet,
        "nodes": len(nodes),
        "edges": len(edges),
        "tokens": tokens,
        "node_recall": node_recall,
        "edge_recall": edge_recall,
        "irrelevant_ratio": round(irrelevant_ratio, 4),
        "negative_ok": negative_ok,
        "answerable": answerable,
    }


def observed_window_candidate(graph: Graph, task: Task, plan) -> DynamicCandidate:
    shape = profile_graph_shape(graph)
    first_nodes, first_edges = expand_directional(graph, list(task.starts), plan.hops, plan.node_budget, plan.direction)
    first_choice = choose_packet_for_subgraph(
        PacketChoice(plan.hops, plan.packet, "observed first pass"),
        compute_subgraph_stats(graph, first_nodes, first_edges),
        query_class=task.query_class,
    )
    first_tokens = estimate_tokens(render_packet(graph, first_nodes, first_edges, first_choice.packet))
    observed = recommend_observed_context_window(
        task.query_class,
        "",
        shape,
        observed_budget=plan.node_budget or len(first_nodes),
        observed_nodes=len(first_nodes),
        observed_tokens=first_tokens,
    )
    return DynamicCandidate(
        "observed_window",
        observed.recommended_budget,
        observed.reason,
        observed.target_tokens,
        observed.estimated_tokens,
        observed.saturation,
        observed.page_node_budget,
        observed.mode,
    )


def run() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for graph_path in sorted(REAL_GRAPHS.glob("*.json")):
        graph = load_any(graph_path)
        shape = profile_graph_shape(graph)
        for task in make_tasks(graph):
            for candidate in candidates_for(graph, task.query_class):
                row = score_candidate(graph, task, candidate)
                row.update({
                    "project": graph_path.stem,
                    "graph_nodes": shape.nodes,
                    "graph_edges": shape.edges,
                    "doc_node_ratio": shape.doc_node_ratio,
                    "weak_edge_ratio": shape.weak_edge_ratio,
                    "imports_per_source_file": shape.imports_per_source_file,
                })
                rows.append(row)
    return rows


def write(rows: list[dict[str, object]]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    fields = [
        "project",
        "query_class",
        "candidate",
        "max_nodes",
        "packet",
        "nodes",
        "edges",
        "tokens",
        "node_recall",
        "edge_recall",
        "irrelevant_ratio",
        "negative_ok",
        "answerable",
        "reason",
        "target_tokens",
        "estimated_tokens",
        "estimated_saturation",
        "actual_saturation",
        "page_node_budget",
        "window_mode",
        "graph_nodes",
        "graph_edges",
        "doc_node_ratio",
        "weak_edge_ratio",
        "imports_per_source_file",
    ]
    with RESULTS_CSV.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    SUMMARY_MD.write_text(render_markdown(rows), encoding="utf-8")


def render_markdown(rows: list[dict[str, object]]) -> str:
    lines = [
        "# Dynamic Budget Benchmark",
        "",
        "This benchmark tests graph-shape-recommended node budgets against the",
        "current default on saved real-project evidence-containment tasks.",
        "A smaller budget is promotable only if it preserves 100% answerability.",
        "",
        "## Summary",
        "",
        "| Candidate | Answerable | Avg tokens | Avg nodes | Irrelevant ratio |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for candidate in ("current_default", "shape_recommended", "context_window", "observed_window"):
        items = [row for row in rows if row["candidate"] == candidate]
        answerable = sum(1 for row in items if truthy(row["answerable"]))
        lines.append(
            f"| `{candidate}` | {answerable}/{len(items)} | {avg(items, 'tokens'):.1f} | "
            f"{avg(items, 'nodes'):.1f} | {avg(items, 'irrelevant_ratio'):.3f} |"
        )

    lines.extend([
        "",
        "## By Query Class",
        "",
        "| Query class | Candidate | Answerable | Avg tokens | Avg nodes | Irrelevant ratio |",
        "| --- | --- | ---: | ---: | ---: | ---: |",
    ])
    for query_class in QUERY_CLASSES:
        for candidate in ("current_default", "shape_recommended", "context_window", "observed_window"):
            items = [row for row in rows if row["query_class"] == query_class and row["candidate"] == candidate]
            answerable = sum(1 for row in items if truthy(row["answerable"]))
            lines.append(
                f"| {query_class} | `{candidate}` | {answerable}/{len(items)} | "
                f"{avg(items, 'tokens'):.1f} | {avg(items, 'nodes'):.1f} | {avg(items, 'irrelevant_ratio'):.3f} |"
            )

    failures = [row for row in rows if row["candidate"] == "shape_recommended" and not truthy(row["answerable"])]
    if failures:
        lines.extend([
            "",
            "## Shape Candidate Failures",
            "",
            "| Project | Query class | Budget | Node recall | Edge recall | Negative OK | Reason |",
            "| --- | --- | ---: | ---: | ---: | --- | --- |",
        ])
        for row in failures:
            lines.append(
                f"| {row['project']} | {row['query_class']} | {row['max_nodes']} | "
                f"{float(row['node_recall']):.3f} | {float(row['edge_recall']):.3f} | "
                f"{row['negative_ok']} | {row['reason']} |"
            )

    window = [row for row in rows if row["candidate"] in {"context_window", "observed_window"}]
    if window:
        lines.extend([
            "",
            "## Window Candidates",
            "",
            "| Candidate | Query class | Answerable | Avg target tokens | Avg actual tokens | Actual saturation | Estimated saturation | Avg page budget | Modes |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
        ])
        for candidate in ("context_window", "observed_window"):
            for query_class in QUERY_CLASSES:
                items = [row for row in window if row["candidate"] == candidate and row["query_class"] == query_class]
                answerable = sum(1 for row in items if truthy(row["answerable"]))
                modes = ", ".join(sorted({str(row["window_mode"]) for row in items if row.get("window_mode")}))
                lines.append(
                    f"| `{candidate}` | {query_class} | {answerable}/{len(items)} | {avg(items, 'target_tokens'):.1f} | "
                    f"{avg(items, 'tokens'):.1f} | {avg(items, 'actual_saturation'):.3f} | "
                    f"{avg(items, 'estimated_saturation'):.3f} | "
                    f"{avg(items, 'page_node_budget'):.1f} | {modes} |"
                )

    current = [row for row in rows if row["candidate"] == "current_default"]
    dynamic = [row for row in rows if row["candidate"] == "shape_recommended"]
    window = [row for row in rows if row["candidate"] == "context_window"]
    observed = [row for row in rows if row["candidate"] == "observed_window"]
    current_answerable = sum(1 for row in current if truthy(row["answerable"]))
    dynamic_answerable = sum(1 for row in dynamic if truthy(row["answerable"]))
    window_answerable = sum(1 for row in window if truthy(row["answerable"]))
    observed_answerable = sum(1 for row in observed if truthy(row["answerable"]))
    current_tokens = avg(current, "tokens")
    dynamic_tokens = avg(dynamic, "tokens")
    savings = (1.0 - dynamic_tokens / current_tokens) * 100.0 if current_tokens else 0.0
    promotable = dynamic and dynamic_answerable == len(dynamic) and dynamic_tokens <= current_tokens
    lines.extend([
        "",
        "## Read",
        "",
        f"- Shape candidate promotable: `{promotable}`",
        f"- Current answerability: `{current_answerable}/{len(current)}`",
        f"- Shape answerability: `{dynamic_answerable}/{len(dynamic)}`",
        f"- Context-window answerability: `{window_answerable}/{len(window)}`",
        f"- Context-window actual target saturation: `{avg(window, 'actual_saturation'):.3f}`",
        f"- Context-window estimated target saturation: `{avg(window, 'estimated_saturation'):.3f}`",
        f"- Observed-window answerability: `{observed_answerable}/{len(observed)}`",
        f"- Observed-window actual target saturation: `{avg(observed, 'actual_saturation'):.3f}`",
        f"- Observed-window estimated target saturation: `{avg(observed, 'estimated_saturation'):.3f}`",
        f"- Token savings if promoted: `{savings:.2f}%`",
        "- Window candidates are experimental and should not be promoted unless they preserve answerability and improve saturation/noise.",
        "- If answerability drops, the candidate is useful as a hypothesis but not a runtime default.",
        "",
        f"CSV: `{RESULTS_CSV.relative_to(ROOT)}`",
    ])
    return "\n".join(lines) + "\n"


def main() -> None:
    rows = run()
    if not rows:
        OUT.mkdir(parents=True, exist_ok=True)
        SUMMARY_MD.write_text("# Dynamic Budget Benchmark\n\nSkipped: no saved real-project graphs found.\n", encoding="utf-8")
        print(SUMMARY_MD.read_text(encoding="utf-8"))
        return
    write(rows)
    print(SUMMARY_MD.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
