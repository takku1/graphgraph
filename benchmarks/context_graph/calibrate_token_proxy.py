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


def _features(text: str) -> tuple[float, float]:
    """The two shipped features, so the fit can never drift from the estimator."""
    lengths, punctuation = _piece_lengths(text)
    units = sum(
        1 + max(0, length - _PIECE_FREE_CHARS) // _PIECE_CHARS_PER_TOKEN
        for length in lengths
    )
    return float(units), float(punctuation)


def main() -> None:
    try:
        import tiktoken
    except ImportError:
        print("SKIP: tiktoken is not installed (dev-only dependency)")
        return
    graph_path = ROOT / ".graphgraph" / "graph.gg"
    if not graph_path.exists():
        print("SKIP: no graph; run `graphgraph scan --depth symbols --docs`")
        return

    graph = load_graph_binary(graph_path)
    active = [n for n, node in graph.nodes.items() if node.active]
    samples: list[tuple[str, str, int]] = []
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
                samples.append((packet_format, packet, len(encoder.encode(packet))))

    import numpy as np

    matrix = np.array([_features(p) for _, p, _ in samples], dtype=float)
    target = np.array([real for _, _, real in samples], dtype=float)
    piece_scale, punctuation_scale = np.linalg.lstsq(matrix, target, rcond=None)[0]

    errors = [(estimate_tokens(p) - real) / real for _, p, real in samples]
    by_format: dict[str, list[float]] = {}
    for (fmt, _, _), err in zip(samples, errors):
        by_format.setdefault(fmt, []).append(err)
    means = {f: sum(v) / len(v) for f, v in by_format.items()}

    print(f"samples            : {len(samples)} packets x {len(ENCODINGS)} encodings")
    print(f"fitted piece scale : {piece_scale:.4f}   (shipped: {PIECE_TOKEN_SCALE})")
    print(f"fitted punct scale : {punctuation_scale:.4f}   (shipped: {PUNCTUATION_TOKEN_SCALE})")
    print(f"mean error         : {sum(errors) / len(errors):+.2%}")
    print(f"mean |error|       : {sum(abs(e) for e in errors) / len(errors):.2%}")
    print(f"max  |error|       : {max(abs(e) for e in errors):.2%}")
    print(f"cross-format spread: {max(means.values()) - min(means.values()):.2%}")
    print()
    for fmt in FORMATS:
        print(f"  {fmt:16} {means[fmt]:+7.2%}")
    if abs(piece_scale - PIECE_TOKEN_SCALE) > 0.02 or abs(
        punctuation_scale - PUNCTUATION_TOKEN_SCALE
    ) > 0.02:
        print()
        print("DRIFT: update packets/metrics.py to")
        print(f"    PIECE_TOKEN_SCALE = {piece_scale:.4f}")
        print(f"    PUNCTUATION_TOKEN_SCALE = {punctuation_scale:.4f}")


if __name__ == "__main__":
    main()
