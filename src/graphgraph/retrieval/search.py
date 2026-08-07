from __future__ import annotations

import math
import re
from collections import defaultdict
from dataclasses import dataclass
from functools import lru_cache

from ..graph.core import Graph, Node
from ..graph.coupling import EDGE_COUPLINGS, coupled_graph
from . import git_utils
from .models import Match
from .scoping import _is_test_material
from .text import node_search_text, tokenize

# Cached (authority_rank, document_authority, neutral_rank). Loaded lazily: the
# analysis package imports eval -> retrieval, so a module-load import here would
# cycle. By the time search runs, retrieval is fully initialized.
_authority_fns: tuple | None = None


def _node_authority_rank(node: Node) -> int:
    """Authority rank for a doc node, neutral for everything else.

    Only documentation nodes under a ``docs/`` tree carry an authority tier, so
    this differentiates current reference from dated findings while leaving
    code-node ordering untouched (they all resolve to the same neutral rank).
    Used strictly as a *tiebreaker* below score, so it can never demote a
    lexically stronger match.
    """
    global _authority_fns
    if _authority_fns is None:
        from ..analysis.document_authority import authority_rank, document_authority
        _authority_fns = (authority_rank, document_authority, authority_rank("current"))
    authority_rank, document_authority, neutral = _authority_fns
    path = node.path.replace("\\", "/")
    index = path.find("docs/")
    if index == -1:
        return neutral
    return authority_rank(document_authority(path[index + len("docs/"):]))

DEPENDENCY_QUERY_TERMS = {"dependency", "dependencies", "external", "import", "imports", "module", "package", "vendor"}
TEST_QUERY_TERMS = {"test", "tests", "testing", "pytest", "unittest", "spec", "fixture", "fixtures"}
LOCAL_PPR_GRAPH_THRESHOLD = 512

# Generic/placeholder identifier names that don't indicate a well-formed,
# descriptive symbol even if they technically have multiple characters.
_GENERIC_IDENTIFIER_TOKENS = frozenset({
    "x", "y", "z", "i", "j", "k", "n", "m", "a", "b", "c",
    "tmp", "temp", "val", "value", "data", "obj", "item", "el",
    "res", "ret", "out", "arg", "args", "kwargs", "self", "cls",
    "idx", "index", "buf", "buffer", "str", "num", "err", "e",
})

_CAMEL_CASE_SEGMENT = re.compile(r"[A-Z]?[a-z0-9]+|[A-Z]+(?![a-z])")

# Directory segments and filename markers that identify machine-generated or
# vendored sources rather than a project's source of truth. A query that lands
# on both a hand-written definition and its generated stub (e.g. a protobuf
# `*_pb2.py`) should prefer the source the author actually maintains.
_GENERATED_DIR_SEGMENTS = frozenset({
    "generated", "__generated__", "node_modules", "vendor",
    "third_party", "__pycache__", "site-packages",
})
_GENERATED_NAME_MARKERS = (
    "_pb2", ".pb.", ".generated.", "_generated.", ".min.", ".g.dart", ".designer.",
)
# Terms that signal the caller actually wants the generated artifact, which
# suppresses the penalty (mirrors how the test penalty yields to test queries).
_GENERATED_QUERY_TERMS = frozenset({
    "generated", "proto", "protobuf", "grpc", "pb2", "stub", "codegen", "autogen",
})
_BENCHMARK_QUERY_TERMS = frozenset({
    "benchmark", "benchmarks", "performance", "latency", "throughput", "evaluation", "eval",
})
_DOCUMENT_NODE_KINDS = frozenset({"section", "paragraph", "markdown", "concept", "rst", "html", "file", "text"})

# Bounded natural-language -> code-vocabulary bridges. These are deliberately
# directional: a user asking how results are "printed" commonly needs code
# named write/render/emit/output, while a query about writing configuration
# should not be broadened to every printer implementation. Additions require a
# measured retrieval fixture and regression coverage; this is not a thesaurus.
_CODE_QUERY_ALIASES: dict[str, frozenset[str]] = {
    "argument": frozenset({"flag", "flags"}),
    "print": frozenset({"emit", "output", "render", "write"}),
}


