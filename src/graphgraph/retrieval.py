from __future__ import annotations

import re
from dataclasses import dataclass

from .core import Edge, Graph, Node
from .ontology import is_weak_relation, provenance_confidence
from .policies import path_matches
from .traversal import relation_rank, traversal_policy


_TOKEN = re.compile(r"[A-Za-z0-9_]+")
_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_QUERY_STOPWORDS = {
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
_DOC_QUERY = re.compile(r"\b(readme|docs?|documentation|guide|install(?:ation)?|usage|setup|tutorial|manual)\b", re.IGNORECASE)
_DEFAULT_EDGE_TYPE_LIMITS = {
    "references": 16,
    "links": 16,
    "includes": 16,
}
_DEFAULT_UNKNOWN_WEAK_LIMIT = 12


@dataclass(frozen=True)
class Match:
    node: Node
    score: float
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class RetrievalResult:
    starts: tuple[str, ...]
    matches: tuple[Match, ...]
    nodes: set[str]
    edges: list[Edge]


def _identifier_terms(token: str) -> tuple[str, ...]:
    token = token.strip("_").lower()
    if len(token) < 2:
        return ()

    parts: list[str] = [token]
    for piece in re.split(r"[_\-.\\/]+", token):
        if not piece:
            continue
        parts.append(piece)
        parts.extend(_CAMEL_BOUNDARY.sub(" ", piece).lower().split())
    return tuple(dict.fromkeys(part for part in parts if len(part) >= 2))


def tokenize(text: str, *, keep_stopwords: bool = False) -> tuple[str, ...]:
    terms: list[str] = []
    for raw in _TOKEN.findall(text):
        for term in _identifier_terms(raw):
            if not keep_stopwords and term in _QUERY_STOPWORDS:
                continue
            terms.append(term)
    return tuple(dict.fromkeys(terms))


def node_search_text(node: Node) -> str:
    facts = " ".join(node.facts)
    return " ".join((node.id, node.label, node.kind, node.path, node.summary, facts)).lower()


def search_nodes(graph: Graph, query: str, limit: int = 8) -> tuple[Match, ...]:
    """Rank graph nodes with a deterministic lexical score.

    This is intentionally dependency-free. It is not a semantic retriever; it is
    a native bootstrap retriever so graphgraph can find graph anchors itself.
    """
    terms = tokenize(query)
    if not terms:
        return ()

    degree = graph.degree()
    matches: list[Match] = []
    for node in graph.nodes.values():
        haystack = node_search_text(node)
        haystack_terms = set(tokenize(haystack, keep_stopwords=True))
        node_id = node.id.lower()
        label = node.label.lower()
        path = node.path.lower()
        score = 0.0
        reasons: list[str] = []
        matched_terms: set[str] = set()
        for term in terms:
            if term == node_id:
                score += 8.0
                reasons.append(f"id:{term}")
                matched_terms.add(term)
            if term == label:
                if "_" in term or len(terms) == 1:
                    score += 12.0
                elif node.kind in {"section", "markdown", "text", "rst", "html"}:
                    score += 8.0
                else:
                    score += 4.0
                reasons.append(f"label_exact:{term}")
                matched_terms.add(term)
            elif term in label:
                score += 4.0
                reasons.append(f"label:{term}")
                matched_terms.add(term)
            if node.path and term == path:
                score += 8.0
                reasons.append(f"path_exact:{term}")
                matched_terms.add(term)
            elif node.path and term in path:
                score += 3.0
                reasons.append(f"path:{term}")
                matched_terms.add(term)
            if node.kind and term == node.kind.lower():
                score += 2.0
                reasons.append(f"kind:{term}")
                matched_terms.add(term)
            if node.summary and term in node.summary.lower():
                score += 1.5
                reasons.append(f"summary:{term}")
                matched_terms.add(term)
            if any(term in fact.lower() for fact in node.facts):
                score += 1.0
                reasons.append(f"fact:{term}")
                matched_terms.add(term)
            if term in haystack_terms and not any(reason.endswith(f":{term}") for reason in reasons):
                score += 1.0
                reasons.append(f"term:{term}")
                matched_terms.add(term)
            elif term in haystack and not any(reason.endswith(f":{term}") for reason in reasons):
                score += 0.5
                reasons.append(f"text:{term}")
                matched_terms.add(term)

        if score > 0.0:
            coverage = len(matched_terms) / len(terms)
            score *= 0.5 + coverage
            if node.kind == "community":
                score *= 0.65
            score += min(degree.get(node.id, 0), 25) * 0.05
            matches.append(Match(node=node, score=score, reasons=tuple(dict.fromkeys(reasons))))

    matches.sort(key=lambda m: (-m.score, m.node.path, m.node.label))
    return tuple(matches[:limit])


def retrieve_context(
    graph: Graph,
    query: str,
    query_class: str,
    hops: int,
    anchor_limit: int | None = None,
    max_nodes: int | None = None,
    scopes: tuple[str, ...] = (),
) -> RetrievalResult:
    effective_anchor_limit = anchor_limit if anchor_limit is not None else default_anchor_limit(query, query_class)
    matches = search_nodes(graph, query, limit=max(effective_anchor_limit, 1))
    starts = tuple(match.node.id for match in matches[:effective_anchor_limit])
    if not starts:
        return RetrievalResult(starts=(), matches=matches, nodes=set(), edges=[])

    effective_max_nodes = retrieval_node_budget(query, query_class, max_nodes)
    nodes, edges = graph.expand(list(starts), hops=hops, max_nodes=effective_max_nodes, scopes=scopes)
    policy = traversal_policy(query_class)
    edges = [
        edge for edge in edges
        if edge.confidence * provenance_confidence(edge.provenance) >= policy.min_confidence
    ]
    edges = sorted(edges, key=lambda e: (*relation_rank(e.type, policy), e.source, e.target))
    edges = budget_edges(edges, max_nodes=effective_max_nodes, weak_limit=policy.weak_edge_limit)
    nodes, edges = enrich_runtime_context(graph, nodes, edges, max_nodes=effective_max_nodes)
    return RetrievalResult(starts=starts, matches=matches, nodes=nodes, edges=edges)


def default_anchor_limit(query: str, query_class: str) -> int:
    """Pick anchor breadth by query shape.

    Direct and reverse lookups should stay tight. Summary queries often name a
    family of related symbols where each symbol only matches one or two terms,
    so they need broader starts before traversal can do useful compression.
    """
    term_count = len(tokenize(query))
    if query_class in {"direct_lookup", "reverse_lookup"} and any("_" in raw for raw in _TOKEN.findall(query)):
        return 1
    if query_class == "doc_summary" or (query_class == "subsystem_summary" and _DOC_QUERY.search(query)):
        return 3
    if query_class == "subsystem_summary":
        return max(6, min(16, term_count * 3))
    if query_class == "blast_radius":
        return max(3, min(6, term_count))
    return 3


def retrieval_node_budget(query: str, query_class: str, max_nodes: int | None) -> int | None:
    if query_class == "doc_summary" or (query_class == "subsystem_summary" and _DOC_QUERY.search(query)):
        doc_budget = 12
        return min(max_nodes, doc_budget) if max_nodes is not None else doc_budget
    if query_class != "subsystem_summary":
        return max_nodes
    summary_budget = max(16, min(24, len(tokenize(query)) * 5))
    return min(max_nodes, summary_budget) if max_nodes is not None else summary_budget


def enrich_runtime_context(
    graph: Graph,
    nodes: set[str],
    edges: list[Edge],
    max_nodes: int | None = None,
    decision_trace_limit: int = 3,
) -> tuple[set[str], list[Edge]]:
    included = set(nodes)
    out_edges = list(edges)

    def room() -> bool:
        return max_nodes is None or len(included) < max_nodes

    # Policy nodes are governance context. Link matching policy scopes to included source paths.
    policy_nodes = [node for node in graph.nodes.values() if node.kind == "policy" and node.active]
    for policy in policy_nodes:
        if not room():
            break
        for nid in list(included):
            node = graph.nodes.get(nid)
            if not node or not node.path:
                continue
            scopes = tuple(s.strip() for s in policy.scope.split(",") if s.strip())
            if scopes and any(path_matches(scope, node.path) for scope in scopes):
                included.add(policy.id)
                out_edges.append(Edge(nid, policy.id, "constrained_by", provenance="policy", confidence=1.0))
                break

    # Decision traces become useful when they cite inputs or policies already in scope.
    trace_count = 0
    for edge in graph.edges:
        if trace_count >= decision_trace_limit or not room():
            break
        if edge.type not in {"used_input", "applied_policy"}:
            continue
        if edge.target in included and edge.source in graph.nodes:
            trace = graph.nodes[edge.source]
            if trace.kind == "decision_trace" and trace.active and edge.source not in included:
                included.add(edge.source)
                out_edges.append(edge)
                trace_count += 1

    return included, out_edges


def budget_edges(edges: list[Edge], max_nodes: int | None = None, weak_limit: int | None = None) -> list[Edge]:
    """Limit weak edge types after graph expansion.

    Regex-derived references are useful for recall, but they can dominate compact
    packets on large codebases. Strong structural edges are left uncapped.
    """
    limits = dict(_DEFAULT_EDGE_TYPE_LIMITS)
    if weak_limit is not None:
        for key in limits:
            limits[key] = weak_limit
    if max_nodes is not None:
        limits["references"] = max(8, min(limits["references"], max_nodes // 2))

    counts: dict[str, int] = {}
    kept: list[Edge] = []
    for edge in edges:
        limit = limits.get(edge.type)
        if limit is None and is_weak_relation(edge.type):
            limit = weak_limit if weak_limit is not None else _DEFAULT_UNKNOWN_WEAK_LIMIT
        if limit is None:
            kept.append(edge)
            continue
        current = counts.get(edge.type, 0)
        if current < limit:
            counts[edge.type] = current + 1
            kept.append(edge)
    return kept
