from __future__ import annotations

import re
from functools import lru_cache

from ..graph.core import Node

TOKEN = re.compile(r"[A-Za-z0-9_]+")
CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
QUERY_STOPWORDS = {
    "a",
    "about",
    "all",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "can",
    "do",
    "does",
    "for",
    "from",
    "give",
    "how",
    "in",
    "is",
    "it",
    "me",
    "of",
    "on",
    "or",
    "show",
    "tell",
    "that",
    "the",
    "this",
    "to",
    "what",
    "when",
    "where",
    "which",
    "who",
    "why",
    "with",
}


# Building the search index tokenizes every node, and identifier tokens
# repeat heavily across a repo: 350k occurrences of 29k distinct tokens on
# a mid-size Rust workspace, a ~92% hit rate. The function is pure and
# returns an immutable tuple, so memoizing it is safe; the bound keeps a
# pathological corpus from growing this without limit.
@lru_cache(maxsize=65536)
def identifier_terms(token: str) -> tuple[str, ...]:
    raw = token.strip("_")
    lowered = raw.lower()
    if len(lowered) < 2:
        return ()

    parts: list[str] = [lowered]
    for piece in raw.split("_"):
        if not piece:
            continue
        piece_lowered = piece.lower()
        parts.append(piece_lowered)
        if piece_lowered != piece:
            parts.extend(CAMEL_BOUNDARY.sub(" ", piece).lower().split())
    return tuple(dict.fromkeys(part for part in parts if len(part) >= 2))


def tokenize(text: str, *, keep_stopwords: bool = False) -> tuple[str, ...]:
    terms: list[str] = []
    for raw in TOKEN.findall(text):
        for term in identifier_terms(raw):
            if not keep_stopwords and term in QUERY_STOPWORDS:
                continue
            terms.append(term)
    return tuple(dict.fromkeys(terms))


def node_search_text(node: Node) -> str:
    facts = " ".join(node.facts)
    return " ".join((node.id, node.label, node.kind, node.path, node.summary, facts)).lower()
