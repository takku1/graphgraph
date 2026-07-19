from __future__ import annotations

import re

PLAN_TOKEN = re.compile(r"[A-Za-z0-9_]+")

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

DEFAULT_NODE_BUDGETS = {
    "direct_lookup": 80,
    "reverse_lookup": 80,
    "affected_tests": 60,
    "multi_hop_path": 80,
    # 8, not 1: a 1-node budget caps expansion back down to just the anchor
    # even with hops=1, which would silently undo the point of raising hops
    # (see choose_packet's negative_query branch). 8 is enough to surface
    # real direct evidence of use without ballooning into a full expansion.
    "negative_query": 8,
    # Exact/high-confidence summaries remain recall-first. Natural-language
    # queries without a targeted anchor receive a smaller runtime cap after
    # anchor discovery (retrieval/context.py).
    "subsystem_summary": 120,
    "blast_radius": 120,
    "spreading_activation": 120,
    # Recent-changes results are a short list of qualifying commits per file,
    # not a deep expansion -- 40 comfortably covers a well-touched file's
    # fix history without ballooning into unrelated subsystem context.
    "recent_changes": 40,
}
DEFAULT_FALLBACK_NODE_BUDGET = 120
DOC_NODE_BUDGET = 12

# A query is treated as documentation-intent when this fraction of its words hit
# a doc keyword (query_class == "doc_summary" always qualifies).
DOC_INTENSITY_THRESHOLD = 0.25
DOC_KEYWORDS = frozenset(
    {"readme", "install", "usage", "documentation", "guide", "setup", "docs", "markdown", "md"}
)


def default_anchor_limit(query: str, query_class: str) -> int:
    term_count = len(plan_terms(query))
    identifiers = explicit_query_identifiers(query)
    if query_class in {"direct_lookup", "reverse_lookup", "affected_tests", "blast_radius"} and identifiers:
        # A single exact symbol should stay surgical. Contract/test questions
        # often name several exact methods plus a CamelCase type or trait; the
        # old any-underscore gate collapsed those multi-entity queries to one
        # anchor and made the other requested evidence unreachable.
        if len(identifiers) == 1:
            return 1
        return min(8, max(3, len(identifiers) * 2))
    if query_class in {"direct_lookup", "reverse_lookup", "affected_tests"}:
        return max(3, min(6, term_count + 1))
    if is_doc_query(query_class, query):
        return 6
    if query_class == "subsystem_summary":
        return max(6, min(16, term_count * 3))
    if query_class == "blast_radius":
        if term_count <= 2:
            return 6
        return max(3, min(8, term_count + 2))
    return 3


def retrieval_node_budget(query: str, query_class: str, max_nodes: int | None) -> int | None:
    if is_doc_query(query_class, query):
        return min(max_nodes, DOC_NODE_BUDGET) if max_nodes is not None else DOC_NODE_BUDGET
    if max_nodes is None:
        return default_node_budget(query_class, query)
    if query_class != "subsystem_summary":
        return max_nodes
    summary_budget = max(16, min(32, len(plan_terms(query)) * 8))
    return min(max_nodes, summary_budget)


def default_node_budget(query_class: str, query: str = "") -> int:
    if is_doc_query(query_class, query):
        return DOC_NODE_BUDGET
    return DEFAULT_NODE_BUDGETS.get(query_class, DEFAULT_FALLBACK_NODE_BUDGET)


def is_doc_query(query_class: str, query: str) -> bool:
    return doc_intensity_score(query_class, query) >= DOC_INTENSITY_THRESHOLD


def doc_intensity_score(query_class: str, query: str) -> float:
    if query_class == "doc_summary":
        return 1.0
    query_words = [w for w in query.lower().split() if len(w) > 1]
    if not query_words:
        return 0.0
    matches = sum(1 for w in query_words if any(k in w for k in DOC_KEYWORDS))
    return matches / len(query_words)


def plan_terms(text: str) -> tuple[str, ...]:
    terms = [term.lower().strip("_") for term in PLAN_TOKEN.findall(text)]
    return tuple(dict.fromkeys(term for term in terms if len(term) >= 2 and term not in QUERY_STOPWORDS))


def explicit_query_identifiers(text: str) -> tuple[str, ...]:
    """Return code-shaped identifiers explicitly named by the user."""
    identifiers = []
    for raw in PLAN_TOKEN.findall(text):
        # Sentence-initial prose such as ``How`` is capitalized but is not a
        # code-shaped identifier. Require an uppercase transition after the
        # first character for CamelCase/PascalCase names.
        has_mixed_case = any(char.islower() for char in raw) and any(char.isupper() for char in raw[1:])
        if "_" not in raw and not has_mixed_case:
            continue
        folded = raw.casefold()
        if len(folded.strip("_")) >= 2 and folded not in identifiers:
            identifiers.append(folded)
    return tuple(identifiers)
