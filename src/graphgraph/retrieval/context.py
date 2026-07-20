"""Context retrieval orchestrator.

The heavy lifting lives in the sibling modules (scoping, facets, expansion,
anchors, ...); this module keeps the top-level ``retrieve_context`` flow and
re-exports the split helpers so ``graphgraph.retrieval.context`` remains the
stable import surface.
"""

# ruff: noqa: F401

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from ..concepts.doccode import doc_code_bias, is_code_like
from ..graph.core import Graph
from ..graph.ontology import provenance_confidence
from ..planning import plan_context
from ..planning.budgets import doc_intensity_score, explicit_query_identifiers, plan_terms
from .anchors import (
    _TOPIC_LOCAL_ROADMAP_ROW,
    AnchorScoreShape,
    _adaptive_anchor_limit,
    _anchor_score_shape,
    _document_content_key,
    _is_file_like_anchor,
    _is_high_confidence_exact_anchor,
    _is_targeted_symbol_anchor,
    _node_stem,
    _unrequested_identifier_sibling,
    apply_shape_budget,
    exact_token_symbol_anchor_matches,
    infer_dominant_scope,
    interpretation_concept_anchor_matches,
    preferred_path_anchor_matches,
    qualified_symbol_anchor_matches,
    select_anchor_matches,
    select_enumerated_doc_roots,
    select_topic_local_doc_roots,
)
from .document_status import (
    _ABSENT_DOCUMENT_INTENT,
    _DOCUMENT_STATUS_CELL,
    _DOCUMENT_STATUS_MARKER,
    _DOCUMENT_TABLE_ROW,
    _PARTIAL_DOCUMENT_INTENT,
    _constrain_document_status_packet,
    _document_status_facet,
    _document_status_row,
    _requested_document_statuses,
    document_status_anchor_matches,
)
from .expansion import (
    PATH_BEAM_WIDTH,
    PATH_PREFERRED_RELATION_BONUS,
    _beam_best_path,
    _edge_shape_rank,
    _expand_affected_tests,
    _expand_blast_radius,
    _path_edge_strength,
    _reserve_blast_support_evidence,
    _reserve_paths_between_starts,
    _reserve_relation_family_evidence,
    _start_evidence_priority,
    adaptive_weak_edge_limit,
    expand_context,
    include_reserved_structural_edges,
    prune_doc_concept_noise,
    reserve_start_evidence,
    reserve_structural_neighbors,
    reserve_test_support_files,
    shape_edge_budget,
)
from .facets import (
    _AFFECTED_OUTPUT_TERMS,
    _FACET_PROCESS_TERMS,
    _affected_output_contract_facet,
    _bounded_input_contract_match,
    _facet_evidence_queries,
    _facet_evidence_terms,
    _facet_label_matched_terms,
    _facet_matched_terms,
    _facet_matched_text_terms,
    _facet_matches_node,
    _facet_node_text,
    _facet_structural_evidence,
    _facet_term_forms,
    _symbol_identity_terms,
    facet_coverage,
    facet_search_queries,
    query_facets,
    reconcile_affected_output_facets,
    reserve_facet_matches,
)
from .models import Match, RetrievalResult
from .pruning import (
    _context_node_score,
    _is_structural_node,
    _least_valuable_context_node,
    _least_valuable_doc_node,
    _loose_term_hits,
    _node_edge_scores,
)
from .quality import (
    cap_inferred_scope_crossings,
    packet_quality_metadata,
    query_topology_trust,
)
from .reservations import (
    _reverse_lookup_relations,
    prune_concrete_contract_siblings,
    prune_unexplained_structural_nodes,
    reserve_ordered_doc_siblings,
    reserve_query_named_siblings,
    reserve_reverse_contract_starts,
    reserve_reverse_direct_neighbors,
    reverse_lookup_truncation,
)
from .scoping import (
    _AFFECTED_ANCHOR_INTENT,
    _ENUMERATED_DOC_QUERY,
    _FLOW_ORIENTATION_QUERY,
    _NOISE_PATTERNS,
    _ORDERED_DOC_QUERY,
    _TEST_EVIDENCE_QUERY,
    NON_STRUCTURAL_KINDS,
    SESSION_CONTEXT_QUERY_CLASSES,
    STRUCTURAL_QUERY_CLASSES,
    STRUCTURAL_RELATIONS,
    _explicit_document_paths,
    _is_test_node,
    _is_test_path,
    _package_scope,
    _path_in_scopes,
    _qualified_query_symbols,
    _source_declares_rust_test,
    sanitize_query,
    structural_anchor_query,
)
from .search import search_nodes
from .test_recommendations import (
    _cargo_inline_rust_module_command,
    _cargo_inline_rust_test_target,
    _cargo_source_context,
    _cargo_test_target,
    _rust_test_module_calls_symbol,
    _test_command,
    affected_test_recommendations,
    changed_path_test_recommendations,
    reconcile_retrieval_receipt,
    reconcile_semantic_retrieval_receipt,
    reserve_affected_test_evidence,
)


