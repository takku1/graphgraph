from __future__ import annotations

import re

# Words and standalone punctuation, the coarse unit a packet line is built from.
WORD_SPLIT = re.compile(r"\w+|[^\s\w]")
# Identifier seams a byte-pair tokenizer almost always breaks on. `retrieve_context`
# and `context.py:554` are several tokens each, never one.
PIECE_SPLIT = re.compile(r"[_./\\-]|(?<=[a-z0-9])(?=[A-Z])")

# Fitted by least squares against tiktoken `o200k_base` and `cl100k_base` over
# 108 rendered packets spanning nine formats and six selection sizes. See
# `benchmarks/context_graph/calibrate_token_proxy.py`, which re-derives both
# constants from the shipped functions below and reports drift. Do not hand-tune
# them: re-run the fit.
#
# Held-out model selection (fit on o200k, scored on the unseen cl100k):
#
#   piece + punct weights (this)  mean |err| 2.95%  max 12.60%  format spread  6.90%
#   step + single scale           mean |err| 3.48%  max 13.21%  format spread  8.51%
#   pieces+chars+punct            mean |err| 3.57%  max 15.79%  format spread  8.34%
#   pieces+chars                  mean |err| 4.22%  max 19.24%  format spread  9.91%
#   unconstrained length buckets                    max 61.96%  REJECTED: negative costs
#
# The bare word count this replaces scored mean |err| 26.50%, max 62.50%, and a
# 47.20% cross-format spread -- large enough to reorder which packet format
# looked cheapest and to score `gg` and `gg_lex` as identical when they differ
# by 5.6% in real tokens.
PIECE_TOKEN_SCALE = 1.2593
# Punctuation costs about an eighth of a word piece: byte-pair tokenizers merge
# runs like `@`, `:`, `/`, and `.` into their neighbours rather than emitting
# one token each.
PUNCTUATION_TOKEN_SCALE = 0.1626
_PIECE_FREE_CHARS = 2
_PIECE_CHARS_PER_TOKEN = 6


def _piece_lengths(text: str) -> tuple[list[int], int]:
    """Subword piece lengths a BPE tokenizer would emit, and punctuation count."""
    lengths: list[int] = []
    punctuation = 0
    for word in WORD_SPLIT.findall(text):
        if len(word) == 1 and not word.isalnum():
            punctuation += 1
            continue
        pieces = [piece for piece in PIECE_SPLIT.split(word) if piece]
        lengths.extend(len(piece) for piece in pieces or [word])
    return lengths, punctuation


def token_units(text: str) -> float:
    """Unrounded token cost, additive over newline-joined fragments.

    Neither splitter matches across a newline, so
    ``token_units(a + "\\n" + b) == token_units(a) + token_units(b)`` exactly.
    Callers that accumulate a packet line by line must sum this and round once
    at the end; summing :func:`estimate_tokens` per line accumulates a rounding
    error against the same packet rendered whole.
    """
    lengths, punctuation = _piece_lengths(text)
    units = sum(
        1 + max(0, length - _PIECE_FREE_CHARS) // _PIECE_CHARS_PER_TOKEN
        for length in lengths
    )
    return units * PIECE_TOKEN_SCALE + punctuation * PUNCTUATION_TOKEN_SCALE


def estimate_tokens(text: str) -> int:
    """Return GraphGraph's deterministic packet-token proxy.

    Calibrated against real byte-pair tokenizers rather than counting words. A
    word count charges one token for an identifier a tokenizer splits into a
    dozen, and it does so unevenly across packet formats -- so it cannot be used
    to compare formats, size a budget, or support a token-saving claim.

    Stays pure-Python and dependency-free: this runs inside the packet compile
    loop, where invoking a real tokenizer would be far too slow.

    **Calibrated for packets, and blind to whitespace.** Both splitters discard
    spaces, so indentation is free here while a real tokenizer charges for it:
    `--json --pretty` measures +26.7% in real tokens and +0.0% by this proxy.
    That is acceptable because packets are uniformly single-space separated and
    this number sizes packet budgets -- but it means the proxy cannot be used to
    judge a layout or pretty-printing decision. Adding a whitespace term was
    tried and rejected: every fit gave it a negative coefficient and worsened
    worst-case error, the same failure mode as the 13-parameter length model.
    """
    return round(token_units(text))
