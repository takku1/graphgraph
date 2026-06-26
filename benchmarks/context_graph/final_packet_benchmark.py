from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

from constraint_context_benchmark import POLICIES, render_policy, select_policies
from protocol_benchmark import OUT, ROOT, get_token_counter


SOURCE_RESULTS = OUT / "source_routes" / "source_route_results.csv"
RESULTS_CSV = OUT / "final_packets" / "final_packet_results.csv"
SUMMARY_MD = OUT / "final_packets" / "final_packet_summary.md"

ROUTE = "code_graph_direct"
MIN_NODE_RECALL = 0.95
MIN_EDGE_RECALL = 0.95
MAX_IRRELEVANT_CONTEXT = 0.85

TASK_CONTEXTS = {
    "direct_lookup": {
        "id": "direct_lookup",
        "paths": ["src/components/AuthStatus.tsx"],
        "tags": ["frontend", "design"],
    },
    "reverse_lookup": {
        "id": "reverse_lookup",
        "paths": ["server/auth/tokens.py"],
        "tags": ["auth", "security", "backend"],
    },
    "multi_hop_path": {
        "id": "multi_hop_path",
        "paths": ["routes/export.py"],
        "tags": ["api", "backend", "bugfix"],
    },
    "blast_radius": {
        "id": "blast_radius",
        "paths": ["server/auth/session.py"],
        "tags": ["auth", "security", "backend"],
    },
    "subsystem_summary": {
        "id": "subsystem_summary",
        "paths": ["benchmarks/context_graph/protocol_benchmark.py"],
        "tags": ["answering", "agent"],
    },
    "negative_query": {
        "id": "negative_query",
        "paths": ["benchmarks/context_graph/adaptive_policy_report.py"],
        "tags": ["answering", "agent"],
    },
}


def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        raise SystemExit(f"Missing required benchmark output: {path}")
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def avg(items: list[dict], key: str) -> float:
    return sum(float(item[key]) for item in items) / max(1, len(items))


def choose_graph_packets(rows: list[dict]) -> dict[str, dict]:
    grouped: dict[tuple[str, int, str], list[dict]] = defaultdict(list)
    for row in rows:
        if row["source_route"] != ROUTE:
            continue
        grouped[(row["query_class"], int(row["hops"]), row["packet_mode"])].append(row)

    choices = {}
    for query_class in TASK_CONTEXTS:
        candidates = []
        for (qc, hops, packet_mode), items in grouped.items():
            if qc != query_class:
                continue
            summary = {
                "query_class": qc,
                "hops": hops,
                "packet_mode": packet_mode,
                "graph_tokens": avg(items, "tokens"),
                "node_recall": avg(items, "node_recall"),
                "edge_recall": avg(items, "edge_recall"),
                "irrelevant_context_ratio": avg(items, "irrelevant_context_ratio"),
            }
            if (
                summary["node_recall"] >= MIN_NODE_RECALL
                and summary["edge_recall"] >= MIN_EDGE_RECALL
                and summary["irrelevant_context_ratio"] <= MAX_IRRELEVANT_CONTEXT
            ):
                candidates.append(summary)
        if query_class in {"direct_lookup", "reverse_lookup", "negative_query"}:
            one_hop = [item for item in candidates if item["hops"] == 1]
            if one_hop:
                candidates = one_hop
        if query_class in {"multi_hop_path", "blast_radius"}:
            candidates = [item for item in candidates if item["hops"] == 2]
        if candidates:
            choices[query_class] = sorted(candidates, key=lambda item: (item["graph_tokens"], item["hops"]))[0]
    return choices


def policy_packet(task: dict, strategy: str, count_tokens) -> tuple[int, int, str]:
    if strategy == "none":
        return 0, 0, ""
    if strategy == "global_all_compact":
        selected = POLICIES
    elif strategy == "scoped_compact":
        selected = select_policies(task, "scoped_compact")
    else:
        raise ValueError(f"unknown policy strategy {strategy}")
    text = "\n".join(render_policy(policy, compact=True) for policy in selected)
    return count_tokens(text), len(selected), " ".join(policy["id"] for policy in selected)


def run() -> list[dict]:
    tokenizer, count_tokens = get_token_counter()
    graph_choices = choose_graph_packets(read_csv(SOURCE_RESULTS))
    rows = []
    glue_tokens = count_tokens("CONSTRAINTS:\n\nGRAPH:\n")
    for query_class, task in TASK_CONTEXTS.items():
        graph = graph_choices.get(query_class)
        if not graph:
            continue
        for policy_strategy in ["none", "global_all_compact", "scoped_compact"]:
            policy_tokens, policy_count, policy_ids = policy_packet(task, policy_strategy, count_tokens)
            rows.append(
                {
                    "query_class": query_class,
                    "graph_hops": graph["hops"],
                    "graph_packet": graph["packet_mode"],
                    "policy_strategy": policy_strategy,
                    "tokenizer": tokenizer,
                    "graph_tokens": round(graph["graph_tokens"], 3),
                    "policy_tokens": policy_tokens,
                    "glue_tokens": glue_tokens if policy_tokens else 0,
                    "total_tokens": round(graph["graph_tokens"] + policy_tokens + (glue_tokens if policy_tokens else 0), 3),
                    "policy_count": policy_count,
                    "policy_ids": policy_ids,
                    "node_recall": round(graph["node_recall"], 4),
                    "edge_recall": round(graph["edge_recall"], 4),
                    "irrelevant_context_ratio": round(graph["irrelevant_context_ratio"], 4),
                }
            )
    return rows


def write(rows: list[dict]) -> None:
    RESULTS_CSV.parent.mkdir(parents=True, exist_ok=True)
    with RESULTS_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        grouped[row["policy_strategy"]].append(row)

    lines = [
        "# Final Packet Benchmark",
        "",
        f"Tokenizer: `{rows[0]['tokenizer']}`",
        "",
        "This estimates the final LLM-facing packet after composing the selected graph packet with optional constraint policies.",
        "",
        "| Policy strategy | Avg graph tokens | Avg policy tokens | Avg total tokens | Avg policies |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for strategy, items in sorted(grouped.items()):
        lines.append(
            f"| {strategy} | {avg(items, 'graph_tokens'):.1f} | {avg(items, 'policy_tokens'):.1f} | "
            f"{avg(items, 'total_tokens'):.1f} | {avg(items, 'policy_count'):.1f} |"
        )

    lines.extend(
        [
            "",
            "## Query Class Detail",
            "",
            "| Query class | Graph | Policies | Total tokens | Policy IDs |",
            "| --- | --- | --- | ---: | --- |",
        ]
    )
    for row in rows:
        if row["policy_strategy"] != "scoped_compact":
            continue
        lines.append(
            f"| {row['query_class']} | {row['graph_hops']}hop {row['graph_packet']} | "
            f"{row['policy_strategy']} | {row['total_tokens']:.1f} | {row['policy_ids']} |"
        )

    lines.extend(
        [
            "",
            "Read:",
            "",
            "- `none` is the graph-only floor.",
            "- `global_all_compact` shows the cost of always-on project standards.",
            "- `scoped_compact` is the target final packet: graph evidence plus only relevant policies.",
            "",
            f"CSV: `{RESULTS_CSV.relative_to(ROOT)}`",
        ]
    )
    SUMMARY_MD.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    rows = run()
    write(rows)
    print(SUMMARY_MD.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
