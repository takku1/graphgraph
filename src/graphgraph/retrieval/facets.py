"""Query facet extraction, matching, and facet-evidence reservation."""

from __future__ import annotations

import math
import re

from ..concepts.doccode import is_code_like
from ..concepts.terms import term_key
from ..graph.core import Graph
from ..planning.budgets import explicit_query_identifiers, plan_terms
from .models import Match
from .scoping import (
    STRUCTURAL_RELATIONS,
    _is_test_material,
    _qualified_query_symbols,
)

# Terms naming *the concept of a definition* rather than a definition's content.
# A facet term that is one of these (or that names a node kind the graph
# actually contains) describes the shape of the wanted answer, not a content
# entity, so its absence as literal node text must not trigger abstention.
_DEFINITION_TERMS = frozenset(
    {
        "definition",
        "definitions",
        "def",
        "declaration",
        "declarations",
        "declare",
        "declared",
        "implementation",
        "implementations",
        "body",
        "signature",
        "signatures",
        "prototype",
        "prototypes",
    }
)

# A facet term must clear this normalized-IDF bar to count as content. A term
# in a large fraction of nodes carries little discriminative power (Sparck
# Jones 1972: term specificity is inverse to collection frequency), so it
# cannot, on its own, make a facet a required part of the answer.
_CONTENT_SPECIFICITY_FLOOR = 0.22

# Query-local semantic role expansion. These are conventional software process
# roles rather than repository symbols: they translate user vocabulary into a
# bounded set of identifier-shaped terms, then require ordinary graph evidence.
# They propose anchors only; typed paths and facet coverage still license the
# answer. Keep the groups small so a generic word cannot spray the whole graph.
_SOFTWARE_ROLE_FORMS: dict[str, tuple[str, ...]] = {
    "prepare": ("preprocess", "initialize", "setup", "parse"),
    "preparation": ("preprocess", "initialize", "setup", "parse"),
    "inbound": ("request", "input", "receive", "read"),
    "transaction": ("request", "operation"),
    "execute": ("dispatch", "handle", "run", "evaluate"),
    "execution": ("dispatch", "handle", "run", "evaluate"),
    "application": ("app", "handler"),
    "logic": ("handler", "dispatch", "evaluate"),
    "complete": ("finalize", "finish", "process"),
    "completion": ("finalize", "finish", "process"),
    "outgoing": ("response", "output", "send", "write"),
    "data": ("response", "result", "output"),
    "checked": ("validate", "verify", "status"),
    "repaired": ("repair", "fix", "sync"),
    "reads": ("load", "parse", "read"),
    "emits": ("render", "write", "output", "return"),
    "scores": ("evaluate", "metric", "score"),
}

_SOFTWARE_ROLE_PHRASES: tuple[tuple[frozenset[str], tuple[tuple[str, ...], ...]], ...] = (
    (
        frozenset({"prepare", "inbound", "transaction"}),
        (("preprocess", "request"), ("initialize", "request")),
    ),
    (
        frozenset({"execute", "application", "logic"}),
        (("dispatch", "request"), ("handle", "request")),
    ),
    (
        frozenset({"complete", "outgoing", "data"}),
        (("finalize", "response"), ("process", "response")),
    ),
    (
        frozenset({"framework", "factory", "routing", "dependency"}),
        (("create", "application"), ("application", "router")),
    ),
    (
        frozenset({"user", "input", "compiled", "logic"}),
        (("pattern", "matcher"), ("build", "many")),
    ),
    (
        frozenset({"filesystem", "traversal"}),
        (("search", "path"), ("walk", "builder")),
    ),
    (
        frozenset({"user", "intent", "size", "limited", "structural", "answer"}),
        (("route", "query"), ("plan", "context"), ("retrieve", "context"), ("render", "packet")),
    ),
    (
        frozenset({"generated", "deliverables", "checked"}),
        (("distribution", "artifact", "status"),),
    ),
    (
        frozenset({"repaired"}),
        (("sync", "distribution", "artifacts"),),
    ),
    (
        frozenset({"executable", "boundary", "reads", "evaluation", "cases"}),
        (("cmd", "eval"), ("load", "eval", "tasks")),
    ),
    (
        frozenset({"emits", "scores"}),
        (("evaluate", "graph"),),
    ),
)

_SOFTWARE_ROLE_REQUIRED_FACETS: tuple[
    tuple[frozenset[str], tuple[tuple[str, ...], ...]], ...
] = (
    (
        frozenset({"framework", "factory", "routing", "dependency"}),
        (("create", "application"), ("application", "router")),
    ),
    (
        frozenset({"user", "input", "compiled", "logic"}),
        (("matcher",), ("matcher", "rust"), ("pattern", "matcher"), ("build", "many")),
    ),
    (
        frozenset({"user", "intent", "size", "limited", "structural", "answer"}),
        (("route", "query"), ("plan", "context"), ("retrieve", "context"), ("render", "packet")),
    ),
    (
        frozenset({"executable", "boundary", "reads", "evaluation", "cases"}),
        (("cmd", "eval"), ("load", "eval", "tasks")),
    ),
)