def saturating_boost(value: float, cap: float) -> float:
    """Smoothly bound a non-negative boost to ``cap`` without a hard cliff.

    A hard ``min(value, cap)`` collapses every input above the threshold to the
    same score, erasing all ordering among high-centrality nodes -- the exact
    nodes a ranking most needs to separate. ``cap * tanh(value / cap)`` is the
    smooth counterpart: it is ~``value`` while ``value << cap`` (so ordinary
    nodes are unaffected), rises monotonically, and asymptotes to ``cap`` so a
    single hub can never dominate. Being differentiable and cliff-free, it also
    keeps the score well-behaved if these weights are later calibrated to data.
    """
    if cap <= 0.0 or value <= 0.0:
        return 0.0
    return cap * math.tanh(value / cap)


@lru_cache(maxsize=65536)
def identifier_quality_bonus(label: str) -> float:
    """Reward well-formed, multi-segment identifiers over short/generic ones.

    From Aider's repo-map PageRank personalization (see
    docs/research/related-work.md): a descriptive identifier like
    `resolve_modified_node_ids` is far more likely to be what a query
    actually means than a generic single-letter/placeholder name like `x`
    or `tmp`, even when both technically match. Segments a label by
    snake_case or camelCase word boundaries and scales the bonus with
    segment count, capped so it can never dominate an exact match (still
    an order of magnitude below `label_exact_terms`'s +36).

    Memoized like `lexical_forms` above: pure in *label*, and the per-row
    scoring loop in `search_nodes` calls it once per candidate row on every
    personalized search -- a repository's vocabulary of distinct labels is
    far smaller than the number of times a warm session re-scores it.
    """
    if not label:
        return 0.0
    stripped = label.strip("_")
    if not stripped or stripped.lower() in _GENERIC_IDENTIFIER_TOKENS:
        return 0.0
    if "_" in label:
        segments = [s for s in label.split("_") if s]
    else:
        segments = _CAMEL_CASE_SEGMENT.findall(label)
    segments = [s for s in segments if len(s) >= 2]
    if len(segments) <= 1:
        return 0.0
    return min(3.0, 0.5 * (len(segments) - 1))


def _exact_fast_path_match(
    graph: Graph,
    query: str,
    scopes: tuple[str, ...],
) -> tuple[Match, ...] | None:
    """Resolve a query that names one node outright, or None to keep searching.

    Returns a result only when exactly one node matches, so an ambiguous name
    falls through to ranked search rather than picking a winner arbitrarily.
    """
    raw = query.strip()
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in {"`", "'", '"'}:
        raw = raw[1:-1].strip()
    if not raw:
        return None
    normalized = raw.replace("\\", "/").lower()
    explicit_label = any(marker in raw for marker in ("_", "::", ".", "/", "\\", "-")) or any(
        char.isupper() for char in raw
    )
    index = _exact_lookup_index(graph)
    aliases = [("id", f"id:{normalized}"), ("path", f"path_exact:{normalized}")]
    if explicit_label:
        aliases.extend((
            ("label", f"label_exact:{normalized}"),
            ("basename", f"basename_exact:{normalized}"),
        ))
    normalized_scopes = tuple(scope.replace("\\", "/").strip("/") for scope in scopes)
    candidate_reasons: dict[str, list[str]] = defaultdict(list)
    for alias_kind, reason in aliases:
        for node_id in index.get(f"{alias_kind}:{normalized}", ()):
            node = graph.nodes[node_id]
            if not normalized_scopes or any(
                value == scope or value.startswith(scope + "/")
                for value in node.normalized_scope_values
                for scope in normalized_scopes
            ):
                candidate_reasons[node_id].append(reason)
    if len(candidate_reasons) != 1:
        return None
    node_id, reasons = next(iter(candidate_reasons.items()))
    node = graph.nodes[node_id]
    quality = identifier_quality_bonus(node.label)
    return (
        Match(
            node=node,
            score=64.0 + quality,
            reasons=tuple((
                *dict.fromkeys(reasons),
                *(("well_named_identifier",) if quality else ()),
                "exact_fast_path",
            )),
        ),
    )


