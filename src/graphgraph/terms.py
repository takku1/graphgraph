from __future__ import annotations

import re


_SPACE = re.compile(r"\s+")
_PUNCT = re.compile(r"[^A-Za-z0-9_]+")
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_CODE_TICKS = re.compile(r"^`+|`+$")

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


def normalize_label(value: str) -> str:
    """Return a stable display label for a term or concept."""
    value = _CODE_TICKS.sub("", value.strip())
    value = re.sub(r"<[^>]+>", "", value)
    value = re.sub(r"^[#*\-\s]+|[#*\-\s.,;:]+$", "", value)
    return _SPACE.sub(" ", value).strip()


def term_key(value: str) -> str:
    """Return a case/punctuation-insensitive key for semantic equality."""
    label = normalize_label(value)
    if not label:
        return ""
    parts: list[str] = []
    for raw in re.split(r"[\s_\-./\\:]+", label):
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

