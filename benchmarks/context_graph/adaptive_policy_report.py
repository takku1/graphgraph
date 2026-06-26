from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

from protocol_benchmark import OUT, ROOT


SOURCE_RESULTS = OUT / "source_routes" / "source_route_results.csv"
CONSTRAINT_RESULTS = OUT / "constraints" / "constraint_context_results.csv"
PROMPT_PREFLIGHT = OUT / "prompt_preflight.csv"
REPORT_MD = OUT / "adaptive_policy_report.md"

MIN_EXTRACT_EDGE_RECALL = 0.95
MIN_EXTRACT_EDGE_PRECISION = 0.99
MIN_PACKET_NODE_RECALL = 0.95
MIN_PACKET_EDGE_RECALL = 0.95
MAX_IRRELEVANT_CONTEXT = 0.85
MIN_POLICY_RECALL = 1.0
MAX_POLICY_IRRELEVANT = 0.0


def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        raise SystemExit(f"Missing required benchmark output: {path}")
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def avg(items: list[dict], key: str) -> float:
    return sum(float(item[key]) for item in items) / max(1, len(items))


def summarize_source_routes(rows: list[dict]) -> list[dict]:
    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in rows:
        grouped[(row["source_route"], row["corpus"])].append(row)

    per_route: dict[str, list[dict]] = defaultdict(list)
    seen = set()
    for (route, corpus), items in grouped.items():
        sample = items[0]
        key = (route, corpus)
        if key in seen:
            continue
        seen.add(key)
        per_route[route].append(sample)

    summary = []
    for route, items in sorted(per_route.items()):
        summary.append(
            {
                "source_route": route,
                "extract_node_recall": avg(items, "extract_node_recall"),
                "extract_edge_recall": avg(items, "extract_edge_recall"),
                "extract_edge_precision": avg(items, "extract_edge_precision"),
                "extract_extra_edges": avg(items, "extract_extra_edges"),
            }
        )
    return summary


def summarize_packets(rows: list[dict]) -> list[dict]:
    grouped: dict[tuple[str, str, int, str], list[dict]] = defaultdict(list)
    for row in rows:
        grouped[(row["source_route"], row["query_class"], int(row["hops"]), row["packet_mode"])].append(row)

    summary = []
    for (route, query_class, hops, packet), items in sorted(grouped.items()):
        summary.append(
            {
                "source_route": route,
                "query_class": query_class,
                "hops": hops,
                "packet_mode": packet,
                "tokens": avg(items, "tokens"),
                "node_recall": avg(items, "node_recall"),
                "edge_recall": avg(items, "edge_recall"),
                "path_recall": avg(items, "path_recall"),
                "irrelevant_context_ratio": avg(items, "irrelevant_context_ratio"),
            }
        )
    return summary


def summarize_constraints(rows: list[dict]) -> list[dict]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        grouped[row["strategy"]].append(row)
    return [
        {
            "strategy": strategy,
            "tokens": avg(items, "tokens"),
            "policy_recall": avg(items, "policy_recall"),
            "irrelevant_policy_ratio": avg(items, "irrelevant_policy_ratio"),
            "selected_policy_count": avg(items, "selected_policy_count"),
        }
        for strategy, items in sorted(grouped.items())
    ]


def summarize_prompt_preflight(rows: list[dict]) -> list[dict]:
    grouped: dict[tuple[str, int], list[dict]] = defaultdict(list)
    for row in rows:
        grouped[(row["variant"], int(row["hops"]))].append(row)
    return [
        {
            "variant": variant,
            "hops": hops,
            "prompt_tokens": avg(items, "prompt_tokens"),
            "prompt_count": len(items),
        }
        for (variant, hops), items in sorted(grouped.items())
    ]


def choose_routes(source_summary: list[dict]) -> tuple[list[dict], list[dict]]:
    passing = [
        row
        for row in source_summary
        if row["extract_edge_recall"] >= MIN_EXTRACT_EDGE_RECALL
        and row["extract_edge_precision"] >= MIN_EXTRACT_EDGE_PRECISION
    ]
    failing = [row for row in source_summary if row not in passing]
    return passing, failing


def choose_packet(packet_summary: list[dict], route: str, query_class: str) -> dict | None:
    candidates = [
        row
        for row in packet_summary
        if row["source_route"] == route
        and row["query_class"] == query_class
        and row["node_recall"] >= MIN_PACKET_NODE_RECALL
        and row["edge_recall"] >= MIN_PACKET_EDGE_RECALL
        and row["irrelevant_context_ratio"] <= MAX_IRRELEVANT_CONTEXT
    ]
    if query_class in {"multi_hop_path", "blast_radius"}:
        candidates = [row for row in candidates if row["hops"] == 2]
    if query_class in {"direct_lookup", "reverse_lookup", "negative_query"}:
        direct = [row for row in candidates if row["hops"] == 1]
        if direct:
            candidates = direct
    if not candidates:
        return None
    return sorted(candidates, key=lambda row: (row["tokens"], row["hops"], row["packet_mode"]))[0]


