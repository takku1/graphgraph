"""Private request-feasibility phase for context retrieval."""

from __future__ import annotations

import re
from dataclasses import dataclass

import graphgraph.retrieval.anchors as anchors
import graphgraph.retrieval.document_status as document_status
import graphgraph.retrieval.facets as facet_stage
import graphgraph.retrieval.scoping as scoping
import graphgraph.retrieval.search as search

from ..concepts import INTERPRETATION_CONCEPT_IDS
from ..concepts.doccode import is_code_like
from ..graph.core import Graph
from ..planning import ContextPlan, plan_context
from ..planning.budgets import explicit_query_identifiers
from .models import Match, RetrievalResult
from .phase_support import _semantic_novelty_result


@dataclass(frozen=True, slots=True)
class _FeasibleRequest:
    query: str
    query_class: str
    scopes: tuple[str, ...]
    scope_mode: str
    anchor_paths: tuple[str, ...]
    requested_statuses: frozenset[str]
    status_constrained: bool
    identifiers: tuple[str, ...]
    qualified_matches: tuple[Match, ...]
    facets: tuple[tuple[str, tuple[str, ...]], ...]
    plan: ContextPlan


def _request_feasibility(
    graph: Graph,
    query: str,
    query_class: str,
    hops: int,
    anchor_limit: int | None,
    max_nodes: int | None,
    scopes: tuple[str, ...],
    scope_mode: str,
    anchor_paths: tuple[str, ...],
) -> _FeasibleRequest | RetrievalResult:
    if scope_mode not in {"strict", "expand"}:
        raise ValueError(f"unknown scope mode: {scope_mode}")
    query = scoping.sanitize_query(query)
    requested_statuses = document_status._requested_document_statuses(query) if query_class == "doc_summary" else set()
    status_constrained = bool(requested_statuses)
    if query_class == "doc_summary" and not scopes:
        explicit_doc_paths = scoping._explicit_document_paths(graph, query)
        if len(explicit_doc_paths) == 1:
            scopes = explicit_doc_paths
            scope_mode = "strict"
    identifiers = explicit_query_identifiers(query)
    qualified_matches = (
        anchors.qualified_symbol_anchor_matches(graph, query, scopes=scopes)
        if query_class in {"direct_lookup", "multi_hop_path"} and not anchor_paths
        else ()
    )
    subsystem_facets = facet_stage.query_facets(query) if query_class == "subsystem_summary" else ()
    facet_aware = query_class in {
        "affected_tests",
        "blast_radius",
        "multi_hop_path",
        "negative_query",
        "doc_summary",
        "reverse_lookup",
        "direct_lookup",
    } or (
        query_class == "subsystem_summary"
        and (
            bool(re.search(r"\barchitectur(?:e|al)\b", query, re.I))
            or facet_stage.has_software_role_vocabulary(subsystem_facets)
        )
    )
    facets = (
        subsystem_facets
        if query_class == "subsystem_summary" and facet_aware
        else (facet_stage.query_facets(query) if facet_aware else ())
    )
    if status_constrained:
        # The typed status-row matcher owns this predicate. Leaving the same
        # words in generic lexical facets creates a contradictory second gate:
        # a literal `[ ]` row can prove absence without repeating the word
        # "absent" in its body.
        facets = tuple(
            facet for facet in facets if not document_status._document_status_facet(facet[1], requested_statuses)
        )
    plan = plan_context(
        query_class,
        query,
        anchor_limit=anchor_limit,
        max_nodes=max_nodes,
        hops=hops,
    )
    preflight_exact_matches = qualified_matches
    if query_class == "direct_lookup" and identifiers and not preflight_exact_matches:
        exact_candidates = search.search_nodes(
            graph,
            identifiers[0],
            limit=1,
            scopes=scopes,
            exact_fast_path=True,
            exact_only=True,
        )
        preflight_exact_matches = tuple(
            match
            for match in exact_candidates
            if query.strip().casefold() == identifiers[0].casefold()
            or any(reason.startswith(("label_exact", "path_exact", "qualified")) for reason in match.reasons)
        )
    # Explicit `anchor_paths` are a caller directive, not a guess: the caller
    # has already located the evidence. The feasibility preflight exists to
    # avoid ranked searches for entities that do not exist anywhere, so letting
    # it veto a pinned path turns a precise request into an empty answer.
    if (
        query_class in {"direct_lookup", "reverse_lookup"}
        and facets
        and not preflight_exact_matches
        and not anchor_paths
    ):
        # A collection-wide evidence-facet feasibility pass is cheaper than eight
        # ranked searches for a query whose required entities do not exist.
        # It uses the same matcher and IDF requiredness contract as final
        # answerability, so this is a proof of complete miss, not a score
        # threshold. Mixed queries (at least one fulfilled facet) continue.
        preflight_scopes = scopes if scope_mode == "strict" else ()
        evidence_nodes = {
            node_id
            for node_id, node in graph.nodes.items()
            if node.active
            and (is_code_like(node) or node_id in INTERPRETATION_CONCEPT_IDS)
            and (not preflight_scopes or scoping._path_in_scopes(node.path, preflight_scopes))
        }
        global_coverage = facet_stage.facet_coverage(graph, evidence_nodes, facets)
        if query_class == "direct_lookup":
            empty_coverage = facet_stage.facet_coverage(graph, set(), facets)
            required_labels = set(empty_coverage.get("unfulfilled_required", ()))
            individually_fulfilled = {
                label
                for label, terms in facets
                if any(facet_stage._facet_matches_node(graph.nodes[node_id], terms) for node_id in evidence_nodes)
            }
            missing_required = required_labels - individually_fulfilled
            # A facet that no code node satisfies has three quite different
            # explanations, and the preflight used to treat all of them as the
            # same total miss:
            #
            # 1. A term occurs nowhere in the corpus at all ("GraphQL"). The
            #    concept is genuinely absent and abstaining is correct.
            # 2. A *documentation* node satisfies the whole facet but no code
            #    does. Documented-but-unbuilt: an `incomplete` answer, which
            #    the mention pass below already reports.
            # 3. Every term exists somewhere, but scattered across nodes so no
            #    single one carries them all. That is simply what a
            #    paraphrased question looks like, and it is not evidence of
            #    anything. Measured on the held-out locus corpus, the correct
            #    symbol for such a query was the source planner's rank-1
            #    semantic seed while this branch returned an empty packet.
            #
            # Only 1 and 2 justify abstaining. 3 must fall through so ranked
            # and semantic retrieval get their turn.
            mention_nodes = {
                node_id for node_id, node in graph.nodes.items() if node.active and node_id not in evidence_nodes
            }
            mention_fulfilled = frozenset(
                label
                for label, terms in facets
                if label in missing_required
                and any(facet_stage._facet_matches_node(graph.nodes[node_id], terms) for node_id in mention_nodes)
            )
            provably_absent = {
                label
                for label, terms in facets
                if label in missing_required and facet_stage.facet_terms_absent_from_corpus(graph, terms)
            }
            if provably_absent or mention_fulfilled:
                return _semantic_novelty_result(
                    graph,
                    query_class=query_class,
                    coverage=empty_coverage,
                    structural_coverage=empty_coverage,
                    selected_matches=(),
                    plan=plan,
                    scopes=scopes,
                    scope_mode=scope_mode,
                    inferred_scope="",
                    effective_anchor_limit=plan.anchor_limit,
                    anchor_paths=anchor_paths,
                    mention_fulfilled=mention_fulfilled,
                )
        provably_absent = any(
            facet_stage.facet_terms_absent_from_corpus(graph, terms)
            for label, terms in facets
            if label in set(global_coverage.get("unfulfilled_required", ()))
        )
        if not global_coverage.get("fulfilled") and global_coverage.get("unfulfilled_required") and provably_absent:
            return _semantic_novelty_result(
                graph,
                query_class=query_class,
                coverage=global_coverage,
                structural_coverage=global_coverage,
                selected_matches=(),
                plan=plan,
                scopes=scopes,
                scope_mode=scope_mode,
                inferred_scope="",
                effective_anchor_limit=plan.anchor_limit,
                anchor_paths=anchor_paths,
            )
    return _FeasibleRequest(
        query=query,
        query_class=query_class,
        scopes=scopes,
        scope_mode=scope_mode,
        anchor_paths=anchor_paths,
        requested_statuses=frozenset(requested_statuses),
        status_constrained=status_constrained,
        identifiers=identifiers,
        qualified_matches=qualified_matches,
        facets=facets,
        plan=plan,
    )
