"""Context retrieval orchestrator over explicit retrieval-stage modules."""

from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path

from ..concepts import INTERPRETATION_CONCEPT_IDS
from ..concepts.doccode import doc_code_bias, is_code_like
from ..graph.core import Graph
from ..graph.ontology import provenance_confidence
from ..planning import plan_context
from ..planning.budgets import doc_intensity_score, explicit_query_identifiers, plan_terms
from . import (
    anchors,
    document_status,
    expansion,
    obligations,
    quality,
    reservations,
    scoping,
    search,
    subsystems,
    test_recommendations,
)
from . import facets as facet_stage
from .models import Match, RetrievalResult

_OVERLOAD_DEF_KINDS = frozenset(
    {
        "function",
        "method",
        "class",
        "struct",
        "trait",
        "enum",
        "interface",
        "type",
    }
)


def _named_project_coverage(graph: Graph, query: str, nodes: set[str]) -> dict[str, object] | None:
    """Measure evidence coverage for repositories explicitly named in a query."""
    project_names = {
        node.scope or node.label
        for node in graph.nodes.values()
        if node.active and node.kind == "project" and (node.scope or node.label)
    }
    project_names.update(
        name.strip()
        for name in str(graph.metadata.get("projects", "")).split(",")
        if name.strip()
    )
    if len(project_names) < 2:
        return None
    named = sorted(
        name
        for name in project_names
        if re.search(rf"(?<![\w-]){re.escape(name)}(?![\w-])", query, flags=re.I)
    )
    if not named:
        return None
    current_project = str(graph.metadata.get("current_project", ""))
    represented = sorted(
        name
        for name in named
        if any(
            node_id in graph.nodes
            and graph.nodes[node_id].kind != "project"
            and (
                graph.nodes[node_id].scope.casefold() == name.casefold()
                or (
                    name.casefold() == current_project.casefold()
                    and "::" not in node_id
                )
            )
            for node_id in nodes
        )
    )
    missing = [name for name in named if name not in represented]
    return {
        "required": named,
        "represented": represented,
        "missing": missing,
        "coverage_ratio": round(len(represented) / len(named), 4),
    }


def _exact_overload_disambiguation(
    graph: Graph,
    query_class: str,
    query: str,
    matches: tuple[Match, ...],
) -> dict[str, object] | None:
    """Explain a ranked fallback caused by an *overloaded* exact identifier.

    An exact, unique identifier uses the fast path; an exact identifier that
    resolves to several definitions cannot, so retrieval correctly ranks to
    disambiguate -- but the receipt used to report only ``anchor=ranked`` with
    no reason (graybox T12). When a bare-identifier query matches two or more
    exact definitions of the same name, name the count so a consumer sees *why*
    ranking ran rather than the fast path.
    """
    if query_class != "direct_lookup" or not matches:
        return None
    exact_labels: dict[str, int] = {}
    for match in matches:
        if any(reason.startswith("label_exact") for reason in match.reasons):
            key = match.node.label.casefold()
            exact_labels[key] = exact_labels.get(key, 0) + 1
    if not exact_labels:
        return None
    label, count = max(exact_labels.items(), key=lambda item: item[1])
    # Only for a query that IS this one identifier: a phrase query ranks for
    # other reasons and must not be mislabeled an overload.
    if count < 2 or query.strip().casefold() != label:
        return None
    # Count graph-wide for an accurate receipt; the anchor budget may have
    # trimmed `matches` below the true number of definitions.
    definitions = max(
        count,
        sum(
            1
            for node in graph.nodes.values()
            if node.active and node.kind in _OVERLOAD_DEF_KINDS and node.label.casefold() == label
        ),
    )
    display = next(
        (match.node.label for match in matches if match.node.label.casefold() == label),
        label,
    )
    return {
        "identifier": display,
        "definitions": definitions,
        "reason": (f"'{display}' resolves to {definitions} exact definitions; ranked to disambiguate"),
    }


def _normalize_doc_path(path: str) -> str:
    return path.replace("\\", "/").lstrip("./").strip("/")


