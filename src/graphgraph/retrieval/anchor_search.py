"""Private Anchor/search execution phase for context retrieval."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace

import graphgraph.retrieval.anchors as anchors
import graphgraph.retrieval.document_status as document_status
import graphgraph.retrieval.facets as facet_stage
import graphgraph.retrieval.obligations as obligations
import graphgraph.retrieval.reservations as reservations
import graphgraph.retrieval.scoping as scoping
import graphgraph.retrieval.search as search

from ..concepts.doccode import doc_code_bias, is_code_like
from ..graph.core import Graph
from ..planning import ContextPlan
from ..planning.budgets import doc_intensity_score, plan_terms
from .models import Match, RetrievalResult
from .phase_support import (
    _FACET_ANCHOR_RESERVATION,
    _empty_anchor_result,
    _negative_query_abstain,
    _seat_facet_reservations,
)
from .request_feasibility import _FeasibleRequest


@dataclass(frozen=True, slots=True)
class _AnchorSelection:
    request: _FeasibleRequest
    plan: ContextPlan
    path_matches: tuple[Match, ...]
    selected_matches: tuple[Match, ...]
    status_matches: tuple[Match, ...]
    inferred_scope: str
    exact_anchor_fast_path: bool
    effective_anchor_limit: int
    starts: tuple[str, ...]
    facet_roots: tuple[str, ...]


def _execute_anchor_search(
    graph: Graph,
    request: _FeasibleRequest,
    *,
    max_nodes: int | None,
    seed_ids: tuple[str, ...],
) -> _AnchorSelection | RetrievalResult:
    query = request.query
    query_class = request.query_class
    scopes = request.scopes
    scope_mode = request.scope_mode
    anchor_paths = request.anchor_paths
    requested_statuses = request.requested_statuses
    status_constrained = request.status_constrained
    identifiers = request.identifiers
    qualified_matches = request.qualified_matches
    facets = request.facets
    plan = request.plan
    anchor_query = scoping.structural_anchor_query(query, query_class)
    path_matches = anchors.preferred_path_anchor_matches(
        graph,
        query,
        query_class,
        anchor_paths,
        facets,
    )
    concept_matches = (
        anchors.interpretation_concept_anchor_matches(graph, query, scopes=scopes)
        if query_class in {"direct_lookup", "reverse_lookup"}
        else ()
    )
    exact_matches: tuple[Match, ...] = ()
    if not path_matches:
        exact_matches = concept_matches or qualified_matches
        if not exact_matches and (
            query_class == "direct_lookup" or (query_class == "reverse_lookup" and len(identifiers) == 1)
        ):
            exact_matches = search.search_nodes(
                graph,
                identifiers[0] if query_class == "reverse_lookup" else anchor_query,
                limit=1,
                scopes=scopes,
                exact_fast_path=True,
                exact_only=True,
            )
    exact_match = exact_matches[0] if exact_matches else None
    doc_intensity = 0.0
    if exact_match is None:
        doc_intensity = doc_intensity_score(query_class, query)
        graph_bias = doc_code_bias(graph)
        doc_intensity *= 0.75 + graph_bias * 0.5
    if max_nodes is None and exact_match is None:
        plan = anchors.apply_shape_budget(graph, plan, query)
    candidate_limit = max(
        plan.anchor_limit,
        plan.anchor_limit * 3 if query_class in scoping.STRUCTURAL_QUERY_CLASSES else plan.anchor_limit,
    )
    if facets:
        candidate_limit = max(candidate_limit, min(36, len(facets) * 3))
    if query_class == "direct_lookup" and len(plan_terms(query)) == 1:
        candidate_limit = max(candidate_limit, 24)
    matches = (
        path_matches
        or exact_matches
        or search.search_nodes(
            graph,
            anchor_query,
            limit=max(candidate_limit, 1),
            doc_intensity=doc_intensity,
            personalize=True,
            scopes=scopes,
            exact_fast_path=query_class == "direct_lookup",
        )
    )
    token_symbol_matches = (
        anchors.exact_token_symbol_anchor_matches(
            graph,
            anchor_query,
            scopes=scopes,
        )
        if query_class == "affected_tests" and not path_matches
        else ()
    )
    implementation_matches = (
        anchors.implementation_symbol_anchor_matches(
            graph,
            facets,
            scopes=scopes,
        )
        if query_class == "direct_lookup"
        and not exact_matches
        and re.search(r"\bimplement(?:ed|ation|ations)?\b", query, re.I)
        else ()
    )
    if implementation_matches:
        implementation_ids = {match.node.id for match in implementation_matches}
        matches = implementation_matches + tuple(match for match in matches if match.node.id not in implementation_ids)
    if token_symbol_matches:
        token_symbol_ids = {match.node.id for match in token_symbol_matches}
        matches = (*token_symbol_matches, *(match for match in matches if match.node.id not in token_symbol_ids))
    status_matches: tuple[Match, ...] = ()
    if query_class == "doc_summary":
        status_matches = document_status.document_status_anchor_matches(
            graph,
            query,
            scopes=scopes,
        )
        if status_matches and not path_matches:
            status_ids = {match.node.id for match in status_matches}
            matches = (*status_matches, *(match for match in matches if match.node.id not in status_ids))
    source_matches = tuple(
        Match(
            graph.nodes[node_id],
            max(20.0, matches[0].score + 1.0 if matches else 20.0),
            ("source_planner",),
        )
        for node_id in dict.fromkeys(seed_ids)
        if node_id in graph.nodes and graph.nodes[node_id].active
    )
    if facet_stage.has_software_role_projection(facets):
        # Auxiliary semantic similarity is proposal evidence. When a bounded
        # role compiler has already produced independently checkable graph
        # obligations, high-scoring semantic seeds must not become mandatory
        # roots and evict those terminals under the anchor/node budgets.
        source_matches = ()
    priority_matches = (*path_matches, *source_matches, *implementation_matches)
    if priority_matches:
        priority_ids = {match.node.id for match in priority_matches}
        matches = priority_matches + tuple(match for match in matches if match.node.id not in priority_ids)
    exact_anchor_fast_path = bool(matches) and all("exact_fast_path" in match.reasons for match in matches)
    semantic_terminal_matches: tuple[Match, ...] = ()
    if facets and not path_matches and not exact_anchor_fast_path:
        # A single bag-of-words search for a conjunction is dominated by nodes
        # that repeat the query's common subsystem terms. Search each facet
        # independently, then merge its best evidence into the candidate pool
        # before anchor selection. This is bounded by the twelve-facet parser
        # cap and preserves the original whole-query ranking at the front.
        merged = list(matches)
        seen_match_ids = {match.node.id for match in merged}
        merged_positions = {match.node.id: index for index, match in enumerate(merged)}
        semantic_terminals: list[Match] = []
        semantic_terminal_facets = 0
        semantic_candidate_groups: list[tuple[str, ...]] = []
        for facet_label, facet_terms in facets:
            for facet_query in facet_stage.facet_search_queries(facet_label, facet_terms):
                facet_matches = search.search_nodes(
                    graph,
                    facet_query,
                    limit=12,
                    doc_intensity=0.0,
                    personalize=True,
                    scopes=scopes,
                )
                for match in facet_matches:
                    if match.node.id not in seen_match_ids:
                        merged.append(match)
                        seen_match_ids.add(match.node.id)
                        merged_positions[match.node.id] = len(merged) - 1
            semantic_candidates = (
                [
                    node
                    for node in sorted(
                        (
                            node
                            for node in graph.nodes.values()
                            if node.active
                            and is_code_like(node)
                            and (query_class != "subsystem_summary" or not scoping._is_test_material(node))
                            and (not scopes or scoping._path_in_scopes(node.path, scopes))
                            and facet_stage._facet_matches_node(node, facet_terms)
                        ),
                        key=lambda node: (
                            scoping._is_test_material(node),
                            facet_stage._software_role_label_distance(node, facet_terms),
                            node.kind not in {"method", "function", "external"},
                            len(node.path),
                            node.id,
                        ),
                    )[:8]
                ]
                if query_class in {"multi_hop_path", "subsystem_summary"}
                and facet_stage.has_software_role_projection(((facet_label, facet_terms),))
                else []
            )
            if semantic_candidates:
                semantic_terminal_facets += 1
                semantic_candidate_groups.append(tuple(node.id for node in semantic_candidates))
                semantic_terminals.extend(
                    Match(node, 1000.0, ("semantic_structural_terminal",)) for node in semantic_candidates
                )
            for node in semantic_candidates:
                if node.id not in seen_match_ids:
                    merged.append(Match(node, 1000.0, ("semantic_structural_facet",)))
                    seen_match_ids.add(node.id)
                    merged_positions[node.id] = len(merged) - 1
                else:
                    position = merged_positions[node.id]
                    prior = merged[position]
                    merged[position] = Match(
                        node,
                        max(1000.0, prior.score),
                        tuple(dict.fromkeys((*prior.reasons, "semantic_structural_facet"))),
                    )
        matches = tuple(merged)
        if semantic_terminal_facets == len(facets):
            if query_class == "subsystem_summary":
                # A summary role is an evidence obligation, not a request for
                # the cheapest graph connector. A test that calls both the
                # inspection and repair functions can be a smaller connector,
                # but it must not replace either production role. Round-robin
                # preserves every role before retaining bounded ambiguity
                # within a role (for example finalization plus response
                # processing in a lifecycle).
                semantic_terminals = []
                max_group_size = max(map(len, semantic_candidate_groups), default=0)
                for candidate_index in range(max_group_size):
                    for group in semantic_candidate_groups:
                        if candidate_index >= len(group):
                            continue
                        semantic_terminals.append(
                            Match(
                                graph.nodes[group[candidate_index]],
                                1000.0,
                                ("semantic_role_terminal",),
                            )
                        )
                        if len(semantic_terminals) >= 12:
                            break
                    if len(semantic_terminals) >= 12:
                        break
            else:
                global_connector = obligations.minimal_evidence_connector(
                    {node_id for node_id, node in graph.nodes.items() if node.active},
                    graph.edges,
                    tuple(semantic_candidate_groups),
                )
                if global_connector is not None and len(global_connector[0]) <= 12:
                    connector_nodes, _connector_edges, _connector_receipt = global_connector
                    semantic_terminals = [
                        Match(graph.nodes[node_id], 1000.0, ("semantic_global_connector",))
                        for node_id in sorted(connector_nodes)
                    ]
                else:
                    # Preserve at least one candidate from every obligation before
                    # spending spare root slots on ambiguity within a facet. A flat
                    # concatenation let a generic first facet (for example
                    # ``matcher``) consume all twelve roots and silently dropped
                    # exact later obligations such as ``search_path``.
                    balanced_terminals: list[Match] = []
                    max_group_size = max(map(len, semantic_candidate_groups), default=0)
                    for candidate_index in range(max_group_size):
                        for group in semantic_candidate_groups:
                            if candidate_index >= len(group):
                                continue
                            balanced_terminals.append(
                                Match(
                                    graph.nodes[group[candidate_index]],
                                    1000.0,
                                    ("semantic_balanced_terminal",),
                                )
                            )
                            if len(balanced_terminals) >= 12:
                                break
                        if len(balanced_terminals) >= 12:
                            break
                    semantic_terminals = balanced_terminals
        if semantic_terminal_facets == len(facets):
            semantic_terminal_matches = tuple({match.node.id: match for match in semantic_terminals}.values())
    if status_constrained:
        # Status is an evidence type, not a ranking preference. Facet searches,
        # source seeds, and path roots may orient an ordinary document query,
        # but they cannot substitute legend prose or a different status class
        # for a requested literal capability row.
        matches = status_matches
    inferred_scope = "" if scopes else anchors.infer_dominant_scope(matches, query)
    if query_class == "subsystem_summary" and facet_stage.has_software_role_projection(facets):
        # Lexically disjoint conceptual queries often have their strongest raw
        # overlap in tests or prose. Treating that incidental winner as the
        # repository scope removes the production role projections before
        # their graph evidence can be compared.
        inferred_scope = ""
    if inferred_scope and not facets:
        coherent = tuple(match for match in matches if scoping._path_in_scopes(match.node.path, (inferred_scope,)))
        if coherent:
            matches = coherent
    if (
        query_class in {"blast_radius", "subsystem_summary"}
        and max_nodes is None
        and not any(anchors._is_targeted_symbol_anchor(match) for match in matches[:3])
        and plan.node_budget is not None
    ):
        # Keep exact-symbol impact analysis recall-first, but ambiguous prose
        # should be an orientation packet. Otherwise several loose anchors can
        # each contribute a two-hop neighborhood and consume ~100 nodes.
        plan = replace(
            plan,
            node_budget=min(plan.node_budget, 48),
            reason=f"{plan.reason}; ambiguous broad-query cap",
            planner_version=f"{plan.planner_version}_broad_query_cap",
        )
    effective_anchor_limit = (
        anchors._adaptive_anchor_limit(matches, plan, query)
        if query_class in scoping.STRUCTURAL_QUERY_CLASSES or query_class in {"direct_lookup", "subsystem_summary"}
        else plan.anchor_limit
    )
    if query_class == "affected_tests" and identifiers and len(plan_terms(anchor_query)) > len(identifiers):
        # "Type method changes" names a member in prose even when the method
        # itself is not code-shaped. Keep the exact type and its matching
        # member as roots; the intent-sanitized query prevents affected/change
        # homonyms from consuming this second slot.
        effective_anchor_limit = max(2, effective_anchor_limit)
    if source_matches:
        effective_anchor_limit = max(
            effective_anchor_limit,
            min(12, len(source_matches) + plan.anchor_limit),
        )
    if implementation_matches:
        effective_anchor_limit = max(
            effective_anchor_limit,
            min(12, len(implementation_matches)),
        )
    if token_symbol_matches:
        effective_anchor_limit = max(
            effective_anchor_limit,
            min(12, len(token_symbol_matches)),
        )
    if path_matches and not status_constrained:
        effective_anchor_limit = max(effective_anchor_limit, min(12, len(path_matches)))
    if facets and not path_matches and not exact_anchor_fast_path:
        effective_anchor_limit = max(effective_anchor_limit, min(12, len(facets)))
    selected_matches = anchors.select_anchor_matches(
        matches,
        effective_anchor_limit,
        query_class,
        doc_intensity >= 0.35,
        query=query,
        graph=graph,
        dominant_scope=inferred_scope,
    )
    selected_matches = anchors.select_topic_local_doc_roots(
        selected_matches,
        matches,
        query=query,
        query_class=query_class,
    )
    if facets and not path_matches and not exact_anchor_fast_path:
        anchor_facets = (
            tuple(facet for facet in facets if not facet_stage._affected_output_contract_facet(facet[1]))
            if query_class == "affected_tests"
            else facets
        )
        # Source seeds can widen the ranked anchor budget all the way to the
        # packet's start cap, and reservation only ever *appends* -- so when the
        # cap is already full the facet stage silently reserves nothing and the
        # packet loses the one anchor retrieved specifically to answer a facet.
        # Give reservation room to run, then let what it found displace the
        # weakest ranked anchors rather than be truncated away: an anchor
        # retrieved for a requested facet outranks one that merely scored well
        # on the whole query.
        ranked_matches = selected_matches
        selected_matches = facet_stage.reserve_facet_matches(
            selected_matches,
            matches,
            anchor_facets,
            graph=graph,
            prefer_code=query_class in {"multi_hop_path", "subsystem_summary"},
            prefer_production=query_class == "subsystem_summary",
            limit=12 + min(len(anchor_facets), _FACET_ANCHOR_RESERVATION),
        )
        selected_matches = _seat_facet_reservations(
            ranked_matches,
            selected_matches,
            limit=12,
        )
        if query_class == "subsystem_summary" and any(
            is_code_like(match.node) and not scoping._is_test_material(match.node) for match in selected_matches
        ):
            selected_matches = tuple(match for match in selected_matches if not scoping._is_test_material(match.node))
    if path_matches:
        # Exact edited paths are an explicit ANCHOR instruction. They define
        # roots; ordinary lexical matches may still enter through structural
        # expansion, but cannot become competing roots.
        selected_matches = path_matches[:effective_anchor_limit]
    selected_matches = anchors.select_enumerated_doc_roots(
        selected_matches,
        matches,
        query=query,
        query_class=query_class,
    )
    if query_class in {"multi_hop_path", "subsystem_summary"} and semantic_terminal_matches:
        # All prose facets compiled to structural terminals. They are the path
        # constraints (or bounded process-role witnesses); unrelated
        # whole-query lexical hits must not become additional mandatory roots
        # and defeat the connector or role-evidence optimizer.
        selected_matches = semantic_terminal_matches[:12]
    negative_abstain = _negative_query_abstain(
        graph,
        query_class=query_class,
        facets=facets,
        selected_matches=selected_matches,
        plan=plan,
    )
    if negative_abstain is not None:
        return negative_abstain
    starts_list = list(match.node.id for match in selected_matches)
    facet_roots = tuple(starts_list[:12])
    if query_class == "reverse_lookup":
        starts_list = list(reservations.reserve_reverse_contract_starts(graph, tuple(starts_list), query=query))

    # Discover git-modified files (active session context / Ephemeral Session Layer).
    # Dirty files are useful ambient context for exploratory summaries and
    # activation, but appending them as traversal starts changes the semantics
    # of exact lookup/path/impact queries. Search personalization already gives
    # modified files a ranking boost without forcing unrelated nodes into those
    # result subgraphs.
    if query_class in scoping.SESSION_CONTEXT_QUERY_CLASSES:
        from .git_utils import get_git_modified_files, select_modified_context_nodes

        modified_paths = get_git_modified_files()
        selected = select_modified_context_nodes(
            graph,
            modified_paths,
            query,
            exclude=tuple(starts_list),
        )
        if inferred_scope:
            selected = tuple(
                node_id for node_id in selected if scoping._path_in_scopes(graph.nodes[node_id].path, (inferred_scope,))
            )
        starts_list.extend(node_id for node_id in selected if node_id not in starts_list)

    starts = tuple(starts_list[:12])
    if not starts:
        return _empty_anchor_result(
            graph,
            query=query,
            query_class=query_class,
            scopes=scopes,
            scope_mode=scope_mode,
            inferred_scope=inferred_scope,
            status_constrained=status_constrained,
            requested_statuses=requested_statuses,
            plan=plan,
            effective_anchor_limit=effective_anchor_limit,
            matches=matches,
            selected_matches=selected_matches,
        )

    return _AnchorSelection(
        request=request,
        plan=plan,
        path_matches=path_matches,
        selected_matches=selected_matches,
        status_matches=status_matches,
        inferred_scope=inferred_scope,
        exact_anchor_fast_path=exact_anchor_fast_path,
        effective_anchor_limit=effective_anchor_limit,
        starts=starts,
        facet_roots=facet_roots,
    )
