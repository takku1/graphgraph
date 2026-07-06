from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from ..graph.core import Graph, Node
from .models import Match
from .text import node_search_text, tokenize

DEPENDENCY_QUERY_TERMS = {"dependency", "dependencies", "external", "import", "imports", "module", "package", "vendor"}


@dataclass(frozen=True)
class SearchIndexRow:
    node: Node
    haystack: str
    haystack_terms: set[str]
    node_id: str
    label: str
    path: str
    label_terms: set[str]
    label_term_sequence: tuple[str, ...]
    label_exact_sequence: tuple[str, ...]
    path_name_terms: set[str]
    path_name_sequence: tuple[str, ...]
    path_name_exact_sequence: tuple[str, ...]
    path_stem: str


def search_nodes(
    graph: Graph,
    query: str,
    limit: int = 20,
    doc_intensity: float = 0.0,
    personalize: bool = False,
    scopes: tuple[str, ...] = (),
) -> tuple[Match, ...]:
    """Rank graph nodes with a deterministic lexical score."""
    terms = tokenize(query)
    if not terms:
        return ()
    query_terms = set(terms)
    test_query = bool(query_terms & {"test", "tests", "testing", "pytest", "unittest", "spec", "fixture", "fixtures"})
    dependency_query = bool(query_terms & DEPENDENCY_QUERY_TERMS)

    degree = graph.degree()
    rows = _candidate_rows(graph, terms, scopes)
    if not rows:
        return ()
    if personalize:
        personalization = {}
        for row in rows:
            node_id_case = row.node.id
            score = 0.0
            for term in terms:
                if term == row.node_id:
                    score += 8.0
                if term == row.label:
                    score += 4.0
                elif term in row.label_terms:
                    score += 2.0
            if score > 0:
                personalization[node_id_case] = score
                
        # Discover git-modified files and change counts (Session Layer)
        import math

        from .git_utils import get_git_modified_files
        session_weights = {}
        try:
            modified_paths = get_git_modified_files()
            for path, change_count in modified_paths.items():
                for node_id, node in graph.nodes.items():
                    if node.active and (node.path.replace("\\", "/") == path or node.id == path):
                        session_weights[node_id] = math.log2(change_count + 2) * 2.0
        except Exception:
            pass
            
        for node_id, weight in session_weights.items():
            personalization[node_id] = personalization.get(node_id, 0.0) + weight
            
        pagerank_scores = graph.personalized_pagerank(personalization)
    else:
        pagerank_scores = graph.pagerank()
    matches: list[Match] = []
    for row in rows:
        node = row.node
        haystack = row.haystack
        haystack_terms = row.haystack_terms
        node_id = row.node_id
        label = row.label
        path = row.path
        label_terms = row.label_terms
        label_term_sequence = row.label_term_sequence
        label_exact_sequence = row.label_exact_sequence
        path_name_terms = row.path_name_terms
        path_name_sequence = row.path_name_sequence
        path_name_exact_sequence = row.path_name_exact_sequence
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
            elif term in label_terms:
                score += 4.0
                reasons.append(f"label:{term}")
                matched_terms.add(term)
            elif len(term) >= 5 and term in label:
                score += 4.0
                reasons.append(f"label:{term}")
                matched_terms.add(term)
            if node.path and term == path:
                score += 8.0
                reasons.append(f"path_exact:{term}")
                matched_terms.add(term)
            elif node.path and term in path_name_terms:
                score += 3.0
                reasons.append(f"path:{term}")
                matched_terms.add(term)
            elif node.path and len(term) >= 5 and term in path:
                score += 3.0
                reasons.append(f"path:{term}")
                matched_terms.add(term)
            is_kind_match = (node.kind and term == node.kind.lower()) or (node.kind == "external" and term in DEPENDENCY_QUERY_TERMS)
            if is_kind_match and term not in {"concept", "section", "file", "function", "method", "class"}:
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
            elif len(term) >= 5 and term in haystack and not any(reason.endswith(f":{term}") for reason in reasons):
                score += 0.5
                reasons.append(f"text:{term}")
                matched_terms.add(term)

        if score > 0.0:
            if (
                len(terms) == 1
                and terms[0] == row.path_stem
                and node.kind in {"file", "python", "typescript", "javascript", "rust", "go", "java", "markdown", "rst", "html", "text"}
            ):
                score += 12.0
                reasons.append("basename_stem_exact")
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
            if _is_test_node(node) and not test_query:
                score *= 0.55
                reasons.append("test_context_penalty")
            if node.kind == "concept" and doc_intensity < 0.5:
                score *= 0.45
                reasons.append("concept_status_penalty")
            external_exact = node.kind == "external" and _external_exact_match(node, terms)
            if node.kind == "external":
                if external_exact and (dependency_query or len(terms) == 1):
                    score *= 0.9
                    reasons.append("external_dependency_exact")
                elif external_exact:
                    score *= 0.65
                    reasons.append("external_dependency_penalty")
                else:
                    score *= 0.25
                    reasons.append("external_unresolved_penalty")

            n_scores = len(pagerank_scores)
            pr_val = pagerank_scores.get(node.id, 0.0)
            if n_scores > 0:
                pr_boost = pr_val * n_scores * 2.0
                is_doc_node = node.kind in {"section", "markdown", "concept", "rst", "html", "file"}
                if not is_doc_node:
                    pr_boost *= (1.0 - doc_intensity * 0.85)
                if node.kind == "external" and not (external_exact and dependency_query):
                    pr_boost *= 0.25
                score += min(pr_boost, 8.0)
            else:
                deg_boost = min(degree.get(node.id, 0), 25) * 0.05
                is_doc_node = node.kind in {"section", "markdown", "concept", "rst", "html", "file"}
                if not is_doc_node:
                    deg_boost *= (1.0 - doc_intensity * 0.85)
                if node.kind == "external" and not (external_exact and dependency_query):
                    deg_boost *= 0.25
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