def _truncated_requested_documents(
    graph: Graph,
    anchor_paths: tuple[str, ...],
) -> list[str]:
    """Requested documents the scanner truncated during extraction.

    The scanner records every document whose section/paragraph extraction hit
    the per-document cap in ``graph.metadata['docs_truncated_files']`` (T10 part
    one). When such a document is also what this query anchored on, the packet
    is built over an incomplete document and must say so rather than presenting
    a clipped summary as whole. Matching is segment-aware so ``foo.md`` never
    masquerades as a suffix of ``barfoo.md``.
    """
    raw = graph.metadata.get("docs_truncated_files", "")
    if not raw or not anchor_paths:
        return []
    truncated = {normalized for entry in raw.split(",") if (normalized := _normalize_doc_path(entry))}
    if not truncated:
        return []
    hits: list[str] = []
    for anchor in anchor_paths:
        norm = _normalize_doc_path(anchor)
        if any(norm == cut or norm.endswith("/" + cut) or cut.endswith("/" + norm) for cut in truncated):
            hits.append(anchor)
    return sorted(dict.fromkeys(hits))


def _document_status_answerability(
    metadata: dict[str, object],
    *,
    graph: Graph,
    query_class: str,
    requested_statuses,
    status_matches,
    nodes: set[str],
) -> None:
    """Finalize doc_summary answerability from grounded/status evidence.

    Extracted verbatim from :func:`retrieve_context`; mutates ``metadata`` with
    the document warning, `document_status_evidence`, and the corresponding
    abstention when a requested roadmap status is missing or conflicting.
    """
    document_warning = str(metadata["quality"].get("document_warning", ""))
    if query_class == "doc_summary" and document_warning:
        metadata["answerability"] = {
            "status": "incomplete",
            "abstained": True,
            "reason": document_warning,
        }
    if query_class == "doc_summary" and requested_statuses:
        status_labels = ["absent" if status == "" else "partial" for status in sorted(requested_statuses)]
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
            row = document_status._document_status_row(" ".join(str(fact) for fact in node.facts))
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


