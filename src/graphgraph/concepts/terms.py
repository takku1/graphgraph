from __future__ import annotations

import re
from functools import lru_cache

_SPACE = re.compile(r"\s+")
_PUNCT = re.compile(r"[^A-Za-z0-9_]+")
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_CODE_TICKS = re.compile(r"^`+|`+$")
_ANGLE_TAG = re.compile(r"<[^>]+>")
_EDGE_PUNCT = re.compile(r"^[#*\-\s]+|[#*\-\s.,;:]+$")
_DIGIT_TIMES = re.compile(r"(?<=\d)[×✕](?=\d)")
_SPLIT_SEPARATORS = re.compile(r"[\s_\-./\\:]+")

# Both functions below are pure string transforms called once per (node, facet)
# pair, so retrieval re-derives the same keys many times over: a warm
# `direct_lookup` on a 7.5 MB graph issued 89,257 `term_key` calls for 4,410
# distinct inputs, a 20x redundancy, with the two hottest inputs repeating
# ~26,000 and ~23,000 times each.
#
# Two different numbers bound the cache size. The working set is the count of
# distinct labels touched by one query -- a few thousand here. The memory bound
# is what an unbounded cache would retain across a long-lived resident process,
# which is every label the process has ever seen. 16384 sits above the observed
# working set while keeping the retained set bounded for the MCP transport.
_TERM_CACHE_SIZE = 16384

_SMALL_WORDS = {
    "a",
    "an",
    "and",
    "as",
    "at",
    "by",
    "for",
    "from",
    "in",
    "into",
    "of",
    "on",
    "or",
    "the",
    "to",
    "with",
}


@lru_cache(maxsize=_TERM_CACHE_SIZE)
def normalize_label(value: str) -> str:
    """Return a stable display label for a term or concept."""
    value = _CODE_TICKS.sub("", value.strip())
    value = _ANGLE_TAG.sub("", value)
    value = _EDGE_PUNCT.sub("", value)
    return _SPACE.sub(" ", value).strip()


@lru_cache(maxsize=_TERM_CACHE_SIZE)
def term_key(value: str) -> str:
    """Return a case/punctuation-insensitive key for semantic equality."""
    label = normalize_label(value)
    if not label:
        return ""
    # Mathematical prose commonly uses the multiplication glyph while source
    # identifiers use ASCII ``x`` (``2×2`` <-> ``mixed_nash_2x2``). Normalize
    # only digit-bounded glyphs so ordinary prose punctuation is unaffected.
    label = _DIGIT_TIMES.sub("x", label)
    parts: list[str] = []
    for raw in _SPLIT_SEPARATORS.split(label):
        if not raw:
            continue
        parts.extend(_CAMEL.sub(" ", raw).split())
    return " ".join(part.lower() for part in parts if part)


def concept_id(value: str, prefix: str = "concept") -> str:
    key = term_key(value)
    slug = _PUNCT.sub("_", key).strip("_")
    return f"{prefix}_{(slug or 'semantic')[:80]}"


def canonical_concept_label(value: str) -> str:
    label = normalize_label(value)
    if not label:
        return ""
    if "_" in label and " " not in label:
        return label
    words = label.split()
    if not words:
        return ""
    if any(any(ch.isupper() for ch in word[1:]) for word in words):
        return label
    titled: list[str] = []
    for index, word in enumerate(words):
        lower = word.lower()
        if index > 0 and lower in _SMALL_WORDS:
            titled.append(lower)
        elif word.isupper() and len(word) <= 6:
            titled.append(word)
        else:
            titled.append(lower[:1].upper() + lower[1:])
    return " ".join(titled)