@lru_cache(maxsize=65536)
def lexical_forms(term: str) -> frozenset[str]:
    """Return conservative English inflections used by lexical retrieval.

    Pure in *term*, and asked the same questions relentlessly: expanding one
    query over an 11.7k-node graph called this 80,000 times, because every
    document row re-derives the forms of its own tokens on every query. Cached
    because the vocabulary of a repository is bounded and far smaller than the
    number of lookups. Returned frozen so the shared value cannot be mutated;
    every caller only iterates it, tests membership, or intersects it.
    """
    forms = {term}
    if term.endswith("ies") and len(term) > 4:
        forms.add(term[:-3] + "y")
    elif term.endswith("ing") and len(term) > 5:
        stem = term[:-3]
        forms.add(stem)
        forms.add(stem + "e")
    elif term.endswith("ed") and len(term) > 4:
        stem = term[:-2]
        forms.add(stem)
        forms.add(stem + "e")
    elif term.endswith("es") and len(term) > 4:
        forms.add(term[:-2])
    elif term.endswith("s") and not term.endswith("ss") and len(term) > 3:
        forms.add(term[:-1])
    return frozenset(form for form in forms if len(form) >= 3)


def code_query_alias_forms(term: str) -> set[str]:
    """Return measured NL-to-code aliases for a query term.

    Inflection stripping is used only to locate the alias key (so ``printed``
    reaches ``print``); ordinary code identifiers are otherwise not stemmed.
    """
    aliases: set[str] = set()
    for form in lexical_forms(term):
        aliases.update(_CODE_QUERY_ALIASES.get(form, ()))
    return aliases


@dataclass(frozen=True)
class SearchIndexRow:
    node: Node
    haystack: str
    #: Frozen, not `set`, because the scoring loop aliases these directly for
    #: non-document rows instead of rebuilding an identical copy per row. These
    #: live on the process-cached search index, so a stray mutation would
    #: corrupt every later query on this graph; `frozenset` makes that
    #: impossible to write rather than merely discouraged by a comment.
    haystack_terms: frozenset[str]
    node_id: str
    label: str
    path: str
    label_terms: frozenset[str]
    label_term_sequence: tuple[str, ...]
    label_exact_sequence: tuple[str, ...]
    path_name_terms: frozenset[str]
    path_name_sequence: tuple[str, ...]
    path_name_exact_sequence: tuple[str, ...]
    path_stem: str
    # Every token this row is findable under, unioned once when the row is
    # built. Candidate selection is then a set intersection per query instead
    # of re-deriving these tokens, which is what made the inverted index worth
    # building in the first place.
    search_tokens: set[str]


def _exact_lookup_index(graph: Graph) -> dict[str, tuple[str, ...]]:
    """`{alias_kind}:{value}` -> node ids for id/label/path/basename lookups.

    Cached on the graph and invalidated by its node revision. Extracted verbatim
    from :func:`search_nodes` for readability; behavior is unchanged.
    """
    if graph._exact_lookup_cache and graph._exact_lookup_cache[0] == graph.node_revision:
        return graph._exact_lookup_cache[1]
    index_sets: dict[str, set[str]] = defaultdict(set)
    for node in graph.nodes.values():
        if not node.active:
            continue
        path = node.path.replace("\\", "/").lower() if node.path else ""
        for alias_kind, value in (
            ("id", node.id.lower()),
            ("label", node.label.lower()),
            ("path", path),
            ("basename", path.rsplit("/", 1)[-1] if path else ""),
        ):
            if value:
                index_sets[f"{alias_kind}:{value}"].add(node.id)
    index = {alias: tuple(sorted(node_ids)) for alias, node_ids in index_sets.items()}
    graph._exact_lookup_cache = (graph.node_revision, index)
    return index