def _affected_tests_metadata(
    metadata: dict[str, object],
    *,
    graph: Graph,
    query: str,
    query_class: str,
    starts: tuple[str, ...],
    nodes: set[str],
    facets,
    anchor_paths,
) -> None:
    """Attach affected-test recommendations for test-oriented queries.

    Mutates ``metadata`` with ``affected_tests``/``hybrid_intents`` for the
    ``affected_tests`` class, a compound test-evidence query, or a changed-path
    signal. Extracted verbatim from :func:`retrieve_context` to keep the
    orchestrator readable; behavior is unchanged.
    """
    changed_path_tests = test_recommendations.changed_path_test_recommendations(graph, anchor_paths)
    if query_class == "affected_tests":
        cover_all_direct_tests = any({"all", "direct", "tests"} <= set(terms) for _label, terms in facets)
        affected = test_recommendations.affected_test_recommendations(
            graph,
            starts,
            nodes,
            cover_all_direct_tests=cover_all_direct_tests,
        )
        if changed_path_tests["commands"]:
            selected_entries = list(affected["command_provenance"])
            changed_entries = list(changed_path_tests["command_provenance"])

            def entry_test_ids(entry: dict[str, object]) -> set[str]:
                return {str(test.get("id", "")) for test in entry.get("tests", []) if test.get("id")}

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
            kept_selected = [entry for entry in selected_entries if str(entry["command"]) not in superseded]
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
            affected["commands"] = list(dict.fromkeys(str(entry["command"]) for entry in merged_entries))
            affected["commands_by_role"]["changed_path_regression"] = [str(entry["command"]) for entry in kept_changed]
            direct_ids = {str(item["id"]) for item in affected["direct"]}
            transitive_ids = {str(item["id"]) for item in affected["transitive"]}
            affected["commands_by_role"]["direct_behavior_or_contract"] = list(
                dict.fromkeys(str(entry["command"]) for entry in merged_entries if entry_test_ids(entry) & direct_ids)
            )
            affected["commands_by_role"]["transitive_regression"] = list(
                dict.fromkeys(
                    str(entry["command"]) for entry in merged_entries if entry_test_ids(entry) & transitive_ids
                )
            )
            affected["command_provenance"] = merged_entries
            affected["command_selection"]["selected_count"] = len(affected["commands"])
            affected["command_selection"]["superseded_commands"] = sorted(superseded)
            affected["changed_path_candidates"] = changed_path_tests["candidates"]
        metadata["affected_tests"] = affected
        metadata["hybrid_intents"] = ["multi_hop_path", "affected_tests"]
    elif scoping._TEST_EVIDENCE_QUERY.search(query):
        compound_test_roots = tuple(
            start
            for start in starts
            if start in graph.nodes
            and graph.nodes[start].kind not in scoping.NON_STRUCTURAL_KINDS
            and graph.nodes[start].kind in {"function", "method", "class", "struct", "trait", "enum", "field"}
            and not scoping._is_test_node(graph.nodes[start])
        )[:1]
        if compound_test_roots:
            affected = test_recommendations.affected_test_recommendations(
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


def _anchor_paths_metadata(
    anchor_paths: tuple[str, ...],
    selected_matches: tuple[Match, ...],
    query_class: str,
) -> list[dict[str, object]]:
    """Describe each explicitly-supplied anchor path for the receipt.

    A pure projection of the chosen anchors over the requested paths: it records
    each path's role (test evidence, primary document root, file fallback, or
    plain root) and which selected anchor node ids resolved to it. Lifted out of
    the success-metadata assembly, where the nested comprehension obscured the
    happy-path flow.
    """
    return [
        {
            "path": path,
            "role": (
                "test_evidence_candidate"
                if query_class == "affected_tests" and scoping._is_test_path(path)
                else "primary_root"
                if Path(path).suffix.casefold() in {".md", ".mdx", ".rst", ".txt", ".html", ".htm"}
                else "file_fallback"
                if any(
                    match.node.path.replace("\\", "/").strip("/") == path.replace("\\", "/").strip("/")
                    and "file_fallback" in match.reasons
                    for match in selected_matches
                )
                else "primary_root"
            ),
            "anchors": [
                match.node.id
                for match in selected_matches
                if match.node.path.replace("\\", "/").strip("/") == path.replace("\\", "/").strip("/")
            ],
        }
        for path in dict.fromkeys(anchor_paths)
    ]


def _negative_query_abstain(
    graph: Graph,
    *,
    query_class: str,
    facets: tuple,
    selected_matches: tuple[Match, ...],
    plan,
) -> RetrievalResult | None:
    """Abstain when a negative query's entity facets have no code/structural cover.

    Returns a terminal unanswerable receipt if this is a facet-bearing negative
    query whose anchors carry no code or structural evidence for the requested
    entities, else ``None`` to let the pipeline continue. Lifted out of the main
    flow as another unhappy-path branch.
    """
    if query_class != "negative_query" or not facets:
        return None
    selected_ids = {match.node.id for match in selected_matches}
    anchor_coverage = facet_stage.facet_coverage(
        graph,
        {node_id for node_id in selected_ids if is_code_like(graph.nodes[node_id])},
        facets,
    )
    if anchor_coverage["fulfilled"]:
        return None
    mention_coverage = facet_stage.facet_coverage(graph, selected_ids, facets)
    return RetrievalResult(
        starts=(),
        matches=selected_matches,
        nodes=set(),
        edges=[],
        metadata={
            "facet_coverage": anchor_coverage,
            "mention_coverage": mention_coverage,
            "answerability": anchors.gate_answer_confidence(
                {
                    "status": "unanswerable",
                    "abstained": True,
                    "reason": "no code or structural graph evidence covers the requested entity facets",
                    "confidence": round(anchors.retrieval_confidence(selected_matches), 4),
                },
                selected_matches,
            ),
            "plan_reason": plan.reason,
            "planner_version": plan.planner_version,
        },
    )


def _semantic_novelty_result(
    graph: Graph,
    *,
    query_class: str,
    coverage: dict[str, object],
    structural_coverage: dict[str, object],
    selected_matches: tuple[Match, ...],
    plan,
    scopes: tuple[str, ...],
    scope_mode: str,
    inferred_scope: str,
    effective_anchor_limit: int,
    anchor_paths: tuple[str, ...],
) -> RetrievalResult:
    """Return a zero-packet reject receipt for a complete semantic miss."""
    effective_scope = scopes[0] if len(scopes) == 1 else inferred_scope
    metadata = quality.packet_quality_metadata(
        graph,
        set(),
        [],
        (),
        effective_scope,
        query_class=query_class,
    )
    metadata.update(
        {
            "scope": list(scopes),
            "scope_mode": "auto_expand" if inferred_scope and not scopes else scope_mode,
            "inferred_scope": inferred_scope,
            "anchor_strategy": "ranked",
            "plan_reason": plan.reason,
            "planner_version": plan.planner_version,
            "node_budget": plan.node_budget,
            "anchor_limit": effective_anchor_limit,
            "anchor_paths": _anchor_paths_metadata(
                anchor_paths,
                selected_matches,
                query_class,
            ),
            "facet_coverage": coverage,
            "structural_facet_coverage": structural_coverage,
            # This is answer confidence, not confidence in the reject
            # decision. A real exact anchor (for example ``Flask``) does not
            # support an answer when every required compound facet misses.
            "answerability": {
                "status": "unanswerable",
                "abstained": True,
                "reason": ("no code or structural graph evidence covers any required query facet"),
                "confidence": 0.0,
            },
        }
    )
    return RetrievalResult(
        starts=(),
        matches=selected_matches,
        nodes=set(),
        edges=[],
        metadata=metadata,
    )


def _empty_anchor_result(
    graph: Graph,
    *,
    query: str,
    query_class: str,
    scopes: tuple[str, ...],
    scope_mode: str,
    inferred_scope: str,
    status_constrained: bool,
    requested_statuses: set[str],
    plan,
    effective_anchor_limit: int,
    matches: tuple[Match, ...],
    selected_matches: tuple[Match, ...],
) -> RetrievalResult:
    """Build the abstention receipt for a query that anchored no traversal roots.

    Terminal handler for the ``not starts`` case, lifted out of the main flow so
    the happy path reads uninterrupted. Two outcomes: a status-constrained
    document query reports that no literal capability rows were found; any other
    empty query is unanswerable, except that a whole-graph architecture map can
    still answer a broad "what are the subsystems" question without anchors.
    """
    if status_constrained:
        status_labels = ["absent" if status == "" else "partial" for status in sorted(requested_statuses)]
        status_warning = (
            "no literal " + "/".join(status_labels) + " capability rows were found in the requested roadmap documents"
        )
        effective_scope = scopes[0] if len(scopes) == 1 else inferred_scope
        metadata = quality.packet_quality_metadata(
            graph,
            set(),
            [],
            (),
            effective_scope,
            query_class=query_class,
        )
        metadata.update(
            {
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
                "answerability": anchors.gate_answer_confidence(
                    {
                        "status": "incomplete",
                        "abstained": True,
                        "reason": status_warning,
                        "confidence": round(anchors.retrieval_confidence(selected_matches), 4),
                    },
                    selected_matches,
                ),
            }
        )
        return RetrievalResult(
            starts=(),
            matches=(),
            nodes=set(),
            edges=[],
            metadata=metadata,
        )
    no_anchor_metadata: dict[str, object] = {
        "answerability": anchors.gate_answer_confidence(
            {
                "status": "unanswerable",
                "abstained": True,
                "reason": "no matching graph anchors",
                "confidence": round(anchors.retrieval_confidence(matches), 4),
            },
            matches,
        ),
    }
    # A whole-graph architecture map does not depend on query anchors, so a
    # broad "what are the subsystems" query is answered by the map even when
    # no single node anchored. Without this the map was reachable only when a
    # node happened to match, making the answer depend on lexical luck.
    if subsystems.wants_subsystem_map(query, query_class):
        subsystem_map = subsystems.build_subsystem_map(graph)
        if subsystem_map["subsystems"]:
            no_anchor_metadata["subsystem_map"] = subsystem_map
            no_anchor_metadata["answerability"] = anchors.gate_answer_confidence(
                {
                    "status": "answerable",
                    "abstained": False,
                    "reason": "architecture map derived from source layout",
                    "confidence": round(anchors.retrieval_confidence(matches), 4),
                },
                matches,
            )
    return RetrievalResult(
        starts=(),
        matches=matches,
        nodes=set(),
        edges=[],
        metadata=no_anchor_metadata,
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
    facet_aware = query_class in {
        "affected_tests",
        "blast_radius",
        "multi_hop_path",
        "negative_query",
        "doc_summary",
        "reverse_lookup",
    } or (query_class == "direct_lookup" and bool(identifiers)) or (
        query_class == "subsystem_summary"
        and bool(re.search(r"\barchitectur(?:e|al)\b", query, re.I))
    )
    facets = facet_stage.query_facets(query) if facet_aware else ()
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
    if query_class == "reverse_lookup" and facets:
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
        if not global_coverage.get("fulfilled") and global_coverage.get("unfulfilled_required"):
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
    priority_matches = (*path_matches, *source_matches)
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
                sorted(
                    (
                        node
                        for node in graph.nodes.values()
                        if node.active
                        and is_code_like(node)
                        and (not scopes or scoping._path_in_scopes(node.path, scopes))
                        and facet_stage._facet_matches_node(node, facet_terms)
                    ),
                    key=lambda node: (
                        scoping._is_test_node(node),
                        node.kind != "external",
                        node.kind not in {"method", "function", "external"},
                        len(node.path),
                        node.id,
                    ),
                )[:4]
                if query_class == "multi_hop_path"
                else []
            )
            if semantic_candidates:
                semantic_terminals.append(
                    Match(semantic_candidates[0], 1000.0, ("semantic_structural_terminal",))
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
        if len(semantic_terminals) == len(facets):
            semantic_terminal_matches = tuple(
                {match.node.id: match for match in semantic_terminals}.values()
            )
    if status_constrained:
        # Status is an evidence type, not a ranking preference. Facet searches,
        # source seeds, and path roots may orient an ordinary document query,
        # but they cannot substitute legend prose or a different status class
        # for a requested literal capability row.
        matches = status_matches
    inferred_scope = "" if scopes else anchors.infer_dominant_scope(matches, query)
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
        selected_matches = facet_stage.reserve_facet_matches(
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
    selected_matches = anchors.select_enumerated_doc_roots(
        selected_matches,
        matches,
        query=query,
        query_class=query_class,
    )
    if query_class == "multi_hop_path" and semantic_terminal_matches:
        # All prose facets compiled to structural terminals. They are the path
        # constraints; unrelated whole-query lexical hits must not become
        # additional mandatory roots and defeat the connector optimizer.
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
    constraint_selection = None
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
                (*evidence_groups, *((node_id,) for node_id in starts)),
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
    effective_scope = scopes[0] if len(scopes) == 1 else inferred_scope
    metadata = quality.packet_quality_metadata(
        graph,
        nodes,
        edges,
        starts,
        effective_scope,
        query_class=query_class,
    )
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
        incomplete = bool(coverage.get("unfulfilled_required")) or structural_required
        metadata["answerability"] = {
            "status": "incomplete" if incomplete else "answerable",
            "abstained": False,
            "reason": (
                "one or more requested facets have no code or structural evidence"
                if structural_required
                else coverage["warning"]
            ),
            "confidence": round(anchors.retrieval_confidence(selected_matches), 4),
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
    relationship_obligation = obligations.relationship_obligation_coverage(
        query_class,
        starts,
        edges,
        plan_terms(query),
        query,
    )
    if relationship_obligation is not None:
        metadata["relationship_obligation"] = relationship_obligation
        if (
            relationship_obligation["status"] != "proven"
            and metadata["answerability"].get("status") == "answerable"
        ):
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

    if subsystems.wants_subsystem_map(query, query_class):
        metadata["subsystem_map"] = subsystems.build_subsystem_map(graph)

    return RetrievalResult(starts=starts, matches=selected_matches, nodes=nodes, edges=edges, metadata=metadata)
