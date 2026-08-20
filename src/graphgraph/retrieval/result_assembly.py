"""Private retrieval-result assembly phase."""

from __future__ import annotations

from pathlib import Path

import graphgraph.retrieval.anchors as anchors
import graphgraph.retrieval.document_status as document_status
import graphgraph.retrieval.expansion as expansion
import graphgraph.retrieval.facets as facet_stage
import graphgraph.retrieval.obligations as obligations
import graphgraph.retrieval.quality as quality
import graphgraph.retrieval.reservations as reservations
import graphgraph.retrieval.scoping as scoping
import graphgraph.retrieval.subsystems as subsystems
import graphgraph.retrieval.test_recommendations as test_recommendations

from ..concepts.doccode import is_code_like
from ..graph.core import Graph
from ..graph.ontology import provenance_confidence
from ..planning.budgets import plan_terms
from .anchor_search import _AnchorSelection
from .models import RetrievalResult
from .phase_support import (
    _affected_tests_metadata,
    _anchor_paths_metadata,
    _document_status_answerability,
    _exact_overload_disambiguation,
    _named_project_coverage,
    _truncated_requested_documents,
)


def _expand_result_graph(
    graph: Graph,
    selection: _AnchorSelection,
    activation_state_path: Path | None,
):
    request = selection.request
    query = request.query
    query_class = request.query_class
    scopes = request.scopes
    scope_mode = request.scope_mode
    status_constrained = request.status_constrained
    plan = selection.plan
    status_matches = selection.status_matches
    inferred_scope = selection.inferred_scope
    exact_anchor_fast_path = selection.exact_anchor_fast_path
    starts = selection.starts
    facet_roots = selection.facet_roots
    if query_class == "spreading_activation":
        from .activation import ActivationStateCache, spreading_activation

        # Callers that know where the graph lives pass its state path; without
        # one this falls back to the CWD-relative default, so a query against
        # an explicit foreign --graph would otherwise read and write the
        # *calling* project's turn history.
        cache = ActivationStateCache(activation_state_path)
        prev_state = cache.load()
        nodes, edges = spreading_activation(
            graph,
            list(starts),
            max_nodes=plan.node_budget or 120,
            previous_activation=prev_state,
            cache=cache,
        )
    else:
        expansion_scopes = scopes if scope_mode == "strict" else ()
        nodes, edges = expansion.expand_context(
            graph, starts, plan, scopes=expansion_scopes, query_terms=plan_terms(query)
        )
        nodes, edges = reservations.reserve_query_named_siblings(graph, nodes, edges, starts, query, plan)
        nodes, edges = reservations.reserve_ordered_doc_siblings(graph, nodes, edges, starts, query, plan)
        if query_class == "reverse_lookup":
            nodes, edges = reservations.reserve_reverse_direct_neighbors(
                graph,
                nodes,
                edges,
                starts,
                query,
                plan,
                scopes=expansion_scopes,
            )
            nodes, edges = reservations.prune_concrete_contract_siblings(
                graph,
                nodes,
                edges,
                roots=facet_roots,
            )
        if query_class == "affected_tests":
            nodes, edges = test_recommendations.reserve_affected_test_evidence(graph, nodes, edges, starts, plan)
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
    if query_class in scoping.STRUCTURAL_QUERY_CLASSES:
        nodes, edges = reservations.prune_unexplained_structural_nodes(nodes, edges, starts)
    nodes, edges, constraint_selection, path_connector_failed = _constrain_multi_hop_path(
        graph, selection, nodes, edges
    )
    if inferred_scope and not (query_class == "multi_hop_path" and exact_anchor_fast_path):
        # A post-hoc top-k scope cap recomputes boundary scores over the current
        # packet, so a newly admitted connector can evict a node returned at a
        # smaller budget. Exact path packets already have precise endpoints and
        # a hard node budget; preserve their universal expansion prefix instead
        # of applying a second, non-monotone optimizer.
        nodes, edges = quality.cap_inferred_scope_crossings(graph, nodes, edges, inferred_scope, protected=starts)
    if scopes and scope_mode == "strict":
        nodes = {node_id for node_id in nodes if scoping._path_in_scopes(graph.nodes[node_id].path, scopes)}
        edges = [edge for edge in edges if edge.source in nodes and edge.target in nodes]
    if status_constrained:
        nodes, edges = document_status._constrain_document_status_packet(
            graph,
            nodes,
            edges,
            {match.node.id for match in status_matches},
        )
    return nodes, edges, starts, constraint_selection, path_connector_failed


