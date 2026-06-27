from __future__ import annotations

from ..core import Graph

from .models import Match
from .text import node_search_text, tokenize


def search_nodes(graph: Graph, query: str, limit: int = 8, is_doc: bool = False) -> tuple[Match, ...]:
    """Rank graph nodes with a deterministic lexical score."""
    terms = tokenize(query)
    if not terms:
        return ()
    query_terms = set(terms)

    degree = graph.degree()
    pagerank_scores = graph.pagerank()
    matches: list[Match] = []
    for node in graph.nodes.values():
        haystack = node_search_text(node)
        haystack_terms = set(tokenize(haystack, keep_stopwords=True))
        node_id = node.id.lower()
        label = node.label.lower()
        path = node.path.lower() if node.path else ""
        label_terms = set(tokenize(node.label, keep_stopwords=True))
        label_term_sequence = tuple(tokenize(node.label, keep_stopwords=True))
        label_exact_sequence = _exact_identifier_sequence(node.label, label_term_sequence)
        path_name = node.path.replace("\\", "/").rsplit("/", 1)[-1] if node.path else ""
        path_name_terms = set(tokenize(path_name, keep_stopwords=True))
        path_name_sequence = tuple(tokenize(path_name, keep_stopwords=True))
        path_name_exact_sequence = _exact_identifier_sequence(path_name, path_name_sequence)
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
            if node.kind and term == node.kind.lower() and term not in {"concept", "section", "file", "function", "method", "class"}:
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
            if len(query_terms) >= 2:
                if terms == label_term_sequence or terms == label_exact_sequence:
                    score += 36.0
                    reasons.append("label_exact_terms")
                elif query_terms <= label_terms:
                    score += 25.0
                    reasons.append("label_all_terms")
                elif len(query_terms & label_terms) >= 2:
                    score += 8.0 * (len(query_terms & label_terms) / len(query_terms))
                    reasons.append("label_multi_terms")
                if terms == path_name_sequence or terms == path_name_exact_sequence:
                    score += 24.0
                    reasons.append("basename_exact_terms")
                elif query_terms <= path_name_terms:
                    score += 16.0
                    reasons.append("basename_all_terms")
            if not any(reason.startswith(("id:", "label", "path")) or reason in {"label_exact_terms", "label_all_terms", "label_multi_terms", "basename_exact_terms", "basename_all_terms"} for reason in reasons):
                score *= 0.35
                reasons.append("weak_text_only")
            coverage = len(matched_terms) / len(terms)
            score *= 0.5 + coverage
            if node.kind == "community":
                score *= 0.65

            n_scores = len(pagerank_scores)
            pr_val = pagerank_scores.get(node.id, 0.0)
            if n_scores > 0:
                pr_boost = pr_val * n_scores * 2.0
                if is_doc:
                    is_doc_node = node.kind in {"section", "markdown", "concept", "rst", "html", "file"}
                    if not is_doc_node:
                        pr_boost *= 0.15
                score += min(pr_boost, 8.0)
            else:
                deg_boost = min(degree.get(node.id, 0), 25) * 0.05
                if is_doc:
                    is_doc_node = node.kind in {"section", "markdown", "concept", "rst", "html", "file"}
                    if not is_doc_node:
                        deg_boost *= 0.15
                score += deg_boost

            # --- GIT TEMPORAL GRAVITY ---
            git_dirty = graph.metadata.get("git_dirty", "").split(",") if hasattr(graph, "metadata") and graph.metadata else []
            git_high_churn = graph.metadata.get("git_high_churn", "").split(",") if hasattr(graph, "metadata") and graph.metadata else []

            is_dirty = bool(node.path and node.path in git_dirty)
            is_high_churn = bool(node.path and node.path in git_high_churn)

            if is_dirty or is_high_churn:
                temporal_query = any(w in query.lower() for w in {"bug", "fix", "change", "modify", "recent", "dirty", "touch", "break", "error", "fail", "git", "diff", "edited"})
                if temporal_query:
                    score += 6.0
                    reasons.append("git_dirty_temporal" if is_dirty else "git_churn_temporal")
                else:
                    score += 1.5
                    reasons.append("git_dirty" if is_dirty else "git_churn")

            matches.append(Match(node=node, score=score, reasons=tuple(dict.fromkeys(reasons))))

    matches.sort(key=lambda m: (-m.score, m.node.path, m.node.label))
    return tuple(matches[:limit])


def _exact_identifier_sequence(raw: str, token_sequence: tuple[str, ...]) -> tuple[str, ...]:
    compact = raw.replace("\\", "/").rsplit("/", 1)[-1].rsplit(".", 1)[0].strip("_").lower()
    return tuple(term for term in token_sequence if term != compact)