def search_nodes(
    graph: Graph,
    query: str,
    limit: int = 20,
    doc_intensity: float = 0.0,
    personalize: bool = False,
    scopes: tuple[str, ...] = (),
    ppr_mode: str = "auto",
    exact_fast_path: bool = False,
    exact_only: bool = False,
    coupling: str = "directed",
) -> tuple[Match, ...]:
    """Rank graph nodes with a deterministic lexical score.

    ``coupling`` selects the edge orientation the personalized-PageRank signal
    diffuses over, and nothing else: lexical scoring and the degree boost keep
    reading the project's real edges, so the knob isolates the field rather
    than reshaping every structural signal at once.
    """
    if ppr_mode not in {"auto", "exact", "local"}:
        raise ValueError(f"unknown personalized PageRank mode: {ppr_mode}")
    if coupling not in EDGE_COUPLINGS:
        raise ValueError(f"unknown edge coupling: {coupling}")
    if exact_fast_path:
        unambiguous = _exact_fast_path_match(graph, query, scopes)
        if unambiguous is not None:
            return unambiguous
        if exact_only:
            return ()
    terms = tokenize(query)
    if not terms:
        return ()
    # In "command line argument(s)", ``command`` and ``line`` form a compound
    # modifier, not independent requests for subprocess or line-buffer code.
    # Scoring them independently made those two subsystems dominate CLI parser
    # paths. The argument->flag bridge below carries the compound's concrete
    # implementation vocabulary; parse/parsed remains ordinary evidence.
    if (
        "command" in terms
        and "line" in terms
        and any("argument" in lexical_forms(term) for term in terms)
    ):
        terms = tuple(term for term in terms if term not in {"command", "line"})
    # label_term_sequence/label_exact_sequence (built in _search_index) keep
    # stopwords, since a label like "how to deploy" needs "how"/"to" to
    # reconstruct its real word sequence. `terms` above strips them, so a
    # query that's an exact phrase match for such a label could never equal
    # that sequence and the +36 label_exact_terms bonus could never fire.
    # Keep a stopword-preserving variant of the query around just for that
    # exact-sequence comparison.
    terms_with_stopwords = tokenize(query, keep_stopwords=True)
    query_terms = set(terms)
    test_terms = query_terms & TEST_QUERY_TERMS
    # Mentioning tests as one desired evidence type in a broad implementation
    # query should not turn every loosely matching test into a primary anchor.
    # Lift the penalty only when test vocabulary is a material part of intent.
    test_query = bool(test_terms) and len(test_terms) >= math.ceil(0.30 * len(query_terms))
    generated_query = bool(query_terms & _GENERATED_QUERY_TERMS)
    benchmark_query = bool(query_terms & _BENCHMARK_QUERY_TERMS)
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
        session_weights = {}
        modified_paths = git_utils.get_git_modified_files()
        selected_session_nodes = git_utils.select_modified_context_nodes(
            graph,
            modified_paths,
            query,
        )
        for node_id, change_count in selected_session_nodes.items():
            session_weights[node_id] = math.log2(change_count + 2) * 2.0


        for node_id, weight in session_weights.items():
                personalization[node_id] = personalization.get(node_id, 0.0) + weight

        # `tokenize` keeps an underscore-joined identifier as its own term
        # alongside its split words (`retrieve_context` -> `retrieve_context`,
        # `retrieve`, `context`), so a query already written with the
        # underscore satisfies the per-term check below directly. A query
        # that instead spells the same identifier with spaces (a facet-search
        # variant deliberately generated to catch that prose form, or a user
        # typing it that way) tokenizes to only the split words -- no single
        # term ever equals the joined label, even though the words are the
        # exact same identifier. Reconstructing the joined form here closes
        # that gap without touching how anything actually scores or matches.
        joined_terms = "_".join(terms)
        exact_seed = any(
            any(
                term == row.node_id
                or (term == row.label and (len(terms) == 1 or "_" in term))
                for term in terms
            )
            or (len(terms) == 1 and terms[0] == row.path_stem)
            or (len(terms) > 1 and (joined_terms == row.node_id or joined_terms == row.label))
            for row in rows
        )
        use_local_ppr = ppr_mode == "local" or (
            ppr_mode == "auto"
            and len(graph.nodes) > LOCAL_PPR_GRAPH_THRESHOLD
            and exact_seed
        )
        field_graph = coupled_graph(graph, coupling)
        pagerank_scores = (
            field_graph.localized_personalized_pagerank(personalization)
            if use_local_ppr
            else field_graph.personalized_pagerank(personalization)
        )
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
        supporting_test = _is_test_material(node) and not test_query
        document_node = node.kind in _DOCUMENT_NODE_KINDS
        # Only prose gets inflection expansion; a code identifier is matched
        # literally. The non-document branch used to rebuild each set from
        # singleton `{token}` copies -- set-equal to the original, at one
        # allocation per token per row, three sets per row, over thousands of
        # rows per facet-variant search. Aliasing the row's own sets is safe by
        # construction: they are `frozenset` on the index row, so the process
        # cache cannot be corrupted from here even by a future edit.
        if document_node:
            expanded_label_terms = {form for token in label_terms for form in lexical_forms(token)}
            expanded_path_terms = {form for token in path_name_terms for form in lexical_forms(token)}
            expanded_haystack_terms = {form for token in haystack_terms for form in lexical_forms(token)}
        else:
            expanded_label_terms = label_terms
            expanded_path_terms = path_name_terms
            expanded_haystack_terms = haystack_terms
        for term in terms:
            alias_forms = set() if document_node else code_query_alias_forms(term)
            term_forms = (
                {term} | alias_forms
                if not document_node or (supporting_test and term in TEST_QUERY_TERMS)
                else lexical_forms(term)
            )
            if term == node_id:
                score += 8.0
                reasons.append(f"id:{term}")
                matched_terms.add(term)
            if term == label:
                if "_" in term or len(terms) == 1:
                    score += 12.0
                elif node.kind in {"section", "paragraph", "markdown", "text", "rst", "html"}:
                    score += 8.0
                else:
                    score += 4.0
                reasons.append(f"label_exact:{term}")
                matched_terms.add(term)
            elif term in label_terms:
                score += 4.0
                reasons.append(f"label:{term}")
                matched_terms.add(term)
            elif alias_forms & expanded_label_terms:
                score += 4.0
                reasons.append(f"label_alias:{term}")
                matched_terms.add(term)
            elif term_forms & expanded_label_terms:
                score += 4.0
                reasons.append(f"label_inflection:{term}")
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
            elif node.path and alias_forms & expanded_path_terms:
                score += 3.0
                reasons.append(f"path_alias:{term}")
                matched_terms.add(term)
            elif node.path and term_forms & expanded_path_terms:
                score += 3.0
                reasons.append(f"path_inflection:{term}")
                matched_terms.add(term)
            elif node.path and len(term) >= 5 and term in path:
                score += 3.0
                reasons.append(f"path:{term}")
                matched_terms.add(term)
            is_kind_match = (node.kind and term == node.kind.lower()) or (node.kind == "external" and term in DEPENDENCY_QUERY_TERMS)
            if is_kind_match and term not in {"concept", "section", "paragraph", "file", "function", "method", "class"}:
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
            elif alias_forms & expanded_haystack_terms and not any(reason.endswith(f":{term}") for reason in reasons):
                score += 1.0
                reasons.append(f"term_alias:{term}")
                matched_terms.add(term)
            elif term_forms & expanded_haystack_terms and not any(reason.endswith(f":{term}") for reason in reasons):
                score += 1.0
                reasons.append(f"term_inflection:{term}")
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
            if len(query_terms) >= 2 or len(terms_with_stopwords) >= 2:
                if (
                    terms == label_term_sequence or terms == label_exact_sequence
                    or terms_with_stopwords == label_term_sequence or terms_with_stopwords == label_exact_sequence
                ):
                    score += 36.0
                    reasons.append("label_exact_terms")
                elif query_terms <= label_terms:
                    score += 25.0
                    reasons.append("label_all_terms")
                elif document_node and len(label_terms) >= 2 and label_terms <= query_terms:
                    # A curated document heading whose full multi-word title
                    # appears in the query is a direct answer to that concept --
                    # the section "Packet Formats" for "... packet formats ...".
                    # Without this a concise, authoritative section title loses to
                    # any code symbol that merely contains one of the query words
                    # (measured: architecture.md sections ranked ~33rd for a query
                    # that literally lists their titles).
                    score += 20.0
                    reasons.append("section_title_in_query")
                elif len(label_query_matches := {
                    term for term in query_terms
                    if (
                        (
                            {term}
                            if not document_node or (supporting_test and term in TEST_QUERY_TERMS)
                            else lexical_forms(term)
                        )
                        | (code_query_alias_forms(term) if not document_node else set())
                    ) & expanded_label_terms
                }) >= 2:
                    score += 8.0 * (len(label_query_matches) / len(query_terms))
                    reasons.append("label_multi_terms")
                if (
                    terms == path_name_sequence or terms == path_name_exact_sequence
                    or terms_with_stopwords == path_name_sequence or terms_with_stopwords == path_name_exact_sequence
                ):
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
            if document_node and "section_title_in_query" not in reasons:
                # A lexical prose paragraph can repeat every word in a
                # code-flow question while proving none of the flow. Convert
                # document intent into a continuous prior: docs retain full
                # rank for explicit doc queries and become supporting evidence
                # (rather than primary anchors) as doc intent approaches zero.
                # A section explicitly named by the query is exempt -- it is the
                # answer, not incidental prose.
                doc_prior = min(1.0, 0.20 + 0.80 * (doc_intensity / 0.25))
                if doc_prior < 1.0:
                    score *= doc_prior
                    reasons.append("document_intent_prior")
            if _is_test_material(node) and not test_query:
                reasons.append("test_context_penalty")
            if _is_generated_node(node) and not generated_query:
                score *= 0.5
                reasons.append("generated_source_penalty")
            if _is_benchmark_node(node) and not benchmark_query:
                score *= 0.45
                reasons.append("benchmark_context_penalty")
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

            identifier_bonus = identifier_quality_bonus(label)
            if identifier_bonus:
                score += identifier_bonus
                reasons.append("well_named_identifier")

            n_scores = len(pagerank_scores)
            pr_val = pagerank_scores.get(node.id, 0.0)
            if n_scores > 0:
                pr_boost = pr_val * n_scores * 2.0
                is_doc_node = node.kind in _DOCUMENT_NODE_KINDS
                if not is_doc_node:
                    pr_boost *= (1.0 - doc_intensity * 0.85)
                if node.kind == "external" and not (external_exact and dependency_query):
                    pr_boost *= 0.25
                score += saturating_boost(pr_boost, 8.0)
            else:
                deg_boost = saturating_boost(degree.get(node.id, 0) * 0.05, 1.25)
                is_doc_node = node.kind in _DOCUMENT_NODE_KINDS
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

            # Apply this after identifier, topology, and temporal boosts so a
            # tangential test cannot regain primary-anchor rank through those
            # additive signals. Tests remain available through graph traversal.
            if _is_test_material(node) and not test_query:
                score *= 0.30

            matches.append(Match(node=node, score=score, reasons=tuple(dict.fromkeys(reasons))))

    # Authority breaks ties *below* score: when two docs are equally relevant,
    # prefer current reference over dated findings (T10). Code nodes share the
    # neutral rank, so their order is unchanged.
    matches.sort(key=lambda m: (-m.score, -_node_authority_rank(m.node), m.node.path, m.node.label))
    return tuple(matches[:limit])