def _constrain_multi_hop_path(graph: Graph, selection: _AnchorSelection, nodes, edges):
    request = selection.request
    query_class = request.query_class
    facets = request.facets
    path_matches = selection.path_matches
    selected_matches = selection.selected_matches
    exact_anchor_fast_path = selection.exact_anchor_fast_path
    starts = selection.starts
    facet_roots = selection.facet_roots
    constraint_selection = None
    path_connector_failed = False
    if query_class == "multi_hop_path" and facets:
        # A prose path often yields only one exact anchor even when expansion
        # has already recovered every named endpoint. Convert facet witnesses
        # into typed terminal groups and solve for the smallest directed proof
        # instead of returning the whole two-hop neighborhood.
        path_coverage = facet_stage.facet_coverage(graph, nodes, facets, roots=facet_roots or starts)
        if not path_coverage["unfulfilled_required"]:
            evidence_groups = tuple(
                tuple(str(node_id) for node_id in item["evidence"])
                for item in path_coverage["fulfilled"]
                if item.get("evidence")
            )
            connector = obligations.minimal_evidence_connector(
                nodes,
                edges,
                (
                    *evidence_groups,
                    *(
                        (match.node.id,)
                        for match in selected_matches
                        if exact_anchor_fast_path or bool(path_matches) or anchors._is_targeted_symbol_anchor(match)
                    ),
                ),
            )
            if connector is not None:
                connector_nodes, connector_edges, constraint_selection = connector
                root_id = str(constraint_selection["root"])
                root_label = graph.nodes[root_id].label.casefold()
                lifecycle_edges = []
                if root_label.startswith(("create", "build", "make", "bootstrap")):
                    lifecycle_edges = sorted(
                        (
                            edge
                            for edge in graph.edges
                            if edge.active
                            and edge.source == root_id
                            and edge.type in {"calls", "observed_calls"}
                            and graph.nodes[edge.target].label.casefold()
                            in {"init", "initialize", "initialise", "setup", "bootstrap"}
                        ),
                        key=lambda edge: (-edge.confidence, edge.target, edge.type),
                    )[:1]
                for edge in lifecycle_edges:
                    connector_nodes.add(edge.target)
                    connector_edges.append(edge)
                connector_edges.sort(key=lambda edge: (edge.source, edge.target, edge.type))
                constraint_selection["lifecycle_preconditions"] = [edge.target for edge in lifecycle_edges]
                constraint_selection["nodes"] = len(connector_nodes)
                constraint_selection["edges"] = len(connector_edges)
                nodes, edges = connector_nodes, connector_edges
            elif len(evidence_groups) >= 2:
                path_connector_failed = True
    return nodes, edges, constraint_selection, path_connector_failed


