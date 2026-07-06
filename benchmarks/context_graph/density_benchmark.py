"""density_benchmark.py — empirical format-efficiency comparison across real codebases.

Measures chars-per-element density, token cost, and recall for every graphgraph
packet format against a simulated graphify-verbose baseline.

Usage:
    uv run python benchmarks/context_graph/density_benchmark.py

Environment overrides:
    DENSITY_REBUILD=1    Force re-scan all repos (slow, default: uses cached graphs)
    DENSITY_LOCUS_MAX=1200  Max nodes for locus scan
    DENSITY_SELF_MAX=600    Max nodes for graphgraph self-scan
"""
from __future__ import annotations

import math
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[2]
BENCH = ROOT / "benchmarks" / "context_graph"
OUT = BENCH / "out" / "density"
DATA = BENCH / "data"

sys.path.insert(0, str(ROOT / "src"))

from graphgraph.io import load_any
from graphgraph.packets import (
    render_gg_max,
    render_packet,
    render_semantic_arrow,
    render_sql,
    render_tensor_array,
)
from graphgraph.retrieval import retrieve_context


# ── token counter ─────────────────────────────────────────────────────────────

def _make_token_counter() -> tuple[str, Callable[[str], int]]:
    try:
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        return "tiktoken:cl100k_base", lambda t: len(enc.encode(t))
    except Exception:
        return "approx:ceil(chars/4)", lambda t: max(1, math.ceil(len(t) / 4))


TOKENIZER_NAME, count_tokens = _make_token_counter()


# ── graphify-verbose simulator ────────────────────────────────────────────────

def render_graphify_verbose(graph, nodes: set[str], edges) -> str:
    """Simulate graphify's verbose NODE/EDGE format for baseline comparison.

    Format mirrors what graphify extract outputs:
        NODE Label [src=path loc=L1 community=scope]
        EDGE SourceLabel --type [PROVENANCE]--> TargetLabel
    """
    lines = []
    for nid in sorted(nodes):
        node = graph.nodes[nid]
        parts = [f"NODE {node.label}"]
        meta = []
        if node.path:
            meta.append(f"src={node.path}")
        meta.append("loc=L1")
        if node.scope:
            meta.append(f"community={node.scope}")
        if meta:
            parts.append(f"[{' '.join(meta)}]")
        lines.append(" ".join(parts))
    label = {nid: graph.nodes[nid].label for nid in graph.nodes}
    for edge in edges:
        src = label.get(edge.source, edge.source)
        tgt = label.get(edge.target, edge.target)
        prov = edge.provenance.upper() if edge.provenance else "EXTRACTED"
        lines.append(f"EDGE {src} --{edge.type} [{prov}]--> {tgt}")
    return "\n".join(lines)


# ── format registry ───────────────────────────────────────────────────────────

FORMATS: dict[str, Callable] = {
    "graphify_verbose": render_graphify_verbose,
    "gg_max":           lambda g, n, e: render_gg_max(g, n, e),
    "gg_max_hybrid":    lambda g, n, e: render_gg_max(g, n, e, hybrid=True),
    "semantic_arrow":   lambda g, n, e: render_semantic_arrow(g, n, e),
    "sql_rows":         lambda g, n, e: render_sql(g, n, e),
    "csr_arrays":       lambda g, n, e: render_tensor_array(g, n, e),
}


# ── measurement ──────────────────────────────────────────────────────────────

def measure(text: str, n_nodes: int, n_edges: int) -> dict:
    chars = len(text)
    tokens = count_tokens(text)
    total_elements = n_nodes + n_edges
    density = round(chars / total_elements, 2) if total_elements else 0.0
    return {"chars": chars, "tokens": tokens, "density_chars_per_elem": density}


def retrieve(graph, query: str, query_class: str, max_nodes: int = 40):
    t0 = time.perf_counter()
    result = retrieve_context(graph, query, query_class, hops=2, max_nodes=max_nodes)
    elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)
    return result, elapsed_ms


# ── repos ─────────────────────────────────────────────────────────────────────

def _run(cmd: list[str]) -> None:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")
    subprocess.run(cmd, cwd=ROOT, env=env, check=True)


