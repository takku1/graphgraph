"""Continuous evidence grounding for abstention.

Effective confidence is shape confidence times a noisy-OR of independent
channels. Exact identifier hits and caller-pinned seeds are proofs (1.0).
Paraphrase specificity and identity-over-query-length are continuous.
"""

from __future__ import annotations

import math

from .models import Match
from .text import tokenize

ABSTAIN_POLICY = 0.2
_CODE_ANCHOR_KINDS = frozenset({
    "function", "method", "class", "struct", "trait", "enum", "interface", "type",
})
_PATH_ANCHOR_KINDS = _CODE_ANCHOR_KINDS | frozenset({
    "package", "module", "file", "python",
})


def term_specificity(term: str) -> float:
    """How identifying a term is, in [0, 1].

    Hyphenated compounds are fully specific. Bare length uses ``tanh`` so
    ``packet`` (6) stays weak, ``settlement`` (10) is strong, and there is
    no cliff at a magic character count.
    """
    if not term:
        return 0.0
    if "-" in term:
        return 1.0
    return math.tanh(max(0.0, len(term) - 5) / 3.0)


def peaked_specificity(term: str) -> float:
    """Soft gate: only high-specificity terms contribute to paraphrase grounding.

    A logistic centered at 0.75 maps ``packet``/``context`` near 0 and
    ``settlement``/``instruction-set`` near 1, without a hard cutoff.
    """
    spec = term_specificity(term)
    return 1.0 / (1.0 + math.exp(-12.0 * (spec - 0.75)))


def noisy_or(channels: tuple[float, ...]) -> float:
    """Independent evidence channels: ``1 - Π(1 - g_i)``."""
    survival = 1.0
    for value in channels:
        clamped = 0.0 if value <= 0.0 else 1.0 if value >= 1.0 else value
        survival *= 1.0 - clamped
        if survival == 0.0:
            return 1.0
    return 1.0 - survival


def _summary_reason_term(reason: str) -> str:
    if not reason.startswith("summary:"):
        return ""
    return reason.split(":", 1)[1]


def _identity_term(reason: str) -> str:
    if reason.startswith(("id:", "label:", "label_exact:", "path:", "path_exact:")):
        return reason.split(":", 1)[1]
    if reason in {
        "basename_stem_exact",
        "label_exact_terms",
        "label_all_terms",
        "basename_exact_terms",
        "basename_all_terms",
    }:
        return reason
    return ""


def paraphrase_grounding(matches: tuple[Match, ...]) -> float:
    """Saturating peaked specificity of summary terms on code anchors."""
    best = 0.0
    for match in matches:
        if match.node.kind not in _CODE_ANCHOR_KINDS:
            continue
        spec = sum(peaked_specificity(_summary_reason_term(reason)) for reason in match.reasons)
        if spec <= 0.0:
            continue
        best = max(best, math.tanh(spec))
    return best


def identity_grounding(matches: tuple[Match, ...], query: str) -> float:
    """Identity-reason coverage on the strongest match, discounted by query length."""
    terms = tokenize(query) if query else ()
    hits = max(
        (sum(1 for reason in match.reasons if _identity_term(reason)) for match in matches),
        default=0,
    )
    if hits <= 0:
        return 0.0
    return math.tanh(hits / max(1, len(terms)))


def distinctive_corpus_grounding(matches: tuple[Match, ...], query: str) -> float:
    """Two query terms that are exact path segments of selected code nodes.

    Long how-does-X-flow questions dilute identity grounding below policy even
    when the selected nodes live in the directories the query named. Substring
    matches are rejected so ``packet`` does not hit ``packet_0.py``.
    """
    terms = [term for term in tokenize(query) if len(term) >= 6]
    if len(terms) < 2:
        return 0.0
    parts: set[str] = set()
    for match in matches:
        if match.node.kind not in _PATH_ANCHOR_KINDS or not match.node.path:
            continue
        for part in match.node.path.replace("\\", "/").split("/"):
            lowered = part.casefold()
            parts.add(lowered)
            parts.add(lowered.rsplit(".", 1)[0])
    hits = sum(1 for term in terms if term in parts)
    if hits < 2:
        return 0.0
    return math.tanh(hits / 2.0)


def packet_grounding(
    matches: tuple[Match, ...],
    query: str = "",
    *,
    exact: bool = False,
    injected: bool = False,
    pinned_paths: bool = False,
) -> float:
    """How grounded the selected anchors are, in [0, 1]."""
    if not matches:
        return 0.0
    return noisy_or((
        1.0 if exact or injected or pinned_paths else 0.0,
        paraphrase_grounding(matches),
        identity_grounding(matches, query),
        distinctive_corpus_grounding(matches, query),
    ))


def effective_confidence(shape_confidence: float, grounding: float) -> float:
    """Shape confidence damped by grounding."""
    if shape_confidence <= 0.0 or grounding <= 0.0:
        return 0.0
    return shape_confidence * grounding