def _base_result_metadata(graph: Graph, selection: _AnchorSelection, nodes, edges, starts, constraint_selection):
    request = selection.request
    query = request.query
    query_class = request.query_class
    scopes = request.scopes
    scope_mode = request.scope_mode
    anchor_paths = request.anchor_paths
    facets = request.facets
    plan = selection.plan
    selected_matches = selection.selected_matches
    inferred_scope = selection.inferred_scope
    effective_anchor_limit = selection.effective_anchor_limit
    # An anchor admitted on lexical similarity that then touched no edge in the
    # finished packet spent budget to say nothing. `anchor_contribution` has
    # always measured this and nothing acted on it. Explicit `anchor_paths` are
    # a caller directive -- the same reasoning the feasibility preflight above
    # applies -- so a pinned packet is never second-guessed here.
    pruned_anchors: tuple[str, ...] = ()
    if not anchor_paths:
        protected_anchors = {
            match.node.id
            for match in selected_matches
            if anchors._is_high_confidence_exact_anchor(match) or set(match.reasons) & quality.INJECTED_ANCHOR_REASONS
        }
        # The ranker's top hit is the answer it chose. Isolation pruning exists
        # to drop tail padding, not to evict the node search_nodes put first.
        if selected_matches:
            protected_anchors.add(selected_matches[0].node.id)
        # Edges are not the only way an anchor earns its place: a node whose
        # text covers a required facet is real evidence even when it is
        # structurally isolated, and dropping it degrades the answerability
        # diagnosis from "no directed connector" to the weaker "facet has no
        # evidence" -- a worse answer about the same graph.
        protected_anchors.update(
            node_id
            for node_id in starts
            if node_id in graph.nodes
            and any(facet_stage._facet_matches_node(graph.nodes[node_id], terms) for _label, terms in facets)
        )
        nodes, starts, pruned_anchors = quality.prune_unsupported_anchors(
            nodes,
            edges,
            starts,
            frozenset(protected_anchors),
        )
    effective_scope = scopes[0] if len(scopes) == 1 else inferred_scope
    metadata = quality.packet_quality_metadata(
        graph,
        nodes,
        edges,
        starts,
        effective_scope,
        query_class=query_class,
    )
    if pruned_anchors:
        metadata["quality"]["pruned_unsupported_anchors"] = list(pruned_anchors)
    if constraint_selection is not None:
        metadata["constraint_selection"] = constraint_selection
    if query_class == "doc_summary" and metadata["quality"]["grounded_doc_nodes"] == 0:
        metadata["quality"]["document_warning"] = "doc_summary selected zero grounded document body nodes"
    overload = _exact_overload_disambiguation(graph, query_class, query, selected_matches)
    if overload is not None:
        metadata["disambiguation"] = overload
    metadata.update(
        {
            "scope": list(scopes),
            "scope_mode": "auto_expand" if inferred_scope and not scopes else scope_mode,
            "inferred_scope": inferred_scope,
            "anchor_strategy": (
                "exact_fast_path"
                if selected_matches and all("exact_fast_path" in match.reasons for match in selected_matches)
                else "ranked"
            ),
            "plan_reason": plan.reason,
            "planner_version": plan.planner_version,
            "node_budget": plan.node_budget,
            "anchor_limit": effective_anchor_limit,
            "anchor_paths": _anchor_paths_metadata(anchor_paths, selected_matches, query_class),
        }
    )
    return metadata, nodes, starts


def _apply_facet_answerability(
    metadata, graph: Graph, selection: _AnchorSelection, nodes, edges, starts, path_connector_failed: bool
) -> None:
    request = selection.request
    query = request.query
    query_class = request.query_class
    facets = request.facets
    selected_matches = selection.selected_matches
    exact_anchor_fast_path = selection.exact_anchor_fast_path
    facet_roots = selection.facet_roots
    if facets:
        coverage = facet_stage.facet_coverage(graph, nodes, facets, roots=facet_roots or starts)
        metadata["facet_coverage"] = coverage
        structural_coverage = None
        if query_class in {"multi_hop_path", "direct_lookup", "reverse_lookup"}:
            structural_coverage = facet_stage.facet_coverage(
                graph,
                {node_id for node_id in nodes if is_code_like(graph.nodes[node_id])},
                facets,
                roots=facet_roots or starts,
            )
            metadata["structural_facet_coverage"] = structural_coverage
        # Only *required* (content) facets gate answerability. A facet that is
        # pure query shape -- "definition", "class" -- going unmatched must not
        # abstain over an answer the anchors already carry (graybox F2). See
        # facets._facet_is_required for the IDF + kind-vocabulary criterion.
        structural_required = bool(structural_coverage and structural_coverage.get("unfulfilled_required"))
        incomplete = bool(coverage.get("unfulfilled_required")) or structural_required or path_connector_failed
        answerability_confidence = round(anchors.retrieval_confidence(selected_matches), 4)
        if path_connector_failed:
            answerability_confidence = min(answerability_confidence, 0.2)
        semantic_support = metadata["quality"].get("semantic_support", {})
        if facet_stage.has_software_role_projection(facets) and not semantic_support.get("supported"):
            answerability_confidence = min(answerability_confidence, 0.2)
        metadata["answerability"] = {
            "status": "incomplete" if incomplete else "answerable",
            "abstained": path_connector_failed,
            "reason": (
                "one or more requested facets have no code or structural evidence"
                if structural_required
                else (
                    "requested facets have evidence but no directed structural connector"
                    if path_connector_failed
                    else coverage["warning"]
                )
            ),
            "confidence": answerability_confidence,
        }
    else:
        metadata["answerability"] = {
            "status": "answerable",
            "abstained": False,
            "reason": "",
            "confidence": round(anchors.retrieval_confidence(selected_matches), 4),
        }
    if query_class == "multi_hop_path" and exact_anchor_fast_path and len(starts) >= 2:
        closure, closure_confidence = obligations.exact_path_obligation_closure(
            starts,
            nodes,
            edges,
            plan_terms(query),
        )
        metadata["obligation_closure"] = closure
        if closure["ratio"] == 1.0:
            if metadata["answerability"]["status"] == "answerable":
                metadata["answerability"]["confidence"] = max(
                    metadata["answerability"]["confidence"],
                    closure_confidence,
                )
        else:
            metadata["answerability"] = {
                "status": "incomplete",
                "abstained": True,
                "reason": (
                    f"required structural obligations are unresolved: {closure['proven']}/{closure['required']} proven"
                ),
                "confidence": closure_confidence,
            }