def _row_in_scope(row: SearchIndexRow, normalized_scopes: list[tuple[str, str]]) -> bool:
    if not normalized_scopes:
        return True
    for norm_val in row.node.normalized_scope_values:
        for prefix, prefix_slash in normalized_scopes:
            if norm_val == prefix or norm_val.startswith(prefix_slash):
                return True
    return False


def _candidate_rows(graph: Graph, terms: tuple[str, ...], scopes: tuple[str, ...]) -> tuple[SearchIndexRow, ...]:
    rows = _search_index(graph)
    if not terms:
        return ()
    if scopes:
        normalized_scopes = []
        for scope in scopes:
            norm = scope.replace("\\", "/").strip("/")
            normalized_scopes.append((norm, norm + "/"))
        scoped = tuple(row for row in rows if _row_in_scope(row, normalized_scopes))
        if not scoped:
            return ()
        rows = scoped
        valid_ids = {row.node.id for row in rows}
    else:
        valid_ids = None

    by_term = _search_token_index(graph)
    candidate_ids: set[str] = set()
    for term in terms:
        candidate_ids.update(by_term.get(term, ()))
    if not candidate_ids:
        return rows

    rows_by_id = _search_index_by_id(graph)
    if valid_ids is not None:
        return tuple(rows_by_id[nid] for nid in candidate_ids if nid in valid_ids)
    else:
        return tuple(rows_by_id[nid] for nid in candidate_ids if nid in rows_by_id)


def _search_token_index(graph: Graph) -> dict[str, tuple[str, ...]]:
    key = _search_index_key(graph)
    if graph._search_token_cache and graph._search_token_cache[0] == key:
        return graph._search_token_cache[1]  # type: ignore[return-value]
    by_term: dict[str, set[str]] = defaultdict(set)
    for row in _search_index(graph):
        tokens = (
            set(row.haystack_terms)
            | set(row.label_terms)
            | set(row.path_name_terms)
            | {row.node_id, row.label, row.path}
        )
        for token in tokens:
            if token:
                by_term[token].add(row.node.id)
    cached = {term: tuple(sorted(node_ids)) for term, node_ids in by_term.items()}
    graph._search_token_cache = (key, cached)
    return cached


