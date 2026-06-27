from __future__ import annotations

import re

from ..core import Node


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


def identifier_terms(token: str) -> tuple[str, ...]:
    raw = token.strip("_")
    lowered = raw.lower()
    if len(lowered) < 2:
        return ()

    parts: list[str] = [lowered]
    for piece in re.split(r"[_\-.\\/]+", raw):
        if not piece:
            continue
        parts.append(piece.lower())
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