def _apply_evidence_receipts(metadata, graph: Graph, selection: _AnchorSelection, nodes, edges, starts) -> None:
    request = selection.request
    query = request.query
    query_class = request.query_class
    scopes = request.scopes
    scope_mode = request.scope_mode
    requested_statuses = request.requested_statuses
    plan = selection.plan
    status_matches = selection.status_matches
    relationship_obligation = obligations.relationship_obligation_coverage(
        query_class,
        starts,
        edges,
        plan_terms(query),
        query,
    )
    if relationship_obligation is not None:
        metadata["relationship_obligation"] = relationship_obligation
        if relationship_obligation["status"] != "proven" and metadata["answerability"].get("status") == "answerable":
            current_confidence = float(metadata["answerability"].get("confidence", 0.49))
            metadata["answerability"] = {
                "status": "incomplete",
                "abstained": True,
                "reason": (
                    "the query requires "
                    f"{relationship_obligation['family']} evidence, but the selected packet "
                    "contains zero matching relationship edges"
                ),
                "confidence": round(min(current_confidence, 0.49), 4),
            }
    if query_class == "recent_changes":
        commit_nodes = sorted(node_id for node_id in nodes if graph.nodes[node_id].kind == "commit")
        change_edges = [edge for edge in edges if edge.active and edge.type in {"fixes", "changes"}]
        has_change_evidence = bool(commit_nodes or change_edges)
        metadata["change_evidence"] = {
            "required": True,
            "proven": has_change_evidence,
            "commit_nodes": commit_nodes,
            "change_edges": len(change_edges),
        }
        if not has_change_evidence:
            metadata["answerability"] = {
                "status": "incomplete",
                "abstained": True,
                "reason": "recent-change queries require commit or change-edge evidence; none was retrieved",
                "confidence": 0.15,
            }
    project_coverage = _named_project_coverage(graph, query, nodes)
    if project_coverage is not None:
        metadata["project_coverage"] = project_coverage
        if project_coverage["missing"]:
            current_confidence = float(metadata["answerability"].get("confidence", 0.49))
            metadata["answerability"] = {
                "status": "incomplete",
                "abstained": True,
                "reason": (
                    "named repositories lack selected evidence: "
                    + ", ".join(str(name) for name in project_coverage["missing"])
                ),
                "confidence": round(min(current_confidence, 0.49), 4),
            }
    _document_status_answerability(
        metadata,
        graph=graph,
        query_class=query_class,
        requested_statuses=requested_statuses,
        status_matches=status_matches,
        nodes=nodes,
    )
    if query_class == "reverse_lookup":
        truncation = reservations.reverse_lookup_truncation(
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
                    f"node budget omitted {truncation['omitted_direct_neighbors']} known direct reverse neighbor(s)"
                ),
            }