def choose_constraint(constraint_summary: list[dict]) -> dict | None:
    candidates = [
        row
        for row in constraint_summary
        if row["policy_recall"] >= MIN_POLICY_RECALL
        and row["irrelevant_policy_ratio"] <= MAX_POLICY_IRRELEVANT
    ]
    if not candidates:
        return None
    return sorted(candidates, key=lambda row: row["tokens"])[0]


def fmt(value: float) -> str:
    return f"{value:.3f}"


def write_report() -> None:
    source_rows = read_csv(SOURCE_RESULTS)
    constraint_rows = read_csv(CONSTRAINT_RESULTS)
    prompt_rows = read_csv(PROMPT_PREFLIGHT)

    source_summary = summarize_source_routes(source_rows)
    packet_summary = summarize_packets(source_rows)
    constraint_summary = summarize_constraints(constraint_rows)
    prompt_summary = summarize_prompt_preflight(prompt_rows)
    passing_routes, failing_routes = choose_routes(source_summary)
    default_route = next((row for row in passing_routes if row["source_route"] == "code_graph_direct"), passing_routes[0] if passing_routes else None)
    constraint_choice = choose_constraint(constraint_summary)

    lines = [
        "# Adaptive Policy Report",
        "",
        "This converts benchmark outputs into a measured routing policy. It is still a hypothesis until live model-answer scoring passes.",
        "",
        "## Source Route Gate",
        "",
        f"Pass gate: edge recall >= `{MIN_EXTRACT_EDGE_RECALL}`, edge precision >= `{MIN_EXTRACT_EDGE_PRECISION}`.",
        "",
        "| Source route | Edge recall | Edge precision | Status |",
        "| --- | ---: | ---: | --- |",
    ]
    for row in source_summary:
        status = "PASS" if row in passing_routes else "FAIL"
        lines.append(
            f"| {row['source_route']} | {fmt(row['extract_edge_recall'])} | "
            f"{fmt(row['extract_edge_precision'])} | {status} |"
        )

    lines.extend(["", "## Packet Choices", ""])
    if default_route:
        route = default_route["source_route"]
        query_classes = [
            "direct_lookup",
            "reverse_lookup",
            "multi_hop_path",
            "blast_radius",
            "subsystem_summary",
            "negative_query",
        ]
        lines.extend(
            [
                f"Default trusted route: `{route}`.",
                "",
                "| Query class | Hops | Packet | Avg tokens | Node recall | Edge recall | Irrelevant ratio |",
                "| --- | ---: | --- | ---: | ---: | ---: | ---: |",
            ]
        )
        for query_class in query_classes:
            choice = choose_packet(packet_summary, route, query_class)
            if not choice:
                lines.append(f"| {query_class} | - | fallback_required | - | - | - | - |")
                continue
            lines.append(
                f"| {query_class} | {choice['hops']} | {choice['packet_mode']} | {choice['tokens']:.1f} | "
                f"{choice['node_recall']:.3f} | {choice['edge_recall']:.3f} | "
                f"{choice['irrelevant_context_ratio']:.3f} |"
            )
    else:
        lines.append("No source route passed extraction gates.")

    lines.extend(["", "## Constraint Context Choice", ""])
    if constraint_choice:
        lines.append(
            f"Use `{constraint_choice['strategy']}`: avg `{constraint_choice['tokens']:.1f}` tokens, "
            f"policy recall `{constraint_choice['policy_recall']:.3f}`, irrelevant ratio "
            f"`{constraint_choice['irrelevant_policy_ratio']:.3f}`."
        )
    else:
        lines.append("No constraint strategy passed policy recall/irrelevance gates.")

    lines.extend(
        [
            "",
            "## Live Prompt Footprint",
            "",
            "| Variant | Hops | Avg prompt tokens | Prompt count |",
            "| --- | ---: | ---: | ---: |",
        ]
    )
    for row in prompt_summary:
        lines.append(f"| {row['variant']} | {row['hops']} | {row['prompt_tokens']:.1f} | {row['prompt_count']} |")

    lines.extend(
        [
            "",
            "## Operational Policy",
            "",
            "1. Use a source route only if extraction edge precision and recall pass the gate.",
            "2. Choose hop depth per query class; do not force all tasks to share the same context radius.",
            "3. For path, blast-radius, and high-risk changes, prefer the cheapest 2-hop passing low-level packet.",
            "4. If live model-answer scoring fails for low-level packets, fall back to SQL rows before hybrid snippets.",
            "5. Add scoped compact constraint policies when path/task tags match; avoid global policy dumps.",
            "6. Use hybrid snippets only when the answer needs source-grounded prose, citations, or semantics beyond topology.",
        ]
    )
    if failing_routes:
        lines.extend(["", "## Failing / Limited Routes", ""])
        for row in failing_routes:
            lines.append(
                f"- `{row['source_route']}`: edge recall `{fmt(row['extract_edge_recall'])}`, "
                f"precision `{fmt(row['extract_edge_precision'])}`."
            )

    REPORT_MD.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    write_report()
    print(REPORT_MD.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
