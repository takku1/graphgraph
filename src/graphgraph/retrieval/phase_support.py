"""Context retrieval orchestrator over explicit retrieval-stage modules."""

from __future__ import annotations

import re
from pathlib import Path

import graphgraph.retrieval.anchors as anchors
import graphgraph.retrieval.document_status as document_status
import graphgraph.retrieval.facets as facet_stage
import graphgraph.retrieval.quality as quality
import graphgraph.retrieval.scoping as scoping
import graphgraph.retrieval.subsystems as subsystems
import graphgraph.retrieval.test_recommendations as test_recommendations

from ..concepts.doccode import is_code_like
from ..graph.core import Graph
from .models import Match, RetrievalResult

#: Upper bound on the headroom granted to `reserve_facet_matches` above the
#: 12-start packet cap, so it can still reserve facet evidence when ranked
#: selection has already filled the cap. Whatever it reserves then displaces the
#: weakest ranked anchors (see `_seat_facet_reservations`); the packet never
#: grows.
#:
#: This is a safety bound, not a fitted parameter. The actual headroom asked for
#: is `min(len(anchor_facets), this)`, and reservation stops as soon as each
#: facet's obligation is covered -- so it is self-limiting and the bound does not
#: bind on any task in the held-out panel: 2, 4 and 12 give byte-identical
#: results across all 22 external tasks (flask/express/ripgrep/locus). It exists
#: only so that a pathological query carrying the parser's full twelve facets
#: cannot evict the entire ranked root set, which is the failure the semantic
#: terminal balancer already guards against on its own path.
_FACET_ANCHOR_RESERVATION = 4

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


def _seat_facet_reservations(
    ranked: tuple[Match, ...],
    reserved: tuple[Match, ...],
    *,
    limit: int,
) -> tuple[Match, ...]:
    """Fit facet reservations inside the anchor cap by displacing ranked tail.

    ``reserve_facet_matches`` preserves its input as a prefix and appends what
    it newly reserved, so anything past ``len(ranked)`` is a facet reservation.
    Truncating the result at the cap would therefore delete exactly the anchors
    the facet stage went and found -- the failure this exists to prevent. Trim
    the *ranked* tail instead, keeping ranked order otherwise intact, and never
    drop a reservation to keep a merely well-scoring lexical hit.

    A run that reserved nothing returns its input unchanged, so a query whose
    facets were already satisfied keeps the full ranked budget.
    """
    additions = reserved[len(ranked) :]
    if not additions or len(reserved) <= limit:
        return reserved[:limit] if len(reserved) > limit else reserved
    kept_additions = additions[: max(0, limit)]
    keep_ranked = max(0, limit - len(kept_additions))
    return (*ranked[:keep_ranked], *kept_additions)


def _named_project_coverage(graph: Graph, query: str, nodes: set[str]) -> dict[str, object] | None:
    """Measure evidence coverage for repositories explicitly named in a query."""
    project_names = {
        node.scope or node.label
        for node in graph.nodes.values()
        if node.active and node.kind == "project" and (node.scope or node.label)
    }
    project_names.update(name.strip() for name in str(graph.metadata.get("projects", "")).split(",") if name.strip())
    if len(project_names) < 2:
        return None
    named = sorted(
        name for name in project_names if re.search(rf"(?<![\w-]){re.escape(name)}(?![\w-])", query, flags=re.I)
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
                or (name.casefold() == current_project.casefold() and "::" not in node_id)
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
            and not scoping._is_test_material(graph.nodes[start])
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
    mention_fulfilled: frozenset[str] = frozenset(),
) -> RetrievalResult:
    """Return a zero-packet reject receipt for a complete semantic miss.

    ``mention_fulfilled`` names required facets that *documentation* covers
    while code and structural evidence miss. That is a weaker outcome than an
    answer but a stronger one than silence: the corpus does discuss the thing,
    it just has no code to point at. Reporting it as ``unanswerable`` told the
    caller nothing was found, which is wrong and hides the doc that was.
    """
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
                "status": "incomplete" if mention_fulfilled else "unanswerable",
                "abstained": True,
                "reason": (
                    "only documentation mentions cover the required query facets "
                    f"({', '.join(sorted(mention_fulfilled))}); no code or structural "
                    "graph evidence"
                    if mention_fulfilled
                    else "no code or structural graph evidence covers any required query facet"
                ),
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