def _apply_document_receipts(metadata, graph: Graph, selection: _AnchorSelection, nodes, starts) -> None:
    request = selection.request
    query = request.query
    query_class = request.query_class
    anchor_paths = request.anchor_paths
    facets = request.facets
    selected_matches = selection.selected_matches
    _affected_tests_metadata(
        metadata,
        graph=graph,
        query=query,
        query_class=query_class,
        starts=starts,
        nodes=nodes,
        facets=facets,
        anchor_paths=anchor_paths,
    )
    if query_class == "doc_summary" and not any(node.kind in {"section", "paragraph"} for node in graph.nodes.values()):
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
    # A requested document the scanner truncated yields at best a partial
    # answer: the packet is built over an incomplete document, so summarizing it
    # as whole would overstate coverage (T10). Surface the clipped documents and
    # downgrade a would-be-answerable receipt to an explicit, non-abstaining
    # partial -- a stronger abstention set upstream (conflicting status rows, an
    # empty doc graph) is left untouched.
    requested_doc_paths = tuple(dict.fromkeys((*anchor_paths, *(match.node.path for match in selected_matches))))
    truncated_documents = _truncated_requested_documents(graph, requested_doc_paths)
    if truncated_documents:
        metadata["document_truncation"] = {
            "truncated": True,
            "requested_documents": truncated_documents,
            "reason": (
                "requested document(s) were truncated during scan; "
                "the packet reflects a partial document: " + ", ".join(truncated_documents)
            ),
        }
        answerability = metadata.get("answerability")
        if (
            isinstance(answerability, dict)
            and answerability.get("status") == "answerable"
            and not answerability.get("abstained")
        ):
            answerability["status"] = "partial"
            answerability["reason"] = metadata["document_truncation"]["reason"]

    # Single guarantee that every answerability receipt carries a real answer
    # confidence, however it was set above. Several branches build the dict and
    # fall through here; rather than repeat the field at each (and silently miss
    # one, as the first pass did -- the CLI surfaced status but a null
    # confidence), backfill it once from the anchors that actually seeded this
    # result. Branches that already computed it keep their value.
    answerability = metadata.get("answerability")
    if isinstance(answerability, dict) and "confidence" not in answerability:
        answerability["confidence"] = round(anchors.retrieval_confidence(selected_matches), 4)
    # Confidence must honor the receipt's own status: an incomplete/partial/
    # abstained answer cannot advertise the anchor-shape confidence of a clean
    # hit, or the trust signal inverts (a dirty-miss fuzzy collision reads 0.7).
    if isinstance(answerability, dict):
        anchors.gate_answer_confidence(answerability, selected_matches)


def _assemble_retrieval_result(
    graph: Graph,
    selection: _AnchorSelection,
    *,
    activation_state_path: Path | None,
) -> RetrievalResult:
    request = selection.request
    query = request.query
    query_class = request.query_class
    selected_matches = selection.selected_matches
    starts = selection.starts
    nodes, edges, starts, constraint_selection, path_connector_failed = _expand_result_graph(
        graph, selection, activation_state_path
    )
    metadata, nodes, starts = _base_result_metadata(graph, selection, nodes, edges, starts, constraint_selection)
    _apply_facet_answerability(metadata, graph, selection, nodes, edges, starts, path_connector_failed)
    _apply_evidence_receipts(metadata, graph, selection, nodes, edges, starts)
    _apply_document_receipts(metadata, graph, selection, nodes, starts)
    if subsystems.wants_subsystem_map(query, query_class):
        metadata["subsystem_map"] = subsystems.build_subsystem_map(graph)
    selected_matches, nodes, edges, starts = _apply_ungrounded_packet_abstention(
        metadata, selection, selected_matches, nodes, edges, starts
    )
    _record_evidence_and_completeness(metadata, starts, nodes)

    return RetrievalResult(starts=starts, matches=selected_matches, nodes=nodes, edges=edges, metadata=metadata)


def _record_evidence_and_completeness(metadata, starts, nodes) -> None:
    """Split minimum-evidence success from full-neighborhood completeness."""

    answerability = metadata.get("answerability")
    if not isinstance(answerability, dict):
        return
    status = str(answerability.get("status", "unknown"))
    abstained = bool(answerability.get("abstained"))
    truncation = metadata.get("truncation") if isinstance(metadata.get("truncation"), dict) else {}
    omitted = int(truncation.get("omitted_direct_neighbors") or 0)
    has_subgraph = bool(starts or nodes)
    minimum_evidence = status != "unanswerable" and has_subgraph
    complete = (
        minimum_evidence
        and status == "answerable"
        and not abstained
        and omitted == 0
    )
    answerability["minimum_evidence"] = minimum_evidence
    answerability["neighborhood_complete"] = complete