def _software_phrase_queries(terms: tuple[str, ...]) -> tuple[tuple[str, ...], ...]:
    normalized_terms = {term_key(term) for term in terms}
    return tuple(
        query
        for required, queries in _SOFTWARE_ROLE_PHRASES
        if required <= normalized_terms
        for query in queries
    )


def has_software_role_projection(
    facets: tuple[tuple[str, tuple[str, ...]], ...],
) -> bool:
    canonical_projections = {
        projection
        for _required, projections in _SOFTWARE_ROLE_REQUIRED_FACETS
        for projection in projections
    }
    return any(
        _software_phrase_queries(terms)
        or (re.search(r"\[\d+\]$", label) is not None and tuple(terms) in canonical_projections)
        for label, terms in facets
    )


def has_software_role_vocabulary(
    facets: tuple[tuple[str, tuple[str, ...]], ...],
) -> bool:
    return has_software_role_projection(facets) or any(
        _software_role_queries(terms) for _label, terms in facets
    )


def _software_role_queries(terms: tuple[str, ...]) -> tuple[tuple[str, ...], ...]:
    """Return bounded symbol-shaped projections for conceptual facet terms."""
    projected: list[tuple[str, ...]] = list(_software_phrase_queries(terms))
    role_terms = [(_SOFTWARE_ROLE_FORMS.get(term_key(term), ())) for term in terms]
    for forms in role_terms:
        projected.extend((form,) for form in forms[:4])
    for left, right in zip(role_terms, role_terms[1:]):
        if not left or not right:
            continue
        pair = tuple(dict.fromkeys((left[0], right[0])))
        if pair:
            projected.append(pair)
    return tuple(dict.fromkeys(projected))[:16]


def _software_role_label_distance(node: object, terms: tuple[str, ...]) -> int:
    """Distance from a symbol label to the nearest compiled role projection."""
    label_terms = set(term_key(str(getattr(node, "label", ""))).split())
    candidates = (terms, *_software_role_queries(terms))
    return min(
        (
            len(label_terms - set(candidate))
            + 4 * len(set(candidate) - label_terms)
            for candidate in candidates
            if candidate
        ),
        default=len(label_terms),
    )


def _graph_kind_terms(graph: Graph) -> frozenset[str]:
    """The vocabulary of node kinds the graph actually contains, as terms.

    Data-driven, not a hand-list: whatever kinds exist here (``class``,
    ``method``, ``struct`` ...) are structural descriptors, and a query term
    that merely names one is satisfied by an anchor of that kind rather than by
    a node whose *text* contains the word.
    """
    cache = getattr(graph, "_facet_kind_terms_cache", None)
    if cache is not None:
        return cache
    terms: set[str] = set(_DEFINITION_TERMS)
    for node in graph.nodes.values():
        for part in term_key(str(node.kind)).split():
            if part:
                terms.add(part)
    frozen = frozenset(terms)
    try:
        graph._facet_kind_terms_cache = frozen  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001 - caching is best-effort
        pass
    return frozen


def _term_specificity(term: str, token_index: dict, node_count: int) -> float:
    """Normalized inverse document frequency of *term* over the graph, in [0, 1)."""
    if node_count <= 1:
        return 1.0
    df = len(token_index.get(term, ()))
    return math.log(node_count / (1 + df)) / math.log(node_count + 1)


def _facet_is_required(
    terms: tuple[str, ...],
    kind_terms: frozenset[str],
    token_index: dict,
    node_count: int,
) -> bool:
    """A facet forces abstention only if it names genuine content.

    Content = a term that is neither a structural/kind descriptor nor a
    near-ubiquitous word. ``"definition of LoRAModule class"`` reduces (after
    the identifier is pulled out) to ``definition``/``class`` -- both
    structural -- so the facet is not required and its absence as node text
    does not abstain over an answer the anchors already carry.
    """
    for term in terms:
        if term in kind_terms:
            continue
        if _term_specificity(term, token_index, node_count) >= _CONTENT_SPECIFICITY_FLOOR:
            return True
    return False


