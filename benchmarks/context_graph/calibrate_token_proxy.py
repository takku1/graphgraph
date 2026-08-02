"""Fit the packet token proxy against real BPE tokenizers.

`estimate_tokens` is the unit every budget, packet-format choice, and
token-saving claim in this project is denominated in. It was a bare
`\\w+|[^\\s\\w]` word count, which charges one token for
`src_graphgraph_retrieval_context_py__retrieve_context` where a real tokenizer
charges eleven. That under-count is format-dependent, so it did not merely
shift every number by a constant -- it reordered which packet format looked
cheapest and was blind to the `gg` versus `gg_lex` difference entirely.

This script re-derives the calibration. It is the source of the constants in
`graphgraph.packets.metrics`; run it after changing a renderer and paste the
reported values back. Requires `tiktoken`, which is a dev-only dependency --
the shipped estimator stays pure-Python and allocation-free.

Model selection was done on a held-out tokenizer (fit on o200k, scored on the
unseen cl100k). A two-parameter form -- a step cost per identifier piece plus a
much cheaper cost per punctuation mark -- beat 1-, 2-, 3-, and 13-parameter
alternatives on mean error, worst-case error, and cross-format spread. The
13-parameter unconstrained per-length fit was rejected outright for producing
negative token costs.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from graphgraph.packets import render_packet  # noqa: E402
from graphgraph.packets.metrics import (  # noqa: E402
    _PIECE_CHARS_PER_TOKEN,
    _PIECE_FREE_CHARS,
    PIECE_TOKEN_SCALE,
    PUNCTUATION_TOKEN_SCALE,
    _piece_lengths,
    estimate_tokens,
)
from graphgraph.storage import load_graph_binary  # noqa: E402

ENCODINGS = ("o200k_base", "cl100k_base")
FORMATS = (
    "gg",
    "gg_lex",
    "gg_hybrid",
    "gg_lex_hybrid",
    "lowlevel",
    "sql",
    "semantic_arrow",
    "doc_summary",
    "svo",
)
SIZES = (20, 60, 120, 250, 400, 800)
MAE_GATE = 0.05
P95_GATE = 0.10
FORMAT_SPREAD_GATE = 0.10


def _features(text: str) -> tuple[float, float]:
    """The two shipped features, so the fit can never drift from the estimator."""
    lengths, punctuation = _piece_lengths(text)
    units = sum(
        1 + max(0, length - _PIECE_FREE_CHARS) // _PIECE_CHARS_PER_TOKEN
        for length in lengths
    )
    return float(units), float(punctuation)


def _percentile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[max(0, math.ceil(quantile * len(ordered)) - 1)]


def _diagnostic_strata(graph: object) -> dict[str, str]:
    compact_negative = {
        "status": "unanswerable",
        "confidence": 0.0,
        "nodes": [],
        "edges": [],
        "required_next_action": "none",
    }
    active_nodes = getattr(graph, "nodes")
    active_edges = getattr(graph, "edges")
    identifier_ids = set(
        sorted(
            (node_id for node_id, node in active_nodes.items() if node.active),
            key=lambda node_id: (-len(node_id), node_id),
        )[:20]
    )
    identifier_edges = [
        edge
        for edge in active_edges
        if edge.active and edge.source in identifier_ids and edge.target in identifier_ids
    ]
    return {
        "negative_compact_json": json.dumps(compact_negative, separators=(",", ":")),
        "negative_pretty_json": json.dumps(compact_negative, indent=2),
        "identifier_heavy_gg": render_packet(
            graph,
            identifier_ids,
            identifier_edges,
            "gg",
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graph", type=Path, default=ROOT / ".graphgraph" / "graph.gg")
    parser.add_argument(
        "--enforce",
        action="store_true",
        help="Exit nonzero when MAE, p95, cross-format spread, or format-minimum gates fail.",
    )
    args = parser.parse_args(argv)
    try:
        import tiktoken
    except ImportError:
        print("SKIP: tiktoken is not installed (dev-only dependency)")
        return 0
    graph_path = args.graph
    if not graph_path.exists():
        print("SKIP: no graph; run `graphgraph scan --depth symbols --docs`")
        return 0

    graph = load_graph_binary(graph_path)
    active = [n for n, node in graph.nodes.items() if node.active]
    samples: list[tuple[str, int, str, str, int]] = []
    for encoding_name in ENCODINGS:
        encoder = tiktoken.get_encoding(encoding_name)
        for size in SIZES:
            random.seed(size)
            selected = set(random.sample(active, min(size, len(active))))
            edges = [
                e
                for e in graph.edges
                if e.active and e.source in selected and e.target in selected
            ]
            for packet_format in FORMATS:
                packet = render_packet(graph, selected, edges, packet_format)
                samples.append(
                    (encoding_name, size, packet_format, packet, len(encoder.encode(packet)))
                )

    import numpy as np

    matrix = np.array([_features(packet) for _, _, _, packet, _ in samples], dtype=float)
    target = np.array([real for _, _, _, _, real in samples], dtype=float)
    piece_scale, punctuation_scale = np.linalg.lstsq(matrix, target, rcond=None)[0]

    errors = [
        (estimate_tokens(packet) - real) / real
        for _, _, _, packet, real in samples
        if real
    ]
    absolute_errors = [abs(error) for error in errors]
    by_format: dict[str, list[float]] = {}
    by_encoding: dict[str, list[float]] = {}
    for (encoding, _size, fmt, _packet, _real), err in zip(samples, errors):
        by_format.setdefault(fmt, []).append(err)
        by_encoding.setdefault(encoding, []).append(err)
    means = {f: sum(v) / len(v) for f, v in by_format.items()}

    format_inversions: list[tuple[str, int, tuple[str, ...], tuple[str, ...]]] = []
    for encoding_name in ENCODINGS:
        for size in SIZES:
            group = [
                (fmt, estimate_tokens(packet), real)
                for encoding, sample_size, fmt, packet, real in samples
                if encoding == encoding_name and sample_size == size
            ]
            proxy_floor = min(proxy for _fmt, proxy, _real in group)
            real_floor = min(real for _fmt, _proxy, real in group)
            proxy_minima = tuple(sorted(fmt for fmt, proxy, _real in group if proxy == proxy_floor))
            real_minima = tuple(sorted(fmt for fmt, _proxy, real in group if real == real_floor))
            if not set(proxy_minima) & set(real_minima):
                format_inversions.append((encoding_name, size, proxy_minima, real_minima))

    mean_absolute_error = sum(absolute_errors) / len(absolute_errors)
    p95_absolute_error = _percentile(absolute_errors, 0.95)
    cross_format_spread = max(means.values()) - min(means.values())

    print(f"samples            : {len(samples)} rendered packet/tokenizer pairs")
    print(f"fitted piece scale : {piece_scale:.4f}   (shipped: {PIECE_TOKEN_SCALE})")
    print(f"fitted punct scale : {punctuation_scale:.4f}   (shipped: {PUNCTUATION_TOKEN_SCALE})")
    print(f"mean error         : {sum(errors) / len(errors):+.2%}")
    print(f"mean |error|       : {mean_absolute_error:.2%}")
    print(f"p95  |error|       : {p95_absolute_error:.2%}")
    print(f"max  |error|       : {max(absolute_errors):.2%}")
    print(f"cross-format spread: {cross_format_spread:.2%}")
    print(f"format inversions  : {len(format_inversions)} / {len(ENCODINGS) * len(SIZES)}")
    print()
    for encoding_name in ENCODINGS:
        encoding_errors = by_encoding[encoding_name]
        print(
            f"  {encoding_name:16} MAE={sum(abs(e) for e in encoding_errors) / len(encoding_errors):6.2%} "
            f"p95={_percentile([abs(e) for e in encoding_errors], 0.95):6.2%} "
            f"max={max(abs(e) for e in encoding_errors):6.2%}"
        )
    print()
    for fmt in FORMATS:
        print(f"  {fmt:16} {means[fmt]:+7.2%}")
    print()
    print("diagnostic strata (reported separately; pretty JSON is outside packet calibration):")
    for stratum, payload in _diagnostic_strata(graph).items():
        details = []
        proxy = estimate_tokens(payload)
        for encoding_name in ENCODINGS:
            real = len(tiktoken.get_encoding(encoding_name).encode(payload))
            error = (proxy - real) / real if real else 0.0
            details.append(f"{encoding_name}={real} ({error:+.2%})")
        print(f"  {stratum:24} proxy={proxy}  " + "  ".join(details))
    if format_inversions:
        print()
        for encoding_name, size, proxy_minima, real_minima in format_inversions:
            print(
                f"INVERSION: {encoding_name} size={size} "
                f"proxy={','.join(proxy_minima)} real={','.join(real_minima)}"
            )
    if abs(piece_scale - PIECE_TOKEN_SCALE) > 0.02 or abs(
        punctuation_scale - PUNCTUATION_TOKEN_SCALE
    ) > 0.02:
        print()
        print("DRIFT: update packets/metrics.py to")
        print(f"    PIECE_TOKEN_SCALE = {piece_scale:.4f}")
        print(f"    PUNCTUATION_TOKEN_SCALE = {punctuation_scale:.4f}")
    passed = (
        mean_absolute_error <= MAE_GATE
        and p95_absolute_error <= P95_GATE
        and cross_format_spread <= FORMAT_SPREAD_GATE
        and not format_inversions
    )
    print()
    print(f"gate                : {'PASS' if passed else 'FAIL'}")
    return 0 if passed or not args.enforce else 1


if __name__ == "__main__":
    raise SystemExit(main())