def _ranker_expressed_a_preference(matches) -> bool:
    """Whether ranking produced a strict winner rather than a tie at the top.

    The abstention below exists for one measured failure: a query whose tokens
    collide with a plateau of generic hubs, where no node carries distinctive
    evidence and the system shipped an "answerable" packet of confidently wrong
    context. (The protecting test's comment says ~1800 tokens; an independent
    measurement of the unguarded path found 34. The size is disputed; the
    wrongness is not.) In that case the ranker scores every
    candidate *identically* -- six hubs at 19.2612 -- so choosing the first is
    arbitrary, and abstaining is right.

    Low grounding on its own is not that case. Grounding measures how far the
    query's literal terms reach into an anchor's identity, which a paraphrase
    lacks by construction, so on natural-language questions over a code
    repository the same rule fired on answers that were present and correctly
    ranked. Measured on CodeSearchNet: the gate cost **23 points of recall@10**
    (0.5167 against 0.7500 with it disabled) at no latency saving, and 16 of
    the 23 abstentions were queries BM25 answered from its top ten.

    The separation is empirically bimodal rather than threshold-free. Over 80
    gate decisions the relative winning margin is either exactly 0 (ties) or at
    least 1.4%; nothing lands between. So a constant anywhere in that two-order
    gap behaves identically, which is why none is written here -- but strict
    ``>`` is still a threshold at zero, and it is sensitive at the last bit: an
    independent checker flipped the protected case by adding 1e-12 to one score.

    Known limit, and it is the important one. This guards *exact* score
    symmetry, which is a property of the synthetic collision fixture. A
    realistic plateau -- six similarly generic helpers with differently worded
    summaries -- produces a 14.5% "winner" that is cosmetic rather than
    relevant, and sails through. The protection is therefore closer to nominal
    than the recall gain is; see ROADMAP R-009, which asks for the missing
    abstention-precision measurement.
    """
    if len(matches) < 2:
        # A lone ungrounded candidate is the *most* degenerate case, not a
        # preference: there was nothing to prefer it over. An earlier version
        # returned True here, which silently widened the change beyond the
        # strict-winner rule it documented and shipped a single unranked match
        # on 6 of 80 gate decisions. Found by an independent checker.
        return False
    return matches[0].score > matches[1].score


def _apply_ungrounded_packet_abstention(
    metadata: dict[str, object],
    selection: _AnchorSelection,
    selected_matches,
    nodes,
    edges,
    starts,
):
    """Empty a packet whose effective confidence is below policy.

    Effective confidence is shape confidence times a noisy-OR grounding
    score (exact hit, pinned seed, paraphrase specificity, identity
    coverage). Incomplete receipts keep their taxonomy; already-empty
    receipts are unchanged.
    """
    if not starts and not nodes:
        return selected_matches, nodes, edges, starts
    request = selection.request
    # doc_summary has its own document-status taxonomy. Emptying a scoped
    # document hit treats an operator-directed read as a dirty lexical miss.
    if request.query_class == "doc_summary":
        return selected_matches, nodes, edges, starts
    current = metadata.get("answerability") if isinstance(metadata.get("answerability"), dict) else {}
    incomplete = isinstance(current, dict) and current.get("status") == "incomplete"
    # Conceptual role recovery fills required facets on a connected subgraph.
    # That is not a dirty lexical miss, even when no identifier/summary
    # channel fires. Isolated generic-hub collisions have no facet receipt.
    facet = metadata.get("facet_coverage") if isinstance(metadata.get("facet_coverage"), dict) else {}
    facet_grounded = bool(facet.get("fulfilled")) and not facet.get("unfulfilled_required")
    if incomplete or facet_grounded:
        return selected_matches, nodes, edges, starts
    injected = any(set(match.reasons) & quality.INJECTED_ANCHOR_REASONS for match in selected_matches)
    effective = anchors.effective_answer_confidence(
        selected_matches,
        request.query,
        injected=injected,
        pinned_paths=bool(request.anchor_paths),
    )
    if effective >= anchors.ABSTAIN_POLICY or incomplete:
        return selected_matches, nodes, edges, starts
    if _ranker_expressed_a_preference(selected_matches):
        return selected_matches, nodes, edges, starts
    raw = 0.2
    if isinstance(current, dict) and current.get("confidence") is not None:
        try:
            raw = float(current["confidence"])
        except (TypeError, ValueError):
            raw = 0.2
    metadata["answerability"] = {
        "status": "unanswerable",
        "abstained": True,
        "reason": (
            "effective answer confidence "
            f"{effective:.3f} is below policy {anchors.ABSTAIN_POLICY:.2f}"
        ),
        "confidence": round(min(raw, effective, anchors.ABSTAIN_POLICY), 4),
    }
    return (), set(), [], ()
