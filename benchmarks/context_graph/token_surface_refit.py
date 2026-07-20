"""Refit the packet token surfaces and validate by leave-one-project-out.

Each packet's planning proxy is a linear surface `intercept + node_cost*nodes +
edge_cost*edges` (token_cost.PACKET_TOKEN_SURFACE); `gg_max_hybrid` adds a
separate fact-token term at runtime, so its surface is fit on the residual
`actual - fact_token_proxy`. This script measures the current coefficients and
an ordinary-least-squares refit under leave-one-project-out (LOPO) cross-
validation, so the reported packet-winner agreement reflects generalisation to
unseen projects rather than in-sample overfit. It prints the all-data refit
coefficients to paste into token_cost.py only if they beat the current model.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from graphgraph.analysis.eval import estimate_tokens  # noqa: E402
from graphgraph.graph.core import Graph  # noqa: E402
from graphgraph.io import load_any  # noqa: E402
from graphgraph.packets import render_packet  # noqa: E402
from graphgraph.planning.shape import recommend_facts_per_node  # noqa: E402
from graphgraph.planning.token_cost import PACKET_TOKEN_SURFACE  # noqa: E402

# Import the data-collection scaffolding already used by the calibration bench.
try:
    from .token_proxy_calibration import HOPS, MAX_NODES, PACKETS, REAL_GRAPHS, make_starts
except ImportError:  # pragma: no cover - script entry
    from token_proxy_calibration import (  # type: ignore[no-redef]
        HOPS,
        MAX_NODES,
        PACKETS,
        REAL_GRAPHS,
        make_starts,
    )

OUT = ROOT / "benchmarks" / "context_graph" / "out" / "real_projects"
REPORT_MD = OUT / "token_surface_refit.md"


def _fact_token_proxy(graph: Graph, nodes: set[str]) -> int:
    """Replicates stats.compute_subgraph_stats' fact-token proxy for hybrid."""
    facts_per_node = recommend_facts_per_node(len(nodes))
    total = 0
    for node_id in nodes:
        node = graph.nodes.get(node_id)
        if not node:
            continue
        total += max(0, len(node.summary) // 4)
        total += sum(max(1, len(fact) // 4) for fact in node.facts[:facts_per_node])
    return total


def collect_cases() -> list[dict]:
    """One record per (project, start, hops) subgraph with per-packet actuals."""
    cases: list[dict] = []
    for graph_path in sorted(REAL_GRAPHS.glob("*.json")):
        graph = load_any(graph_path)
        for start in make_starts(graph):
            for hops in HOPS:
                nodes, edges = graph.expand(list(start.node_ids), hops=hops, max_nodes=MAX_NODES)
                fact_proxy = _fact_token_proxy(graph, nodes)
                actual = {p: estimate_tokens(render_packet(graph, nodes, edges, p)) for p in PACKETS}
                cases.append(
                    {
                        "project": graph_path.stem,
                        "nodes": len(nodes),
                        "edges": len(edges),
                        "fact_proxy": fact_proxy,
                        "actual": actual,
                    }
                )
    return cases


def _target(case: dict, packet: str) -> float:
    """Regression target: hybrid's runtime adds fact_proxy, so fit the residual."""
    value = float(case["actual"][packet])
    if packet == "gg_max_hybrid":
        value -= case["fact_proxy"]
    return value


def solve_ols(samples: list[tuple[float, float, float]]) -> tuple[float, float, float]:
    """OLS for y = b0 + b1*nodes + b2*edges via 3x3 normal equations."""
    xtx = [[0.0] * 3 for _ in range(3)]
    xty = [0.0] * 3
    for nodes, edges, y in samples:
        x = (1.0, nodes, edges)
        for i in range(3):
            xty[i] += x[i] * y
            for j in range(3):
                xtx[i][j] += x[i] * x[j]
    return tuple(_gaussian_solve(xtx, xty))  # type: ignore[return-value]


def _gaussian_solve(a: list[list[float]], b: list[float]) -> list[float]:
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(m[r][col]))
        if abs(m[pivot][col]) < 1e-12:
            return [b[0] / max(a[0][0], 1e-9), 0.0, 0.0]  # degenerate; fall back
        m[col], m[pivot] = m[pivot], m[col]
        pv = m[col][col]
        m[col] = [v / pv for v in m[col]]
        for r in range(n):
            if r != col and m[r][col]:
                factor = m[r][col]
                m[r] = [v - factor * mc for v, mc in zip(m[r], m[col])]
    return [m[i][n] for i in range(n)]


def fit_surface(cases: list[dict]) -> dict[str, tuple[float, float, float]]:
    return {
        packet: solve_ols([(float(c["nodes"]), float(c["edges"]), _target(c, packet)) for c in cases])
        for packet in PACKETS
    }


def predict(surface: dict, case: dict, packet: str) -> float:
    intercept, node_cost, edge_cost = surface[packet]
    value = intercept + node_cost * case["nodes"] + edge_cost * case["edges"]
    if packet == "gg_max_hybrid":
        value += case["fact_proxy"]
    return max(0.0, value)


def evaluate(surface: dict, cases: list[dict]) -> dict[str, float]:
    winner_hits = semantic_hits = 0
    zero_edge_hits = zero_edge_total = 0
    abs_err = 0.0
    for case in cases:
        actual = case["actual"]
        pred = {p: predict(surface, case, p) for p in PACKETS}
        actual_winner = min(PACKETS, key=lambda p: (actual[p], p))
        pred_winner = min(PACKETS, key=lambda p: (pred[p], p))
        winner_hits += actual_winner == pred_winner
        a_sem = actual["semantic_arrow"] <= actual["gg_max"]
        p_sem = pred["semantic_arrow"] <= pred["gg_max"]
        semantic_hits += a_sem == p_sem
        # The runtime only consults the semantic/gg decision at zero edges
        # (refine_packet_choice), so track that slice separately.
        if case["edges"] == 0:
            zero_edge_total += 1
            zero_edge_hits += a_sem == p_sem
        abs_err += sum(abs(pred[p] - actual[p]) for p in PACKETS) / len(PACKETS)
    n = max(1, len(cases))
    return {
        "winner_agreement": winner_hits / n,
        "semantic_agreement": semantic_hits / n,
        "zero_edge_semantic_agreement": zero_edge_hits / max(1, zero_edge_total),
        "mean_abs_error": abs_err / n,
    }


def lopo(cases: list[dict], use_refit: bool) -> dict[str, float]:
    """Leave-one-project-out evaluation of current vs refit coefficients."""
    projects = sorted({c["project"] for c in cases})
    agg = {
        "winner_agreement": 0.0,
        "semantic_agreement": 0.0,
        "zero_edge_semantic_agreement": 0.0,
        "mean_abs_error": 0.0,
    }
    total = 0
    for held in projects:
        train = [c for c in cases if c["project"] != held]
        test = [c for c in cases if c["project"] == held]
        surface = fit_surface(train) if use_refit else PACKET_TOKEN_SURFACE
        metrics = evaluate(surface, test)
        for key in agg:
            agg[key] += metrics[key] * len(test)
        total += len(test)
    return {key: value / max(1, total) for key, value in agg.items()}


def main() -> None:
    cases = collect_cases()
    if not cases:
        print("No real-project graphs found; run real_project_packet_balance.py first.")
        return

    current = lopo(cases, use_refit=False)
    refit = lopo(cases, use_refit=True)
    final_surface = fit_surface(cases)

    lines = [
        "# Token Surface Refit (leave-one-project-out)",
        "",
        f"Cases: `{len(cases)}` subgraphs across `{len({c['project'] for c in cases})}` projects.",
        "",
        "| Model | Winner agreement | semantic/gg (all) | semantic/gg (zero-edge) | Mean abs error |",
        "| --- | ---: | ---: | ---: | ---: |",
        f"| current | {current['winner_agreement']:.1%} | {current['semantic_agreement']:.1%} | {current['zero_edge_semantic_agreement']:.1%} | {current['mean_abs_error']:.1f} |",
        f"| OLS refit | {refit['winner_agreement']:.1%} | {refit['semantic_agreement']:.1%} | {refit['zero_edge_semantic_agreement']:.1%} | {refit['mean_abs_error']:.1f} |",
        "",
        "## All-data refit coefficients (intercept, node_cost, edge_cost)",
        "",
        "```python",
        "PACKET_TOKEN_SURFACE = {",
    ]
    for packet in PACKETS:
        a, b, c = final_surface[packet]
        lines.append(f'    "{packet}": ({a:.4f}, {b:.4f}, {c:.4f}),')
    lines.append("}")
    lines.append("```")
    report = "\n".join(lines)
    print(report)
    OUT.mkdir(parents=True, exist_ok=True)
    REPORT_MD.write_text(report + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