def retrieve_context(
    graph: Graph,
    query: str,
    query_class: str,
    hops: int,
    anchor_limit: int | None = None,
    max_nodes: int | None = None,
    scopes: tuple[str, ...] = (),
    scope_mode: str = "strict",
    seed_ids: tuple[str, ...] = (),
    anchor_paths: tuple[str, ...] = (),
) -> RetrievalResult:
    if scope_mode not in {"strict", "expand"}:
        raise ValueError(f"unknown scope mode: {scope_mode}")
    query = sanitize_query(query)
    requested_statuses = (
        _requested_document_statuses(query)
        if query_class == "doc_summary"
        else set()
    )
    status_constrained = bool(requested_statuses)
    if query_class == "doc_summary" and not scopes:
        explicit_doc_paths = _explicit_document_paths(graph, query)
        if len(explicit_doc_paths) == 1:
            scopes = explicit_doc_paths
            scope_mode = "strict"
    identifiers = explicit_query_identifiers(query)
    qualified_matches = (
        qualified_symbol_anchor_matches(graph, query, scopes=scopes)
        if query_class == "direct_lookup" and not anchor_paths
        else ()
    )
    facet_aware = query_class in {
        "affected_tests", "blast_radius", "multi_hop_path", "negative_query", "doc_summary",
    } or (
        query_class in {"direct_lookup", "reverse_lookup"} and bool(identifiers)
    )
    facets = query_facets(query) if facet_aware else ()
    if status_constrained:
        # The typed status-row matcher owns this predicate. Leaving the same
        # words in generic lexical facets creates a contradictory second gate:
        # a literal `[ ]` row can prove absence without repeating the word
        # "absent" in its body.
        facets = tuple(
            facet
            for facet in facets
            if not _document_status_facet(facet[1], requested_statuses)
        )
    anchor_query = structural_anchor_query(query, query_class)
    path_matches = preferred_path_anchor_matches(
        graph,
        query,
        query_class,
        anchor_paths,
        facets,
    )
    concept_matches = (
        interpretation_concept_anchor_matches(graph, query, scopes=scopes)
        if query_class in {"direct_lookup", "reverse_lookup"}
        else ()
    )
    exact_matches: tuple[Match, ...] = ()
    if not path_matches:
        exact_matches = concept_matches or qualified_matches
        if not exact_matches and (
            query_class == "direct_lookup"
            or (query_class == "reverse_lookup" and len(identifiers) == 1)
        ):
            exact_matches = search_nodes(
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
    plan = plan_context(query_class, query, anchor_limit=anchor_limit, max_nodes=max_nodes, hops=hops)
    if max_nodes is None and exact_match is None:
        plan = apply_shape_budget(graph, plan, query)
    candidate_limit = max(plan.anchor_limit, plan.anchor_limit * 3 if query_class in STRUCTURAL_QUERY_CLASSES else plan.anchor_limit)
    if facets:
        candidate_limit = max(candidate_limit, min(36, len(facets) * 3))
    if query_class == "direct_lookup" and len(plan_terms(query)) == 1:
        candidate_limit = max(candidate_limit, 24)
    matches = (
        path_matches
        or ((exact_match,) if exact_match is not None else ())
        or search_nodes(
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
        exact_token_symbol_anchor_matches(
            graph,
            anchor_query,
            scopes=scopes,
        )
        if query_class == "affected_tests" and not path_matches
        else ()
    )
    if token_symbol_matches:
        token_symbol_ids = {match.node.id for match in token_symbol_matches}
        matches = (*token_symbol_matches, *(
            match for match in matches if match.node.id not in token_symbol_ids
        ))
    status_matches: tuple[Match, ...] = ()
    if query_class == "doc_summary":
        status_matches = document_status_anchor_matches(
            graph,
            query,
            scopes=scopes,
        )
        if status_matches and not path_matches:
            status_ids = {match.node.id for match in status_matches}
            matches = (*status_matches, *(
                match for match in matches if match.node.id not in status_ids
            ))
    source_matches = tuple(
        Match(
            graph.nodes[node_id],
            max(20.0, matches[0].score + 1.0 if matches else 20.0),
            ("source_planner",),
        )
        for node_id in dict.fromkeys(seed_ids)
        if node_id in graph.nodes and graph.nodes[node_id].active
    )
    priority_matches = (*path_matches, *source_matches)
    if priority_matches:
        priority_ids = {match.node.id for match in priority_matches}
        matches = priority_matches + tuple(
            match for match in matches if match.node.id not in priority_ids
        )
    exact_anchor_fast_path = (
        len(matches) == 1 and "exact_fast_path" in matches[0].reasons
    )
    if facets and not path_matches and not exact_anchor_fast_path:
        # A single bag-of-words search for a conjunction is dominated by nodes
        # that repeat the query's common subsystem terms. Search each facet
        # independently, then merge its best evidence into the candidate pool
        # before anchor selection. This is bounded by the twelve-facet parser
        # cap and preserves the original whole-query ranking at the front.
        merged = list(matches)
        seen_match_ids = {match.node.id for match in merged}
        for facet_label, facet_terms in facets:
            for facet_query in facet_search_queries(facet_label, facet_terms):
                facet_matches = search_nodes(
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
        matches = tuple(merged)
    if status_constrained:
        # Status is an evidence type, not a ranking preference. Facet searches,
        # source seeds, and path roots may orient an ordinary document query,
        # but they cannot substitute legend prose or a different status class
        # for a requested literal capability row.
        matches = status_matches
    inferred_scope = "" if scopes else infer_dominant_scope(matches, query)
    if inferred_scope and not facets:
        coherent = tuple(match for match in matches if _path_in_scopes(match.node.path, (inferred_scope,)))
        if coherent:
            matches = coherent
    if (
        query_class in {"blast_radius", "subsystem_summary"}
        and max_nodes is None
        and not any(_is_targeted_symbol_anchor(match) for match in matches[:3])
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
        _adaptive_anchor_limit(matches, plan, query)
        if query_class in STRUCTURAL_QUERY_CLASSES or query_class in {"direct_lookup", "subsystem_summary"}
        else plan.anchor_limit
    )
    if (
        query_class == "affected_tests"
        and identifiers
        and len(plan_terms(anchor_query)) > len(identifiers)
    ):
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
    if token_symbol_matches:
        effective_anchor_limit = max(
            effective_anchor_limit,
            min(12, len(token_symbol_matches)),
        )
    if path_matches and not status_constrained:
        effective_anchor_limit = max(effective_anchor_limit, min(12, len(path_matches)))
    if facets and not path_matches and not exact_anchor_fast_path:
        effective_anchor_limit = max(effective_anchor_limit, min(12, len(facets)))
    selected_matches = select_anchor_matches(
        matches,
        effective_anchor_limit,
        query_class,
        doc_intensity >= 0.35,
        query=query,
        graph=graph,
        dominant_scope=inferred_scope,
    )
    selected_matches = select_topic_local_doc_roots(
        selected_matches,
        matches,
        query=query,
        query_class=query_class,
    )
    if facets and not path_matches and not exact_anchor_fast_path:
        anchor_facets = (
            tuple(
                facet for facet in facets
                if not _affected_output_contract_facet(facet[1])
            )
            if query_class == "affected_tests"
            else facets
        )
        selected_matches = reserve_facet_matches(
            selected_matches,
            matches,
            anchor_facets,
            graph=graph,
            prefer_code=query_class == "multi_hop_path",
        )
    if path_matches:
        # Exact edited paths are an explicit ANCHOR instruction. They define
        # roots; ordinary lexical matches may still enter through structural
        # expansion, but cannot become competing roots.
        selected_matches = path_matches[:effective_anchor_limit]
    selected_matches = select_enumerated_doc_roots(
        selected_matches,
        matches,
        query=query,
        query_class=query_class,
    )
    if query_class == "negative_query" and facets:
        selected_ids = {match.node.id for match in selected_matches}
        anchor_coverage = facet_coverage(
            graph,
            {
                node_id
                for node_id in selected_ids
                if is_code_like(graph.nodes[node_id])
            },
            facets,
        )
        if not anchor_coverage["fulfilled"]:
            mention_coverage = facet_coverage(graph, selected_ids, facets)
            return RetrievalResult(
                starts=(),
                matches=selected_matches,
                nodes=set(),
                edges=[],
                metadata={
                    "facet_coverage": anchor_coverage,
                    "mention_coverage": mention_coverage,
                    "answerability": {
                        "status": "unanswerable",
                        "abstained": True,
                        "reason": "no code or structural graph evidence covers the requested entity facets",
                    },
                    "plan_reason": plan.reason,
                    "planner_version": plan.planner_version,
                },
            )
    starts_list = list(match.node.id for match in selected_matches)
    facet_roots = tuple(starts_list[:12])
    if query_class == "reverse_lookup":
        starts_list = list(reserve_reverse_contract_starts(graph, tuple(starts_list), query=query))

    # Discover git-modified files (active session context / Ephemeral Session Layer).
    # Dirty files are useful ambient context for exploratory summaries and
    # activation, but appending them as traversal starts changes the semantics
    # of exact lookup/path/impact queries. Search personalization already gives
    # modified files a ranking boost without forcing unrelated nodes into those
    # result subgraphs.
    if query_class in SESSION_CONTEXT_QUERY_CLASSES:
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
                node_id for node_id in selected
                if _path_in_scopes(graph.nodes[node_id].path, (inferred_scope,))
            )
        starts_list.extend(node_id for node_id in selected if node_id not in starts_list)

    starts = tuple(starts_list[:12])
    if not starts:
        if status_constrained:
            status_labels = [
                "absent" if status == "" else "partial"
                for status in sorted(requested_statuses)
            ]
            status_warning = (
                "no literal "
                + "/".join(status_labels)
                + " capability rows were found in the requested roadmap documents"
            )
            effective_scope = scopes[0] if len(scopes) == 1 else inferred_scope
            metadata = packet_quality_metadata(
                graph,
                set(),
                [],
                (),
                effective_scope,
                query_class=query_class,
            )
            metadata.update({
                "scope": list(scopes),
                "scope_mode": "auto_expand" if inferred_scope and not scopes else scope_mode,
                "inferred_scope": inferred_scope,
                "anchor_strategy": "literal_document_status",
                "plan_reason": plan.reason,
                "planner_version": plan.planner_version,
                "node_budget": plan.node_budget,
                "anchor_limit": effective_anchor_limit,
                "anchor_paths": [],
                "document_status_evidence": {
                    "requested": status_labels,
                    "capability_rows": 0,
                    "evidence": [],
                    "packet_status_rows": [],
                    "conflicting_status_rows": [],
                    "packet_constrained": True,
                    "warning": status_warning,
                },
                "answerability": {
                    "status": "incomplete",
                    "abstained": True,
                    "reason": status_warning,
                },
            })
            return RetrievalResult(
                starts=(),
                matches=(),
                nodes=set(),
                edges=[],
                metadata=metadata,
            )
        return RetrievalResult(
            starts=(),
            matches=matches,
            nodes=set(),
            edges=[],
            metadata={
                "answerability": {
                    "status": "unanswerable",
                    "abstained": True,
                    "reason": "no matching graph anchors",
                },
            },
        )

    if query_class == "spreading_activation":
        from .activation import ActivationStateCache, spreading_activation
        cache = ActivationStateCache()
        prev_state = cache.load()
        nodes, edges = spreading_activation(
            graph,
            list(starts),
            max_nodes=plan.node_budget or 120,
            previous_activation=prev_state,
        )
    else:
        expansion_scopes = scopes if scope_mode == "strict" else ()
        nodes, edges = expand_context(graph, starts, plan, scopes=expansion_scopes, query_terms=plan_terms(query))
        nodes, edges = reserve_query_named_siblings(graph, nodes, edges, starts, query, plan)
        nodes, edges = reserve_ordered_doc_siblings(graph, nodes, edges, starts, query, plan)
        if query_class == "reverse_lookup":
            nodes, edges = reserve_reverse_direct_neighbors(
                graph,
                nodes,
                edges,
                starts,
                query,
                plan,
                scopes=expansion_scopes,
            )
            nodes, edges = prune_concrete_contract_siblings(
                graph,
                nodes,
                edges,
                roots=facet_roots,
            )
        if query_class == "affected_tests":
            nodes, edges = reserve_affected_test_evidence(graph, nodes, edges, starts, plan)
    if (
        query_class == "direct_lookup"
        and exact_anchor_fast_path
        and set(plan_terms(query)) & {"call", "calls", "called", "calling"}
    ):
        # An exact `Type::method` call question is a direct adjacency read.
        # Containment and documentation expansion can only add siblings/noise;
        # derive the slice from the graph's outgoing call table regardless of
        # a generously supplied node budget.
        start_set = set(starts)
        edges = [
            edge
            for edge in graph.edges
            if edge.active
            and edge.source in start_set
            and edge.type == "calls"
            and edge.confidence * provenance_confidence(edge.provenance) >= plan.min_confidence
        ]
        nodes = set(starts) | {edge.target for edge in edges}
    if query_class in STRUCTURAL_QUERY_CLASSES:
        nodes, edges = prune_unexplained_structural_nodes(nodes, edges, starts)
    if inferred_scope:
        nodes, edges = cap_inferred_scope_crossings(graph, nodes, edges, inferred_scope, protected=starts)
    if scopes and scope_mode == "strict":
        nodes = {node_id for node_id in nodes if _path_in_scopes(graph.nodes[node_id].path, scopes)}
        edges = [edge for edge in edges if edge.source in nodes and edge.target in nodes]
    if status_constrained:
        nodes, edges = _constrain_document_status_packet(
            graph,
            nodes,
            edges,
            {match.node.id for match in status_matches},
        )
    effective_scope = scopes[0] if len(scopes) == 1 else inferred_scope
    metadata = packet_quality_metadata(
        graph,
        nodes,
        edges,
        starts,
        effective_scope,
        query_class=query_class,
    )
    if (
        query_class == "doc_summary"
        and metadata["quality"]["grounded_doc_nodes"] == 0
    ):
        metadata["quality"]["document_warning"] = (
            "doc_summary selected zero grounded document body nodes"
        )
    metadata.update({
        "scope": list(scopes),
        "scope_mode": "auto_expand" if inferred_scope and not scopes else scope_mode,
        "inferred_scope": inferred_scope,
        "anchor_strategy": (
            "exact_fast_path"
            if selected_matches
            and all("exact_fast_path" in match.reasons for match in selected_matches)
            else "ranked"
        ),
        "plan_reason": plan.reason,
        "planner_version": plan.planner_version,
        "node_budget": plan.node_budget,
        "anchor_limit": effective_anchor_limit,
        "anchor_paths": [
            {
                "path": path,
                "role": (
                    "test_evidence_candidate"
                    if query_class == "affected_tests" and _is_test_path(path)
                    else "primary_root"
                    if Path(path).suffix.casefold()
                    in {".md", ".mdx", ".rst", ".txt", ".html", ".htm"}
                    else "file_fallback"
                    if any(
                        match.node.path.replace("\\", "/").strip("/")
                        == path.replace("\\", "/").strip("/")
                        and "file_fallback" in match.reasons
                        for match in selected_matches
                    )
                    else "primary_root"
                ),
                "anchors": [
                    match.node.id
                    for match in selected_matches
                    if match.node.path.replace("\\", "/").strip("/")
                    == path.replace("\\", "/").strip("/")
                ],
            }
            for path in dict.fromkeys(anchor_paths)
        ],
    })
    if facets:
        coverage = facet_coverage(graph, nodes, facets, roots=facet_roots or starts)
        metadata["facet_coverage"] = coverage
        structural_coverage = None
        if query_class in {"multi_hop_path", "direct_lookup", "reverse_lookup"}:
            structural_coverage = facet_coverage(
                graph,
                {
                    node_id
                    for node_id in nodes
                    if is_code_like(graph.nodes[node_id])
                },
                facets,
                roots=facet_roots or starts,
            )
            metadata["structural_facet_coverage"] = structural_coverage
        incomplete = bool(coverage["unfulfilled"]) or bool(
            structural_coverage and structural_coverage["unfulfilled"]
        )
        metadata["answerability"] = {
            "status": "incomplete" if incomplete else "answerable",
            "abstained": False,
            "reason": (
                "one or more requested facets have no code or structural evidence"
                if structural_coverage and structural_coverage["unfulfilled"]
                else coverage["warning"]
            ),
        }
    else:
        metadata["answerability"] = {
            "status": "answerable",
            "abstained": False,
            "reason": "",
        }
    document_warning = str(metadata["quality"].get("document_warning", ""))
    if query_class == "doc_summary" and document_warning:
        metadata["answerability"] = {
            "status": "incomplete",
            "abstained": True,
            "reason": document_warning,
        }
    if query_class == "doc_summary" and requested_statuses:
        status_labels = [
            "absent" if status == "" else "partial"
            for status in sorted(requested_statuses)
        ]
        status_warning = (
            ""
            if status_matches
            else (
                "no literal "
                + "/".join(status_labels)
                + " capability rows were found in the requested roadmap documents"
            )
        )
        packet_status_rows: list[str] = []
        conflicting_status_rows: list[str] = []
        for node_id in sorted(nodes):
            node = graph.nodes[node_id]
            row = _document_status_row(" ".join(str(fact) for fact in node.facts))
            if row is None:
                continue
            if row[0] in requested_statuses:
                packet_status_rows.append(node_id)
            else:
                conflicting_status_rows.append(node_id)
        metadata["document_status_evidence"] = {
            "requested": status_labels,
            "capability_rows": len(status_matches),
            "evidence": [match.node.id for match in status_matches],
            "packet_status_rows": packet_status_rows,
            "conflicting_status_rows": conflicting_status_rows,
            "packet_constrained": True,
            "warning": status_warning,
        }
        if status_warning or conflicting_status_rows:
            metadata["answerability"] = {
                "status": "incomplete",
                "abstained": True,
                "reason": status_warning or "document packet contains conflicting status rows",
            }
    if query_class == "reverse_lookup":
        truncation = reverse_lookup_truncation(
            graph,
            nodes,
            edges,
            starts,
            query,
            plan,
            scopes=scopes if scope_mode == "strict" else (),
        )
        metadata["truncation"] = truncation
        if truncation["truncated"]:
            metadata["answerability"] = {
                "status": "incomplete",
                "abstained": True,
                "reason": (
                    f"node budget omitted {truncation['omitted_direct_neighbors']} "
                    "known direct reverse neighbor(s)"
                ),
            }
    changed_path_tests = changed_path_test_recommendations(graph, anchor_paths)
    if query_class == "affected_tests":
        cover_all_direct_tests = any(
            {"all", "direct", "tests"} <= set(terms)
            for _label, terms in facets
        )
        affected = affected_test_recommendations(
            graph,
            starts,
            nodes,
            cover_all_direct_tests=cover_all_direct_tests,
        )
        if changed_path_tests["commands"]:
            selected_entries = list(affected["command_provenance"])
            changed_entries = list(changed_path_tests["command_provenance"])

            def entry_test_ids(entry: dict[str, object]) -> set[str]:
                return {
                    str(test.get("id", ""))
                    for test in entry.get("tests", [])
                    if test.get("id")
                }

            superseded = {
                str(selected["command"])
                for selected in selected_entries
                if any(
                    str(selected["command"]) != str(changed["command"])
                    and entry_test_ids(selected)
                    and entry_test_ids(selected) <= entry_test_ids(changed)
                    and len(entry_test_ids(changed)) > len(entry_test_ids(selected))
                    for changed in changed_entries
                )
            }
            kept_selected = [
                entry
                for entry in selected_entries
                if str(entry["command"]) not in superseded
            ]
            kept_changed = [
                changed
                for changed in changed_entries
                if not any(
                    str(selected["command"]) != str(changed["command"])
                    and entry_test_ids(selected) == entry_test_ids(changed)
                    and entry_test_ids(changed)
                    for selected in kept_selected
                )
            ]
            merged_entries = [*kept_selected, *kept_changed]
            affected["commands"] = list(dict.fromkeys(
                str(entry["command"])
                for entry in merged_entries
            ))
            affected["commands_by_role"]["changed_path_regression"] = [
                str(entry["command"])
                for entry in kept_changed
            ]
            direct_ids = {str(item["id"]) for item in affected["direct"]}
            transitive_ids = {str(item["id"]) for item in affected["transitive"]}
            affected["commands_by_role"]["direct_behavior_or_contract"] = list(dict.fromkeys(
                str(entry["command"])
                for entry in merged_entries
                if entry_test_ids(entry) & direct_ids
            ))
            affected["commands_by_role"]["transitive_regression"] = list(dict.fromkeys(
                str(entry["command"])
                for entry in merged_entries
                if entry_test_ids(entry) & transitive_ids
            ))
            affected["command_provenance"] = merged_entries
            affected["command_selection"]["selected_count"] = len(affected["commands"])
            affected["command_selection"]["superseded_commands"] = sorted(superseded)
            affected["changed_path_candidates"] = changed_path_tests["candidates"]
        metadata["affected_tests"] = affected
        metadata["hybrid_intents"] = ["multi_hop_path", "affected_tests"]
    elif _TEST_EVIDENCE_QUERY.search(query):
        compound_test_roots = tuple(
            start
            for start in starts
            if start in graph.nodes
            and graph.nodes[start].kind not in NON_STRUCTURAL_KINDS
            and graph.nodes[start].kind
            in {"function", "method", "class", "struct", "trait", "enum", "field"}
            and not _is_test_node(graph.nodes[start])
        )[:1]
        if compound_test_roots:
            affected = affected_test_recommendations(
                graph,
                compound_test_roots,
                nodes,
            )
            metadata["affected_tests"] = affected
            metadata["hybrid_intents"] = [query_class, "affected_tests"]
    elif changed_path_tests["commands"]:
        metadata["affected_tests"] = {
            "direct": [],
            "transitive": [],
            "commands": changed_path_tests["commands"],
            "commands_by_role": {
                "direct_behavior_or_contract": [],
                "transitive_regression": [],
                "changed_path_regression": changed_path_tests["commands"],
            },
            "command_provenance": changed_path_tests["command_provenance"],
            "changed_path_candidates": changed_path_tests["candidates"],
            "omitted_transitive": 0,
        }
    if query_class == "doc_summary" and not any(
        node.kind in {"section", "paragraph"} for node in graph.nodes.values()
    ):
        # Documentation query against a graph that carries no grounded doc-body
        # nodes -- it was built without document extraction, so retrieval can
        # only return file pointers. Say so with the fix, rather than silently
        # degrading (a graph built with docs=true grounds paragraph prose fine).
        metadata["document_extraction"] = {
            "grounded": False,
            "hint": (
                "This graph has no document section/paragraph nodes, so documentation "
                "queries return only file pointers. Rebuild with document extraction for "
                "grounded prose: build_graph with docs=true (or `graphgraph scan --docs`)."
            ),
        }
    return RetrievalResult(starts=starts, matches=selected_matches, nodes=nodes, edges=edges, metadata=metadata)