def ensure_locus_graph(locus: Path) -> dict[str, Path]:
    out = OUT / "locus"
    out.mkdir(parents=True, exist_ok=True)
    native = out / "locus-native.json"
    graphify_import = out / "locus-graphify-import.json"

    locus_cached = BENCH / "out" / "locus" / "locus-native.json"
    if locus_cached.exists() and not _rebuild():
        return {"native": locus_cached, "graphify": BENCH / "out" / "locus" / "locus-graphify-import.json"}

    if _rebuild() or not native.exists():
        _run([
            sys.executable, "-m", "graphgraph", "scan",
            "--directory", str(locus),
            "--depth", "symbols",
            "--docs",
            "--max-nodes", os.environ.get("DENSITY_LOCUS_MAX", "1200"),
            "--skip-dirs", "graphify-out", ".code-review-graph", "target", "target_new",
                          "target_new2", "archive", "spikes", "test-inputs",
            "--output", str(native),
        ])

    source_graphify = locus / "graphify-out" / "graph.json"
    if source_graphify.exists() and (_rebuild() or not graphify_import.exists()):
        _run([
            sys.executable, "-m", "graphgraph", "ingest",
            "--input", str(source_graphify),
            "--output", str(graphify_import),
        ])

    return {"native": native, "graphify": graphify_import if graphify_import.exists() else None}


def ensure_self_graph() -> Path:
    out = OUT / "graphgraph"
    out.mkdir(parents=True, exist_ok=True)
    path = out / "graphgraph-native.json"
    if _rebuild() or not path.exists():
        _run([
            sys.executable, "-m", "graphgraph", "scan",
            "--directory", str(ROOT / "src"),
            "--depth", "symbols",
            "--docs",
            "--max-nodes", os.environ.get("DENSITY_SELF_MAX", "600"),
            "--output", str(path),
        ])
    return path


def _rebuild() -> bool:
    return os.environ.get("DENSITY_REBUILD", "0") == "1"


# ── query sets ────────────────────────────────────────────────────────────────

LOCUS_QUERIES = [
    ("compiler expression rules",                       "blast_radius"),
    ("what calls compile_rules_slice",                  "reverse_lookup"),
    ("differentiation synthesizer applier derivative",  "blast_radius"),
    ("symbolic expression visitor condition visitor",   "subsystem_summary"),
    ("ground rewrite recexpr pattern",                  "multi_hop_path"),
    ("matrix transpose orthogonal symmetric square",    "subsystem_summary"),
    ("rule registry coordinate profile",                "blast_radius"),
]

SELF_QUERIES = [
    ("scan_directory incremental",         "blast_radius"),
    ("render_packet gg_max format",        "multi_hop_path"),
    ("retrieve_context anchor limit",      "subsystem_summary"),
    ("search_nodes pagerank score",        "blast_radius"),
    ("TopologicalKVCache set get evict",   "subsystem_summary"),
    ("choose_packet planner query class",  "direct_lookup"),
]


# ── runner ────────────────────────────────────────────────────────────────────

def run_queries(
    graph,
    queries: list[tuple[str, str]],
    graph_label: str,
    max_nodes: int = 40,
) -> list[dict]:
    rows = []
    for query, query_class in queries:
        result, latency_ms = retrieve(graph, query, query_class, max_nodes=max_nodes)
        n_nodes = len(result.nodes)
        n_edges = len(result.edges)
        total_elements = n_nodes + n_edges

        if n_nodes == 0:
            continue

        format_rows: dict[str, dict] = {}
        for fmt_name, renderer in FORMATS.items():
            text = renderer(graph, result.nodes, result.edges)
            format_rows[fmt_name] = measure(text, n_nodes, n_edges)

        baseline = format_rows["graphify_verbose"]
        for fmt_name, metrics in format_rows.items():
            # positive = tokens saved vs baseline; negative = more tokens than baseline
            savings_pct = round(100 * (1 - metrics["tokens"] / baseline["tokens"])) if baseline["tokens"] else 0
            rows.append({
                "graph": graph_label,
                "query": query[:55],
                "query_class": query_class,
                "format": fmt_name,
                "nodes": n_nodes,
                "edges": n_edges,
                "elements": total_elements,
                "chars": metrics["chars"],
                "tokens": metrics["tokens"],
                "density": metrics["density_chars_per_elem"],
                "vs_baseline_savings_pct": savings_pct if fmt_name != "graphify_verbose" else 0,
                "retrieval_ms": latency_ms,
            })
    return rows


