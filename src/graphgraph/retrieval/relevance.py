from __future__ import annotations

import math
from collections import Counter

from ..graph.core import Graph, Node
from .text import QUERY_STOPWORDS, TOKEN, identifier_terms

# Okapi BM25 parameters. k1 controls term-frequency saturation; b controls how
# aggressively long documents are penalised. These are the standard IR defaults
# and are deliberately not query-class-specific: BM25's own length
# normalisation already adapts to the wide size range of doc sections.
BM25_K1 = 1.5
BM25_B = 0.75

# A section's heading (its node label) is a far stronger topical signal than any
# single sentence in its body -- "Installation" as a heading means the whole
# section is about installation. We model that as a field-weighted document
# (a lightweight BM25F): heading terms are counted with extra multiplicity so a
# query term appearing in the heading outweighs the same term buried in prose,
# without needing a separate per-field length model.
HEADING_FIELD_WEIGHT = 3

# Kinds whose ranking benefits from query-conditioned text relevance. These are
# prose/documentation nodes where graph distance alone does not distinguish a
# query-relevant section from an irrelevant sibling at the same hop depth.
DOC_RELEVANCE_KINDS = frozenset(
    {"section", "paragraph", "markdown", "rst", "html", "text", "concept", "docstring"}
)


def _field_terms(text: str) -> list[str]:
    """Frequency-preserving tokenisation (unlike text.tokenize, which dedupes)."""
    terms: list[str] = []
    for raw in TOKEN.findall(text or ""):
        for term in identifier_terms(raw):
            if term in QUERY_STOPWORDS:
                continue
            terms.append(term)
    return terms


def _document_terms(node: Node) -> Counter:
    counts: Counter = Counter()
    heading = _field_terms(node.label)
    for _ in range(HEADING_FIELD_WEIGHT):
        counts.update(heading)
    for fact in node.facts:
        counts.update(_field_terms(fact))
    if node.summary:
        counts.update(_field_terms(node.summary))
    return counts


def bm25_scores(nodes: list[Node], query_terms: tuple[str, ...]) -> dict[str, float]:
    """Okapi BM25 relevance of each node's text against the query terms.

    The corpus is the supplied ``nodes`` themselves, so IDF is computed
    relative to the candidate set actually competing for the budget -- a term
    that is common across every candidate section contributes little, while a
    discriminating term dominates the ranking. Returns raw BM25 scores; callers
    normalise as needed. An empty query or corpus yields ``{}``.
    """
    if not query_terms or not nodes:
        return {}
    docs = {node.id: _document_terms(node) for node in nodes}
    total = len(docs)
    lengths = {nid: sum(counts.values()) for nid, counts in docs.items()}
    avgdl = (sum(lengths.values()) / total) or 1.0

    doc_freq: Counter = Counter()
    for counts in docs.values():
        doc_freq.update(counts.keys())

    active_terms = [term for term in dict.fromkeys(query_terms) if term in doc_freq]
    if not active_terms:
        return {nid: 0.0 for nid in docs}

    idf = {
        term: math.log(1.0 + (total - doc_freq[term] + 0.5) / (doc_freq[term] + 0.5))
        for term in active_terms
    }

    scores: dict[str, float] = {}
    for nid, counts in docs.items():
        length = lengths[nid]
        norm = BM25_K1 * (1.0 - BM25_B + BM25_B * length / avgdl)
        score = 0.0
        for term in active_terms:
            freq = counts.get(term, 0)
            if not freq:
                continue
            score += idf[term] * (freq * (BM25_K1 + 1.0)) / (freq + norm)
        scores[nid] = score
    return scores


def relevance_multipliers(
    nodes: list[Node],
    query_terms: tuple[str, ...],
    *,
    strength: float = 1.5,
) -> dict[str, float]:
    """Per-node selection-value multipliers from normalised BM25 relevance.

    Only prose/doc nodes (``DOC_RELEVANCE_KINDS``) are scored; structural nodes
    keep a multiplier of 1.0 so topology-first query classes are unaffected. The
    returned multiplier is ``1 + strength * (bm25 / max_bm25)``, so the most
    query-relevant section can outweigh an equal-hop-distance sibling while a
    section with no matching terms is left at its graph-distance value. When the
    query matches nothing, every multiplier is 1.0 (a no-op).
    """
    doc_nodes = [node for node in nodes if node.kind in DOC_RELEVANCE_KINDS]
    scores = bm25_scores(doc_nodes, query_terms)
    if not scores:
        return {}
    top = max(scores.values())
    if top <= 0.0:
        return {}
    return {
        nid: 1.0 + strength * (score / top)
        for nid, score in scores.items()
        if score > 0.0
    }


def section_priority_bias(
    graph: Graph,
    starts: tuple[str, ...],
    query_terms: tuple[str, ...],
    *,
    strength: float = 3.0,
) -> dict[str, float]:
    """Normalised BM25 relevance bias for the doc/section neighbours of starts.

    Feeds ``graph.expand(priority_bias=...)``: the returned value for each
    one-hop documentation neighbour is ``strength * (bm25 / max_bm25)`` in
    ``[0, strength]``, so expand's frontier truncation keeps the sections most
    relevant to the query instead of ranking sections purely by graph shape.
    Sections sit one hop from their document anchor, which is exactly the
    frontier expand ranks. Returns ``{}`` when nothing matches (a no-op bias).
    """
    if not query_terms or not starts:
        return {}
    outgoing = graph.outgoing()
    incoming = graph.incoming()
    neighbours: dict[str, Node] = {}
    for start in starts:
        for edge in outgoing.get(start, []) + incoming.get(start, []):
            other = edge.target if edge.source == start else edge.source
            node = graph.nodes.get(other)
            if node is not None and node.active and node.kind in DOC_RELEVANCE_KINDS:
                neighbours[other] = node
    scores = bm25_scores(list(neighbours.values()), query_terms)
    if not scores:
        return {}
    top = max(scores.values())
    if top <= 0.0:
        return {}
    return {nid: strength * (score / top) for nid, score in scores.items() if score > 0.0}