def _row_in_scope(row: SearchIndexRow, normalized_scopes: list[tuple[str, str]]) -> bool:
    if not normalized_scopes:
        return True
    for norm_val in row.node.normalized_scope_values:
        for prefix, prefix_slash in normalized_scopes:
            if norm_val == prefix or norm_val.startswith(prefix_slash):
                return True
    return False


def _search_tokens_for(kind: str, tokens: set[str]) -> set[str]:
    """Every token a row is findable under, computed once as the row is built."""
    if kind in _DOCUMENT_NODE_KINDS:
        tokens = tokens | {form for token in tuple(tokens) for form in lexical_forms(token)}
    return {token for token in tokens if token}


def _candidate_ids_for_forms(graph: Graph, wanted_forms: set[str]) -> set[str]:
    """Node ids reachable from *wanted_forms*.

    This used to require a full inverted index -- 37,465 postings built to serve
    about five lookups, ~350 ms on an 11.7k-node graph, paid on every process
    because the CLI runs one query and exits. Now that each row carries its own
    token set, selection is a set intersection and no index is needed.

    Scans unscoped rows, exactly as the index was built from unscoped rows, so
    scope filtering downstream sees the same candidates as before.
    """
    return {row.node.id for row in _search_index(graph) if row.search_tokens & wanted_forms}


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

    wanted_forms: set[str] = set()
    for term in terms:
        wanted_forms |= lexical_forms(term) | code_query_alias_forms(term)
    candidate_ids = _candidate_ids_for_forms(graph, wanted_forms)
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
        tokens = row.search_tokens
        for token in tokens:
            if token:
                by_term[token].add(row.node.id)
    cached = {term: tuple(sorted(node_ids)) for term, node_ids in by_term.items()}
    graph._search_token_cache = (key, cached)
    return cached