# ── report writers ────────────────────────────────────────────────────────────

def write_density_table(rows: list[dict], path: Path, title: str) -> None:
    lines = [f"# {title}", "", f"Tokenizer: `{TOKENIZER_NAME}`", ""]

    # Group by (graph, query, query_class) → show all formats as sub-rows
    from itertools import groupby
    key_fn = lambda r: (r["graph"], r["query"], r["query_class"])
    sorted_rows = sorted(rows, key=key_fn)
    grouped = groupby(sorted_rows, key=key_fn)

    lines.append("| Graph | Query | Class | Format | Nodes | Edges | Chars | Tokens | Density | vs. Baseline |")
    lines.append("| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |")

    for (graph_label, query, query_class), group in grouped:
        for row in group:
            fmt = row["format"]
            sp = row["vs_baseline_savings_pct"]
            savings = "(baseline)" if fmt == "graphify_verbose" else (f"{-sp:+.0f}%" if sp != 0 else "0%")
            lines.append(
                f"| {graph_label} | {query} | {query_class} | **{fmt}** | "
                f"{row['nodes']} | {row['edges']} | {row['chars']:,} | {row['tokens']:,} | "
                f"{row['density']} | {savings} |"
            )
        lines.append("|  |  |  |  |  |  |  |  |  |  |")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_summary_table(rows: list[dict], path: Path) -> None:
    """Aggregate mean metrics per (graph, format) — the headline comparison."""
    from collections import defaultdict
    buckets: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in rows:
        buckets[(row["graph"], row["format"])].append(row)

    lines = [
        "# Density Benchmark - Headline Summary",
        "",
        f"Tokenizer: `{TOKENIZER_NAME}`  |  Max 40 nodes per query",
        "",
        "Mean metrics across all queries per (graph, format).",
        "Lower density = more structure per token. Savings vs. baseline: negative = fewer tokens (better).",
        "",
        "| Graph | Format | Queries | Mean Nodes | Mean Edges | Mean Tokens | Mean Density | vs. Baseline |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]

    def mean(vals: list) -> float:
        return round(sum(vals) / len(vals), 1) if vals else 0.0

    sorted_keys = sorted(buckets.keys(), key=lambda k: (k[0], k[1] != "graphify_verbose", k[1]))
    for key in sorted_keys:
        graph_label, fmt = key
        bucket_rows = buckets[key]
        n_q = len(set(r["query"] for r in bucket_rows))
        mean_nodes = mean([r["nodes"] for r in bucket_rows])
        mean_edges = mean([r["edges"] for r in bucket_rows])
        mean_tokens = mean([r["tokens"] for r in bucket_rows])
        mean_density = mean([r["density"] for r in bucket_rows])
        if fmt == "graphify_verbose":
            savings_str = "(baseline)"
        else:
            raw = mean([r["vs_baseline_savings_pct"] for r in bucket_rows])
            savings_str = f"{-raw:+.0f}%" if raw != 0 else "0%"
        lines.append(
            f"| {graph_label} | **{fmt}** | {n_q} | {mean_nodes} | {mean_edges} | "
            f"{mean_tokens:.0f} | {mean_density} | {savings_str} |"
        )

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_element_efficiency_table(rows: list[dict], path: Path) -> None:
    """Show elements-per-token for each format — the inverse of density.

    Higher is better: more graph structure per token.
    """
    from collections import defaultdict
    buckets: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in rows:
        buckets[(row["graph"], row["format"])].append(row)

    lines = [
        "# Element Efficiency - Graph Structure per Token",
        "",
        "Higher = more graph structure delivered per token. Computed as (nodes+edges)/tokens.",
        "",
        "| Graph | Format | Mean Elements/Token | Relative to Baseline |",
        "| --- | --- | ---: | ---: |",
    ]

    baselines: dict[str, float] = {}
    eff: dict[tuple[str, str], float] = {}
    for (graph_label, fmt), bucket_rows in buckets.items():
        vals = [r["elements"] / r["tokens"] for r in bucket_rows if r["tokens"] > 0]
        e = round(sum(vals) / len(vals), 3) if vals else 0.0
        eff[(graph_label, fmt)] = e
        if fmt == "graphify_verbose":
            baselines[graph_label] = e

    sorted_keys = sorted(eff.keys(), key=lambda k: (k[0], k[1] != "graphify_verbose", -eff[k]))
    for (graph_label, fmt) in sorted_keys:
        e = eff[(graph_label, fmt)]
        base = baselines.get(graph_label, 1.0) or 1.0
        relative = f"{e / base:.1f}x" if fmt != "graphify_verbose" else "(baseline)"
        lines.append(f"| {graph_label} | **{fmt}** | {e} | {relative} |")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    all_rows: list[dict] = []

    # ── locus (Rust codebase) ─────────────────────────────────────────────────
    default_projects_root = Path(os.environ.get("AIPROJECTS_ROOT", Path.home() / "aiprojects"))
    locus_root = Path(os.environ.get("LOCUS_REPO", default_projects_root / "locus"))
    if locus_root.exists():
        print(f"[locus] loading graphs from {locus_root}...")
        graphs = ensure_locus_graph(locus_root)
        for label, gpath in graphs.items():
            if gpath and gpath.exists():
                graph = load_any(gpath)
                print(f"  [{label}] {len(graph.nodes):,} nodes, {len(graph.edges):,} edges")
                rows = run_queries(graph, LOCUS_QUERIES, f"locus/{label}")
                all_rows.extend(rows)
                print(f"  [{label}] {len(rows)} format×query measurements")
    else:
        print(f"[locus] not found at {locus_root}, skipping")

    # ── graphgraph self-benchmark ─────────────────────────────────────────────
    print(f"\n[graphgraph] scanning self ({ROOT / 'src'})...")
    self_path = ensure_self_graph()
    self_graph = load_any(self_path)
    print(f"  {len(self_graph.nodes):,} nodes, {len(self_graph.edges):,} edges")
    self_rows = run_queries(self_graph, SELF_QUERIES, "graphgraph/self")
    all_rows.extend(self_rows)
    print(f"  {len(self_rows)} format×query measurements")

    # ── contextminer (Python codebase) ───────────────────────────────────────
    cm_root = Path(os.environ.get("CM_REPO", default_projects_root / "contextminer"))
    if cm_root.exists():
        cm_out = OUT / "contextminer"
        cm_out.mkdir(parents=True, exist_ok=True)
        cm_graph_path = cm_out / "contextminer-native.json"
        if _rebuild() or not cm_graph_path.exists():
            print(f"\n[contextminer] scanning {cm_root}...")
            _run([
                sys.executable, "-m", "graphgraph", "scan",
                "--directory", str(cm_root),
                "--depth", "symbols",
                "--docs",
                "--max-nodes", "600",
                "--output", str(cm_graph_path),
            ])
        cm_graph = load_any(cm_graph_path)
        print(f"\n[contextminer] {len(cm_graph.nodes):,} nodes, {len(cm_graph.edges):,} edges")
        cm_queries = [
            ("search contexts artifacts",           "blast_radius"),
            ("runtime status refresh artifacts",    "subsystem_summary"),
            ("concept instruction distiller",       "multi_hop_path"),
        ]
        cm_rows = run_queries(cm_graph, cm_queries, "contextminer/self")
        all_rows.extend(cm_rows)
        print(f"  {len(cm_rows)} format×query measurements")
    else:
        print(f"\n[contextminer] not found at {cm_root}, skipping")

    if not all_rows:
        print("No measurements collected — exiting.")
        return

    # ── write outputs ─────────────────────────────────────────────────────────
    detail_path = OUT / "density_detail.md"
    summary_path = OUT / "density_summary.md"
    efficiency_path = OUT / "element_efficiency.md"

    write_density_table(all_rows, detail_path, "Density Benchmark — Per-Query Detail")
    write_summary_table(all_rows, summary_path)
    write_element_efficiency_table(all_rows, efficiency_path)

    print("\n" + "=" * 70)
    print(summary_path.read_text(encoding="utf-8"))
    print("=" * 70)
    print(efficiency_path.read_text(encoding="utf-8"))
    print(f"\nFull detail: {detail_path}")


if __name__ == "__main__":
    main()