def _is_test_node(node: Node) -> bool:
    path = node.path.replace("\\", "/").lower() if node.path else ""
    label = node.label.lower()
    return (
        path.startswith("tests/")
        or "/tests/" in path
        or path.startswith("test/")
        or "/test/" in path
        or label.startswith("test_")
        or label.endswith("_test")
    )


def _external_exact_match(node: Node, terms: tuple[str, ...]) -> bool:
    label = node.label.lower()
    node_id = node.id.lower()
    return any(term == label or term == node_id for term in terms)


def _search_index(graph: Graph) -> tuple[SearchIndexRow, ...]:
    key = _search_index_key(graph)
    if graph._search_index_cache and graph._search_index_cache[0] == key:
        return graph._search_index_cache[1]  # type: ignore[return-value]
    rows: list[SearchIndexRow] = []
    for node in graph.nodes.values():
        haystack = node_search_text(node)
        norm_path = node.path.replace("\\", "/") if node.path else ""
        path_name = norm_path.rsplit("/", 1)[-1] if norm_path else ""
        path_stem = path_name.rsplit(".", 1)[0].lower() if path_name else ""
        # Include ALL intermediate directory segments in haystack so that
        # queries like "featherwaight" find src/featherwaight/cli.py even
        # when only the basename ("cli.py") was previously indexed.
        path_dir_segments = "/".join(norm_path.split("/")[:-1]) if "/" in norm_path else ""
        full_haystack = " ".join(filter(None, [haystack, path_dir_segments]))
        label_term_sequence = tuple(tokenize(node.label, keep_stopwords=True))
        path_name_sequence = tuple(tokenize(path_name, keep_stopwords=True))
        # Also tokenize the full path (directories) for the path_name_terms index
        path_dir_terms = set(tokenize(path_dir_segments, keep_stopwords=True)) if path_dir_segments else set()
        rows.append(
            SearchIndexRow(
                node=node,
                haystack=full_haystack,
                haystack_terms=set(tokenize(full_haystack, keep_stopwords=True)),
                node_id=node.id.lower(),
                label=node.label.lower(),
                path=norm_path.lower(),
                label_terms=set(label_term_sequence),
                label_term_sequence=label_term_sequence,
                label_exact_sequence=_exact_identifier_sequence(node.label, label_term_sequence),
                path_name_terms=set(path_name_sequence) | path_dir_terms,
                path_name_sequence=path_name_sequence,
                path_name_exact_sequence=_exact_identifier_sequence(path_name, path_name_sequence),
                path_stem=path_stem,
            )
        )
    cached = tuple(rows)
    graph._search_index_cache = (key, cached)
    return cached


def _search_index_by_id(graph: Graph) -> dict[str, SearchIndexRow]:
    key = _search_index_key(graph)
    if graph._search_index_by_id_cache and graph._search_index_by_id_cache[0] == key:
        return graph._search_index_by_id_cache[1]  # type: ignore[return-value]

    rows = _search_index(graph)
    by_id = {row.node.id: row for row in rows}
    graph._search_index_by_id_cache = (key, by_id)
    return by_id


def _search_index_key(graph: Graph) -> tuple[object, ...]:
    return (
        id(graph),
        graph.structural_signature(),
        graph.metadata.get("git_dirty", ""),
        graph.metadata.get("git_high_churn", ""),
    )


def _exact_identifier_sequence(raw: str, token_sequence: tuple[str, ...]) -> tuple[str, ...]:
    compact = raw.replace("\\", "/").rsplit("/", 1)[-1].rsplit(".", 1)[0].strip("_").lower()
    return tuple(term for term in token_sequence if term != compact)