@lru_cache(maxsize=65536)
def _is_generated_node(node: Node) -> bool:
    # Memoized like `_is_test_material`: pure in *node*, one call per
    # candidate row per personalized search.
    path = node.path.replace("\\", "/").lower() if node.path else ""
    if not path:
        return False
    if set(path.split("/")) & _GENERATED_DIR_SEGMENTS:
        return True
    name = path.rsplit("/", 1)[-1]
    return any(marker in name for marker in _GENERATED_NAME_MARKERS)


@lru_cache(maxsize=65536)
def _is_benchmark_node(node: Node) -> bool:
    path = node.path.replace("\\", "/").lower() if node.path else ""
    return bool(set(path.split("/")) & {"benchmark", "benchmarks", "bench"})


def _external_exact_match(node: Node, terms: tuple[str, ...]) -> bool:
    label = node.label.lower()
    node_id = node.id.lower()
    return any(term == label or term == node_id for term in terms)


def _search_index(graph: Graph) -> tuple[SearchIndexRow, ...]:
    key = _search_index_key(graph)
    if graph._search_index_cache and graph._search_index_cache[0] == key:
        return graph._search_index_cache[1]  # type: ignore[return-value]
    rows: list[SearchIndexRow] = []
    # Every path-derived field below depends only on node.path, and a
    # repository has far fewer distinct paths than nodes -- 13.8k nodes over
    # 510 distinct basenames and 59 distinct directories on this graph, so the
    # basename tokenization was repeating at a 96% rate and the directory one
    # at 99.6%. Deriving them once per distinct path removes that work from
    # every index build. Deliberately local rather than an lru_cache on
    # tokenize: the haystack strings are unique per node (76% of the tokenized
    # volume, 0% reuse), so a global cache would retain megabytes to serve no
    # hits, and this dict cannot outlive the build or pin nodes.
    path_cache: dict[str, tuple] = {}
    for node in graph.nodes.values():
        if not node.active:
            # Consistent with pagerank/expand/degree elsewhere in the graph:
            # a soft-deleted (expire_node) node must not be searchable or
            # chosen as an anchor. Previously this was the only place in the
            # retrieval path that didn't filter on active, so a query could
            # surface an expired node as a top hit and expand() would then
            # silently drop it, producing an empty/degraded packet with no
            # explanation of why.
            continue
        haystack = node_search_text(node)
        derived = path_cache.get(node.path)
        if derived is None:
            norm_path = node.path.replace("\\", "/") if node.path else ""
            path_name = norm_path.rsplit("/", 1)[-1] if norm_path else ""
            path_stem = path_name.rsplit(".", 1)[0].lower() if path_name else ""
            # Include ALL intermediate directory segments in haystack so that
            # queries like "featherwaight" find src/featherwaight/cli.py even
            # when only the basename ("cli.py") was previously indexed.
            path_dir_segments = "/".join(norm_path.split("/")[:-1]) if "/" in norm_path else ""
            path_name_sequence = tuple(tokenize(path_name, keep_stopwords=True))
            # Also tokenize the full path (directories) for the path_name_terms index
            path_dir_terms = set(tokenize(path_dir_segments, keep_stopwords=True)) if path_dir_segments else set()
            derived = (
                path_stem,
                path_dir_segments,
                path_name_sequence,
                frozenset(path_name_sequence) | path_dir_terms,
                _exact_identifier_sequence(path_name, path_name_sequence),
                norm_path.lower(),
            )
            path_cache[node.path] = derived
        (
            path_stem,
            path_dir_segments,
            path_name_sequence,
            path_name_terms,
            path_name_exact_sequence,
            path_lower,
        ) = derived
        full_haystack = " ".join(filter(None, [haystack, path_dir_segments]))
        label_term_sequence = tuple(tokenize(node.label, keep_stopwords=True))
        haystack_terms = frozenset(tokenize(full_haystack, keep_stopwords=True))
        node_id_lower = node.id.lower()
        label_lower = node.label.lower()
        label_terms = frozenset(label_term_sequence)
        rows.append(
            SearchIndexRow(
                node=node,
                haystack=full_haystack,
                haystack_terms=haystack_terms,
                node_id=node_id_lower,
                label=label_lower,
                path=path_lower,
                label_terms=label_terms,
                label_term_sequence=label_term_sequence,
                label_exact_sequence=_exact_identifier_sequence(node.label, label_term_sequence),
                path_name_terms=path_name_terms,
                path_name_sequence=path_name_sequence,
                path_name_exact_sequence=path_name_exact_sequence,
                path_stem=path_stem,
                search_tokens=_search_tokens_for(
                    node.kind,
                    haystack_terms | label_terms | path_name_terms | {node_id_lower, label_lower, path_lower},
                ),
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
        graph.node_revision,
        graph.metadata.get("git_dirty", ""),
        graph.metadata.get("git_high_churn", ""),
    )


def _exact_identifier_sequence(raw: str, token_sequence: tuple[str, ...]) -> tuple[str, ...]:
    compact = raw.replace("\\", "/").rsplit("/", 1)[-1].rsplit(".", 1)[0].strip("_").lower()
    return tuple(term for term in token_sequence if term != compact)