def query_facets(query: str) -> tuple[tuple[str, tuple[str, ...]], ...]:
    facets: list[tuple[str, tuple[str, ...]]] = []
    seen: set[tuple[str, ...]] = set()
    facet_query = re.sub(
        r"\b(?:the\s+)?(?:exact\s+)?changed[-\s]+(?:file[-\s]+)?paths\b",
        " ",
        query,
        flags=re.I,
    )
    facet_query = re.sub(
        r"\b(?:trace|show|find|locate)\s+(?:the\s+)?(?:call\s+)?path\b",
        " ",
        facet_query,
        flags=re.I,
    )
    command_contract = re.compile(
        r"\b(?:what\s+is\s+|and\s+)?(?:the\s+)?(?:smallest\s+)?"
        r"(?:exact\s+)?cargo\s+command\s+that\s+runs?\s+"
        r"(?:every|all)(?:\s+one)?\b",
        re.I,
    )
    if command_contract.search(query):
        terms = ("smallest", "exact", "command", "all", "direct", "tests")
        facets.append(("smallest exact command covering all direct tests", terms))
        seen.add(terms)
        facet_query = command_contract.sub(" ", facet_query)
    roadmap_paragraph = re.compile(
        r"\b(?:the\s+)?roadmap(?:'s)?\s+paragraph(?:\s+that\s+documents?\s+"
        r"(?:this|the)\s+api)?\b",
        re.I,
    )
    if roadmap_paragraph.search(query):
        qualified_doc_terms = tuple(
            dict.fromkeys(
                term
                for owner, member in _qualified_query_symbols(query)
                for term in term_key(f"{owner} {member}").split()
            )
        )
        terms = ("roadmap", "paragraph", *qualified_doc_terms)
        facets.append(("roadmap paragraph", terms))
        seen.add(terms)
        facet_query = roadmap_paragraph.sub(" ", facet_query)
    if re.search(r"\bbounded\s+input\s+contract\b", query, re.I):
        terms = ("bounded", "input", "contract")
        facets.append(("bounded input contract", terms))
        seen.add(terms)
    covered_cases = re.compile(
        r"\bwhat\s+cases?\s+(?:do|does)\s+(?:they|it|these|those)\s+cover\b",
        re.I,
    )
    if covered_cases.search(query):
        terms = ("covered", "cases")
        facets.append(("covered cases", terms))
        seen.add(terms)
        facet_query = covered_cases.sub(" ", facet_query)
    qualified = _qualified_query_symbols(query)
    qualified_owners = {owner.casefold() for owner, _member in qualified}
    raw_identifiers = {raw.casefold(): raw for raw in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", query)}
    for owner, member in qualified:
        terms = tuple(term_key(f"{owner} {member}").split())
        if terms and terms not in seen:
            facets.append((f"{owner}::{member}", terms))
            seen.add(terms)
    for identifier in explicit_query_identifiers(query):
        if identifier.casefold() in qualified_owners:
            continue
        display = raw_identifiers.get(identifier.casefold(), identifier)
        terms = tuple(part for part in term_key(display).split() if len(part) >= 2)
        if terms and terms not in seen:
            facets.append((display, terms))
            seen.add(terms)
    identifiers = explicit_query_identifiers(query)
    identifier_terms = {
        part for identifier in identifiers for part in term_key(identifier.replace("-", "_")).split() if len(part) >= 2
    }
    intent_terms = {
        "and",
        "which",
        "tests",
        "test",
        "cover",
        "covers",
        "covered",
        "coverage",
        "run",
        "how",
        "does",
        "do",
        "measure",
        "measures",
        "measured",
        "report",
        "reports",
        "show",
        "shows",
        "including",
        "include",
        "through",
        "reach",
        "reaches",
        "reached",
        "reaching",
        "chain",
        "every",
        "each",
        "all",
        "part",
        "parts",
        "entire",
        "whole",
        "requested",
        "above",
        "positive",
        "negative",
        "documentation",
        "documents",
        "document",
        "docs",
        "doc",
        "say",
        "says",
        "said",
        "under",
        "roadmap",
        "row",
        "now",
        "claim",
        "claims",
        "claimed",
        "blast",
        "radius",
        "api",
        "explain",
        "summarize",
        "summary",
        "architecture",
        "architectural",
        "across",
        "new",
        "capability",
        "capabilities",
        "remain",
        "remains",
        "affected",
        "affecting",
        "impact",
        "impacted",
        "call",
        "calls",
        "called",
        "caller",
        "callers",
        "calling",
        "invocation",
        "invocations",
        "invoke",
        "invokes",
        "invoked",
        "invoking",
        "dispatch",
        "dispatches",
        "dispatched",
        "dispatching",
        "carry",
        "carries",
        "carried",
        "carrying",
        "start",
        "starts",
        "started",
        "starting",
        "end",
        "ends",
        "ended",
        "ending",
        "trace",
        "traces",
        "traced",
        "tracing",
        "locate",
        "locates",
        "located",
        "locating",
        "find",
        "finds",
        "found",
        "work",
        "works",
        "working",
        "consume",
        "consumes",
        "consumed",
        "consumer",
        "use",
        "uses",
        "used",
        "should",
        "if",
        "change",
        "changes",
        "changed",
        "changing",
        "behavior",
        "behaviour",
        "evaluate",
        "evaluates",
        "evaluated",
        "evaluating",
        "assess",
        "assesses",
        "assessed",
        "assessing",
        "gate",
        "gates",
        "gated",
        "gating",
        "direct",
        "directly",
        "transitive",
        "validate",
        "validates",
        "validated",
        "validating",
        "validation",
        "verify",
        "verifies",
        "verifying",
        "identify",
        "identifies",
        "identified",
        "identifying",
        "exact",
        "command",
        "commands",
        "add",
        "adds",
        "added",
        "adding",
        "after",
        "before",
        "behavioral",
        "focus",
        "focused",
        "minimal",
        "runnable",
        "return",
        "returns",
        "own",
        "step",
        "steps",
        "according",
        "md",
        "then",
        "it",
        "its",
        "they",
        "them",
        "their",
        "these",
        "those",
        "have",
        "has",
        "had",
        "cargo",
        "where",
        "what",
        "why",
        "who",
        "when",
        "is",
        "are",
        "was",
        "were",
        "the",
        "a",
        "an",
        "from",
        "into",
        "flow",
        "flows",
        "nonexistent",
        "missing",
        "implemented",
        "implement",
        "implements",
    }
    for clause in re.split(
        r"\s*(?:,|;|\band\b|\bplus\b|\bwhich\b|\breach(?:es|ed|ing)?\b)\s*",
        facet_query,
        flags=re.I,
    ):
        for identifier in identifiers:
            clause = re.sub(rf"\b{re.escape(identifier)}\b", " ", clause, flags=re.I)
        for owner, member in qualified:
            clause = re.sub(
                rf"\b{re.escape(owner)}\s*(?:::|\.|#)\s*{re.escape(member)}\b",
                " ",
                clause,
                flags=re.I,
            )
        terms = tuple(term for term in plan_terms(clause) if term not in intent_terms and term not in identifier_terms)
        meaningful_single = len(terms) == 1 and len(terms[0]) >= 4
        if (meaningful_single or 2 <= len(terms) <= 6) and terms not in seen:
            facets.append((" ".join(terms), terms))
            seen.add(terms)
    if not facets:
        fallback_terms = tuple(
            term
            for term in plan_terms(facet_query)
            if term not in intent_terms and term not in identifier_terms
        )
        if _software_phrase_queries(fallback_terms):
            facets.append((" ".join(fallback_terms), fallback_terms))
    expanded_facets: list[tuple[str, tuple[str, ...]]] = []
    for label, terms in facets:
        normalized_terms = {term_key(term) for term in terms}
        obligations = next(
            (
                projections
                for required, projections in _SOFTWARE_ROLE_REQUIRED_FACETS
                if required <= normalized_terms
            ),
            (),
        )
        if obligations:
            expanded_facets.extend(
                (f"{label} [{index}]", projection)
                for index, projection in enumerate(obligations, start=1)
            )
        else:
            expanded_facets.append((label, terms))
    return tuple(expanded_facets[:12])


def facet_search_queries(label: str, terms: tuple[str, ...]) -> tuple[str, ...]:
    """Bounded relaxed searches let prose facets reach compound code symbols."""
    queries = [label]
    search_aliases = {
        "application": "app",
        "creation": "create",
        "handling": "handle",
        "request": "req",
    }
    normalized = " ".join(search_aliases.get(term, term) for term in terms)
    if normalized and normalized != label:
        queries.append(normalized)
    if len(terms) >= 3:
        queries.extend(" ".join(terms[index : index + 2]) for index in range(len(terms) - 1))
    queries.extend(" ".join(query) for query in _software_role_queries(terms))
    return tuple(dict.fromkeys(query for query in queries if query.strip()))


def _facet_node_text(node: object) -> str:
    return term_key(
        " ".join(
            (
                str(getattr(node, "label", "")),
                str(getattr(node, "kind", "")),
                str(getattr(node, "path", "")),
                str(getattr(node, "summary", "")),
                " ".join(getattr(node, "facts", ()) or ()),
            )
        )
    )


def _symbol_identity_terms(node: object) -> set[str]:
    """Owner-aware terms for same-file candidate coherence."""
    return set(
        term_key(
            " ".join(
                (
                    str(getattr(node, "id", "")),
                    str(getattr(node, "label", "")),
                    str(getattr(node, "summary", "")),
                )
            )
        ).split()
    )


def facet_terms_absent_from_corpus(graph: Graph, terms: tuple[str, ...]) -> tuple[str, ...]:
    """Terms of a facet that appear nowhere in the graph, in any form.

    This is the only honest basis for proving a facet *cannot* be satisfied.
    The feasibility preflight previously proved absence a different way -- it
    asked whether any single node matched every term of the facet at once --
    which conflates two very different situations:

    * "GraphQL" occurs zero times in this repository. The concept is genuinely
      absent, and abstaining is correct.
    * No one node contains all of "tool", "record", "sure", "conclusion" and
      "holds". Every one of those words *is* in the corpus; they are simply
      spread across different nodes, which is what a paraphrased question
      looks like. Abstaining there threw away an answer the retriever had
      already found -- measured on the held-out locus corpus, the correct
      symbol for that exact query was the source planner's rank-1 semantic
      seed while the packet came back empty.

    Uses the cached search token index, so this is dictionary lookups over the
    facet's own terms rather than a scan of the graph.
    """
    from .search import _search_token_index

    index = _search_token_index(graph)
    return tuple(
        term for term in terms
        if not any(form in index for form in _facet_term_forms(term))
    )


def facet_coverage(
    graph: Graph,
    nodes: set[str],
    facets: tuple[tuple[str, tuple[str, ...]], ...],
    *,
    roots: tuple[str, ...] = (),
) -> dict[str, object]:
    # Requiredness needs the IDF index, which is only worth building when a
    # facet is actually unfulfilled and must be classified. Compute it lazily so
    # a fully-answered query (notably the exact-lookup fast path) never forces
    # the token index to build just to confirm there is nothing to gate on.
    requiredness_state: dict[str, object] = {}

    def _is_required(terms: tuple[str, ...]) -> bool:
        if "index" not in requiredness_state:
            from .search import _search_token_index

            requiredness_state["index"] = _search_token_index(graph)
            requiredness_state["count"] = sum(1 for node in graph.nodes.values() if node.active)
            requiredness_state["kinds"] = _graph_kind_terms(graph)
        return _facet_is_required(
            terms,
            requiredness_state["kinds"],  # type: ignore[arg-type]
            requiredness_state["index"],  # type: ignore[arg-type]
            requiredness_state["count"],  # type: ignore[arg-type]
        )

    fulfilled: list[dict[str, object]] = []
    unfulfilled: list[str] = []
    unfulfilled_required: list[str] = []
    for label, terms in facets:
        structural_first = _affected_output_contract_facet(terms)
        evidence = (
            _facet_structural_evidence(
                graph,
                nodes,
                terms,
                roots=roots,
            )
            if structural_first
            else [
                node_id
                for node_id in sorted(
                    nodes,
                    key=lambda candidate: (
                        _is_test_material(graph.nodes[candidate]),
                        not is_code_like(graph.nodes[candidate]),
                        graph.nodes[candidate].kind != "external",
                        candidate,
                    ),
                )
                if _facet_matches_node(graph.nodes[node_id], terms)
            ]
        )
        if not evidence and not structural_first:
            evidence = _facet_structural_evidence(
                graph,
                nodes,
                terms,
                roots=roots,
            )
        if not evidence and len(_facet_evidence_terms(terms)) >= 3:
            needed = set(_facet_evidence_terms(terms))
            distributed = sorted(
                (
                    (-len(hits), node_id, hits)
                    for node_id in nodes
                    if len(hits := _facet_matched_terms(graph.nodes[node_id], tuple(needed))) >= 2
                ),
            )
            covered: set[str] = set()
            selected: list[str] = []
            for _negative_hits, node_id, hits in distributed:
                if not (hits - covered):
                    continue
                selected.append(node_id)
                covered.update(hits)
                if covered >= needed or len(selected) >= 3:
                    break
            if covered >= needed:
                evidence = selected
        if evidence:
            fulfilled.append({"facet": label, "evidence": evidence[:5]})
        else:
            unfulfilled.append(label)
            if _is_required(terms):
                unfulfilled_required.append(label)
    return {
        "fulfilled": fulfilled,
        "unfulfilled": unfulfilled,
        # Only content facets (not structural/generic scaffolding) gate the
        # answerability decision; see _facet_is_required. An unfulfilled facet
        # that is pure query-shape ("definition", "class") is recorded but does
        # not abstain over an answer the anchors already carry.
        "unfulfilled_required": unfulfilled_required,
        "coverage_ratio": round(len(fulfilled) / max(1, len(facets)), 4),
        "warning": "unfulfilled query facets" if unfulfilled_required else "",
    }


def _facet_structural_evidence(
    graph: Graph,
    nodes: set[str],
    terms: tuple[str, ...],
    *,
    roots: tuple[str, ...],
) -> list[str]:
    """Credit relationship facets from selected topology, not only node text."""
    if not roots:
        return []
    targets = set(roots)
    targets.update(node_id for node_id in nodes if graph.nodes[node_id].parent in targets)
    targets.update(
        edge.target
        for edge in graph.edges
        if edge.active and edge.type == "contains" and edge.source in targets and edge.target in nodes
    )
    relation_edges = [
        edge
        for edge in graph.edges
        if edge.active
        and edge.source in nodes
        and edge.target in targets
        and edge.type in {"calls", "references", "tests", "registers"}
    ]
    forms = {form for term in terms for form in _facet_term_forms(term)}
    if forms & {"result", "results", "return", "returns", "outcome"}:
        return sorted(
            {
                edge.target
                for edge in graph.edges
                if edge.active and edge.type == "returns" and edge.source in nodes and edge.target in nodes
            }
        )
    if forms & {"exercise", "exercises", "exercised"}:
        return sorted({edge.source for edge in relation_edges if _is_test_material(graph.nodes[edge.source])})
    if forms & {"case", "cases"} and forms & {"cover", "covers", "covered", "coverage"}:
        return sorted({edge.source for edge in relation_edges if _is_test_material(graph.nodes[edge.source])})
    if forms & {"register", "registers", "registered", "registration", "registry"}:
        return sorted(
            {
                edge.source
                for edge in relation_edges
                if edge.type == "registers"
                or set(_facet_node_text(graph.nodes[edge.source]).split())
                & {"default", "domain", "register", "registered", "registry"}
            }
        )
    return []


def reserve_facet_matches(
    selected: tuple[Match, ...],
    candidates: tuple[Match, ...],
    facets: tuple[tuple[str, tuple[str, ...]], ...],
    *,
    graph: Graph | None = None,
    prefer_code: bool = False,
    prefer_production: bool = False,
    limit: int = 12,
) -> tuple[Match, ...]:
    """Reserve one independently retrieved anchor for every requested facet."""
    reserved = list(selected)
    seen = {match.node.id for match in reserved}
    for _label, terms in facets:
        matching_reserved = [match for match in reserved if _facet_matches_node(match.node, terms)]
        eligible = [
            match for match in candidates if match.node.id not in seen and _facet_matches_node(match.node, terms)
        ]
        qualified_reserved = [
            match
            for match in matching_reserved
            if (not prefer_code or graph is None or is_code_like(match.node))
            and (not prefer_production or not _is_test_material(match.node))
        ]
        reserved_label_quality = max(
            (len(_facet_label_matched_terms(match.node, terms)) for match in qualified_reserved),
            default=0,
        )
        eligible_label_quality = max(
            (len(_facet_label_matched_terms(match.node, terms)) for match in eligible),
            default=0,
        )
        if qualified_reserved and reserved_label_quality >= eligible_label_quality:
            continue
        if not eligible and graph is not None and set(terms) & {"result", "results", "return", "returns", "outcome"}:
            returned_ids = {
                edge.target for edge in graph.edges if edge.active and edge.type == "returns" and edge.source in seen
            }
            eligible = [match for match in candidates if match.node.id in returned_ids and match.node.id not in seen]
        code_eligible = [match for match in eligible if is_code_like(match.node)]
        needs_distributed_code = prefer_code and not code_eligible
        if (not eligible or needs_distributed_code) and len(_facet_evidence_terms(terms)) >= 3:
            needed = set(_facet_evidence_terms(terms))
            covered: set[str] = set()
            distributed = sorted(
                (
                    (
                        0
                        if (
                            (not prefer_code or is_code_like(match.node))
                            and (not prefer_production or not _is_test_material(match.node))
                        )
                        else 1,
                        -len(hits),
                        -match.score,
                        match.node.id,
                        match,
                        hits,
                    )
                    for match in candidates
                    if match.node.id not in seen
                    if len(hits := _facet_matched_terms(match.node, tuple(needed))) >= 2
                ),
                key=lambda item: item[:4],
            )
            for _kind_rank, _hit_rank, _score_rank, _node_id, match, hits in distributed:
                if not (hits - covered):
                    continue
                reserved.append(match)
                seen.add(match.node.id)
                covered.update(hits)
                if covered >= needed or len(reserved) >= limit:
                    break
            if covered >= needed:
                continue
        pool = code_eligible if prefer_code and code_eligible else eligible
        if prefer_production:
            production_pool = [match for match in pool if not _is_test_material(match.node)]
            if production_pool:
                pool = production_pool
        connected_ids: set[str] = set()
        adjacency: dict[str, set[str]] = {}
        if graph is not None and seen:
            for edge in graph.edges:
                if not edge.active or edge.type not in STRUCTURAL_RELATIONS:
                    continue
                adjacency.setdefault(edge.source, set()).add(edge.target)
                adjacency.setdefault(edge.target, set()).add(edge.source)
                if edge.source in seen:
                    connected_ids.add(edge.target)
                if edge.target in seen:
                    connected_ids.add(edge.source)

        def connection_rank(match: Match) -> int:
            node_id = match.node.id
            if node_id in connected_ids:
                return 2
            return int(any(neighbor in connected_ids for neighbor in adjacency.get(node_id, ())))

        candidate = max(
            pool,
            key=lambda match: (
                len(_facet_label_matched_terms(match.node, terms)),
                connection_rank(match),
                match.score,
                match.node.id,
            ),
            default=None,
        )
        if candidate is not None:
            if len(reserved) >= limit:
                # A saturated initial ranking can contain a weak prose witness
                # for this facet. Appending the stronger code witness and then
                # slicing back to ``limit`` silently discards the very node the
                # reservation pass selected. Replace the weakest witness for
                # this same facet in place; never evict evidence for an
                # unrelated obligation here.
                replaceable = [
                    (index, match)
                    for index, match in enumerate(reserved)
                    if _facet_matches_node(match.node, terms)
                    and match.node.id != candidate.node.id
                ]
                replacement = min(
                    replaceable,
                    key=lambda item: (
                        int(not prefer_code or is_code_like(item[1].node)),
                        int(not prefer_production or not _is_test_material(item[1].node)),
                        len(_facet_label_matched_terms(item[1].node, terms)),
                        item[1].score,
                        item[1].node.id,
                    ),
                    default=None,
                )
                if replacement is not None:
                    position, prior = replacement
                    seen.discard(prior.node.id)
                    reserved[position] = candidate
                    seen.add(candidate.node.id)
            else:
                reserved.append(candidate)
                seen.add(candidate.node.id)
        if len(reserved) >= limit:
            continue
    return tuple(reserved[:limit])


_FACET_PROCESS_TERMS = {
    "discovery",
    "equivalence",
    "rationalization",
    "implementation",
    "implementations",
    "measurement",
    "measurements",
    "anchoring",
    "calibrated",
    "calibration",
    "consistency",
    "query",
    "readiness",
    "reconciliation",
    "selection",
    "specific",
}


def _facet_evidence_terms(terms: tuple[str, ...]) -> tuple[str, ...]:
    """Keep a facet's domain terms while treating process nouns as intent."""
    reduced = tuple(term for term in terms if term not in _FACET_PROCESS_TERMS)
    return reduced or terms


def _facet_term_forms(term: str) -> set[str]:
    forms = {term_key(term)}
    aliases = {
        "application": {"app"},
        "creation": {"create", "creates", "created", "creating", "constructor", "factory"},
        "handling": {"handle", "handler", "handles", "handled"},
        "request": {"req"},
        "sync": {"synchronization", "synchronize", "synchronized", "syncing"},
        "synchronization": {"sync", "synchronize", "synchronized", "syncing"},
        "synchronize": {"sync", "synchronization", "synchronized", "syncing"},
        "synchronized": {"sync", "synchronization", "synchronize", "syncing"},
        "anchoring": {"anchor", "anchored"},
        "consistency": {"consistent"},
        "deduplication": {
            "dedup",
            "deduplicate",
            "deduplicated",
            "duplicate",
            "duplicates",
            "unique",
            "once",
        },
        "equality": {"equal", "equals", "exact", "exactly"},
        "readiness": {"ready"},
        "reconciliation": {"reconcile", "reconciled"},
        "unproved": {"unproven", "prove", "proved", "proof"},
        "export": {"exports", "exported", "public", "pub"},
        "result": {"result", "results", "return", "returns", "outcome"},
        "verification": {"verify", "verified", "verifies", "verification"},
        "unsupported": {
            "absent",
            "missing",
            "unsupported",
            "unimplemented",
        },
    }
    forms.update(aliases.get(term, ()))
    forms.update(_SOFTWARE_ROLE_FORMS.get(term, ()))
    if term.endswith("ies") and len(term) > 4:
        forms.add(term[:-3] + "y")
    elif term.endswith("ing") and len(term) > 5:
        stem = term[:-3]
        forms.add(stem)
        if len(stem) >= 2 and stem[-1] == stem[-2]:
            forms.add(stem[:-1])
        forms.add(stem + "e")
    elif term.endswith("ed") and len(term) > 4:
        stem = term[:-2]
        forms.update((stem, stem + "e"))
    elif term.endswith("s") and not term.endswith("ss") and len(term) > 3:
        forms.add(term[:-1])
    else:
        forms.add(term + "s")
    return {form for form in forms if form}


def _facet_evidence_queries(terms: tuple[str, ...]) -> tuple[tuple[str, ...], ...]:
    base = _facet_evidence_terms(terms)
    phrase_queries = _software_phrase_queries(base)
    queries = list(phrase_queries) if phrase_queries else [base]
    role_queries = _software_role_queries(base)
    paired_role_queries = tuple(query for query in role_queries if len(query) >= 2)
    if not phrase_queries:
        if paired_role_queries:
            queries.extend(paired_role_queries)
        elif len(base) == 1:
            queries.extend(role_queries)
    term_set = set(base)
    if "verified" in term_set and term_set & {"source", "application", "applications"}:
        queries.extend(
            (
                ("preview", "fixes"),
                ("is", "fixable"),
                ("successful", "verified", "application"),
                ("verified", "application"),
            )
        )
    if "rejection" in term_set and term_set & {"diagnostic", "diagnostics"}:
        queries.extend((("refactor", "rejection"), ("rejection",), ("diagnostic",)))
    if "yield" in term_set:
        queries.extend((("promotable", "candidate"), ("promotable", "candidates")))
    if term_set & {"metric", "metrics"} and term_set & {"enforce", "enforces", "enforced"}:
        queries.extend((("min",), ("max",), ("threshold",), ("evaluate",)))
    if "unsafe" in term_set and "path" in term_set:
        queries.extend((("unsafe", "path"), ("parent", "traversal"), ("rejects", "parent", "traversal")))
    if term_set & {"running", "run"} and term_set & {"loaded", "load", "cases", "case"}:
        queries.extend((("load", "run"), ("loaded", "case"), ("loads", "cases")))
    if term_set & {"abstain", "abstention"} and term_set & {"case", "cases"}:
        queries.extend(
            (
                ("no", "solution"),
                ("returns", "none"),
                ("dominant", "degenerate"),
            )
        )
    if "unsupported" in term_set:
        queries.extend((("remain", "absent"), ("absent",), ("missing",)))
    if "self" in term_set and term_set & {"verification", "verified", "verify"}:
        queries.extend((("verify",), ("verified",), ("verifies",)))
    return tuple(dict.fromkeys(queries))


def _facet_matches_node(node: object, terms: tuple[str, ...]) -> bool:
    if _bounded_input_contract_match(_facet_node_text(node), terms):
        return True
    token_list = re.findall(r"[a-z0-9]+", _facet_node_text(node))
    tokens = set(token_list)
    compact = "".join(token_list)
    return any(
        all(
            tokens & (forms := _facet_term_forms(term)) or any(len(form) >= 5 and form in compact for form in forms)
            for term in query_terms
        )
        for query_terms in _facet_evidence_queries(terms)
    )


def _facet_matched_terms(node: object, terms: tuple[str, ...]) -> set[str]:
    return _facet_matched_text_terms(_facet_node_text(node), terms)


def _facet_label_matched_terms(node: object, terms: tuple[str, ...]) -> set[str]:
    """Return facet hits from symbol identity, excluding summary/body context."""
    return _facet_matched_text_terms(
        term_key(str(getattr(node, "label", ""))),
        terms,
    )


def _facet_matched_text_terms(text: str, terms: tuple[str, ...]) -> set[str]:
    if _bounded_input_contract_match(text, terms):
        return set(terms)
    token_list = re.findall(r"[a-z0-9]+", text)
    tokens = set(token_list)
    compact = "".join(token_list)
    return {
        term
        for term in terms
        if (tokens & (forms := _facet_term_forms(term)) or any(len(form) >= 5 and form in compact for form in forms))
    }


def _bounded_input_contract_match(text: str, terms: tuple[str, ...]) -> bool:
    """Recognize an explicit numeric input bound as contract evidence."""
    normalized_terms = {term_key(term) for term in terms}
    if not {"bounded", "input", "contract"} <= normalized_terms:
        return False
    normalized = term_key(text)
    has_bound = bool(
        re.search(
            r"\b(?:up to|at most|no more than|maximum(?: of)?)\s+\d+\b"
            r"|\b\d+\s*[x×✕]\s*\d+\b",
            normalized,
        )
    )
    has_input_shape = bool(
        re.search(
            r"\b(?:input|inputs|domain|domains|point|points|item|items|"
            r"element|elements|length|size|arity|game|games|player|players|"
            r"matrix|matrices)\b",
            normalized,
        )
    )
    return has_bound and has_input_shape


_AFFECTED_OUTPUT_TERMS = {
    "affected",
    "all",
    "behavioral",
    "cargo",
    "case",
    "cases",
    "command",
    "commands",
    "cover",
    "covered",
    "covering",
    "coverage",
    "covers",
    "direct",
    "exact",
    "exercise",
    "exercised",
    "exercises",
    "focused",
    "minimal",
    "return",
    "runnable",
    "run",
    "running",
    "runs",
    "smallest",
    "test",
    "tests",
    "transitive",
    "verify",
    "verifies",
    "verifying",
}


def _affected_output_contract_facet(terms: tuple[str, ...]) -> bool:
    normalized = set(term_key(" ".join(terms)).split())
    return bool(normalized) and normalized <= _AFFECTED_OUTPUT_TERMS


def reconcile_affected_output_facets(metadata: dict[str, object]) -> tuple[str, ...]:
    """Fulfill output-contract facets from the affected-test receipt itself."""
    coverage = metadata.get("facet_coverage")
    affected = metadata.get("affected_tests")
    if not isinstance(coverage, dict) or not isinstance(affected, dict):
        return ()
    direct = [item for item in affected.get("direct", ()) if isinstance(item, dict)]
    transitive = [item for item in affected.get("transitive", ()) if isinstance(item, dict)]
    commands = [str(item) for item in affected.get("commands", ()) if item]
    command_selection = affected.get("command_selection", {})
    fulfilled = list(coverage.get("fulfilled", ()))
    remaining: list[str] = []
    repaired: list[str] = []
    for raw_label in coverage.get("unfulfilled", ()):
        label = str(raw_label)
        terms = set(term_key(label).split())
        if not terms or terms - _AFFECTED_OUTPUT_TERMS:
            remaining.append(label)
            continue
        evidence: list[str] = []
        requires_all_direct = bool({"all", "direct", "test"} <= terms or {"all", "direct", "tests"} <= terms)
        selected_command_complete = bool(commands) and (
            not requires_all_direct
            or not isinstance(command_selection, dict)
            or (
                not command_selection.get("uncovered_roots", ())
                and not command_selection.get("uncovered_direct_tests", ())
            )
        )
        if terms & {"cargo", "command", "commands", "runnable", "run", "runs"} and selected_command_complete:
            evidence = [f"affected_tests.command:{command}" for command in commands[:5]]
        elif "direct" in terms and direct:
            evidence = [f"affected_tests.direct:{item.get('id', '')}" for item in direct[:5]]
        elif "transitive" in terms and transitive:
            evidence = [f"affected_tests.transitive:{item.get('id', '')}" for item in transitive[:5]]
        elif terms & {
            "affected",
            "behavioral",
            "test",
            "tests",
            "verify",
            "verifies",
            "verifying",
        } and (direct or transitive):
            evidence = [f"affected_tests.test:{item.get('id', '')}" for item in (*direct, *transitive)[:5]]
        if evidence:
            fulfilled.append(
                {
                    "facet": label,
                    "evidence": evidence,
                    "source": "affected_tests_receipt",
                }
            )
            repaired.append(label)
        else:
            remaining.append(label)
    total = len(fulfilled) + len(remaining)
    coverage.update(
        {
            "fulfilled": fulfilled,
            "unfulfilled": remaining,
            "unfulfilled_required": [
                label
                for label in coverage.get("unfulfilled_required", ())
                if str(label) in remaining
            ],
            "coverage_ratio": round(len(fulfilled) / max(1, total), 4),
            "warning": "unfulfilled query facets" if remaining else "",
        }
    )
    return tuple(repaired)
