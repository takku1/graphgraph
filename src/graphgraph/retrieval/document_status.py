"""Document status facets and status-constrained packet handling."""

from __future__ import annotations

import re

from ..concepts.terms import term_key
from ..graph.core import Edge, Graph
from ..planning.budgets import plan_terms
from .models import Match
from .scoping import (
    _path_in_scopes,
)

_DOCUMENT_STATUS_MARKER = re.compile(
    r"^\s*(?:[-+*]\s*)?`?\[\s*([xX~]?)\s*\]`?",
)

_DOCUMENT_STATUS_CELL = re.compile(r"^`?\[\s*([xX~]?)\s*\]`?$")

_DOCUMENT_TABLE_ROW = re.compile(r"^\s*\|(?:[^|\r\n]*\|){2,}\s*$")

_ABSENT_DOCUMENT_INTENT = re.compile(
    r"\b(?:marked|currently|explicitly)\s+absent\b|"
    r"\b(?:unimplemented|not\s+implemented|missing\s+capabilit(?:y|ies))\b",
    re.I,
)

_PARTIAL_DOCUMENT_INTENT = re.compile(
    r"\b(?:marked|currently|explicitly)\s+partial\b|"
    r"\bpartially\s+implemented\b",
    re.I,
)

def _requested_document_statuses(query: str) -> set[str]:
    wanted: set[str] = set()
    if _ABSENT_DOCUMENT_INTENT.search(query):
        wanted.add("")
    if _PARTIAL_DOCUMENT_INTENT.search(query):
        wanted.add("~")
    return wanted

def _document_status_facet(
    terms: tuple[str, ...],
    requested_statuses: set[str],
) -> bool:
    words = set(terms)
    return (
        ("" in requested_statuses and "absent" in words)
        or ("~" in requested_statuses and bool(words & {"partial", "partially"}))
        or (
            bool(requested_statuses)
            and "status" in words
            and bool(words & {"class", "only"})
        )
    )

def _document_status_row(body: str) -> tuple[str, str] | None:
    """Decode one status-bearing document row into status and subject.

    This is intentionally a row grammar, not a substring search. A legend,
    prose mentioning ``[ ]``, and an old graph node containing an entire table
    must not masquerade as one capability operand.
    """
    marker = _DOCUMENT_STATUS_MARKER.match(body)
    if marker:
        remainder = body[marker.end():].strip()
        subject = re.match(
            r"\*\*([^*]{2,160}?)(?::\*\*|\*\*\s*:)",
            remainder,
        )
        return marker.group(1).casefold(), subject.group(1).strip() if subject else ""

    stripped = body.strip()
    if not _DOCUMENT_TABLE_ROW.fullmatch(stripped):
        return None
    cells = [cell.strip() for cell in stripped.strip("|").split("|")]
    status_cells = [
        (index, match.group(1).casefold())
        for index, cell in enumerate(cells)
        if (match := _DOCUMENT_STATUS_CELL.fullmatch(cell))
    ]
    # A row has one status operand. Multiple markers indicate a legacy node
    # containing a whole unsplit table and must fail closed until reindexed.
    if len(status_cells) != 1:
        return None
    status_index, status = status_cells[0]
    subject = next(
        (
            re.sub(r"^[`*_]+|[`*_]+$", "", cell).strip()
            for cell in reversed(cells[:status_index])
            if cell
        ),
        "",
    )
    if term_key(subject) in {"capability", "status", "item", "feature"}:
        subject = ""
    return status, subject

def document_status_anchor_matches(
    graph: Graph,
    query: str,
    *,
    scopes: tuple[str, ...] = (),
) -> tuple[Match, ...]:
    """Compile roadmap status language to literal checkbox-row anchors."""
    wanted = _requested_document_statuses(query)
    if not wanted:
        return ()

    query_terms = set(plan_terms(query))
    roadmap_intent = "roadmap" in query_terms
    capability_intent = bool(query_terms & {"capability", "capabilities"})
    ranked: list[tuple[tuple[float, int, int, str], Match]] = []
    for node in graph.nodes.values():
        if (
            not node.active
            or node.kind != "paragraph"
            or not node.facts
            or (scopes and not _path_in_scopes(node.path, scopes))
        ):
            continue
        body = " ".join(str(fact) for fact in node.facts)
        normalized_path = node.path.replace("\\", "/").casefold()
        path_terms = set(plan_terms(normalized_path))
        if roadmap_intent and "roadmap" not in path_terms:
            continue
        row = _document_status_row(body)
        status, subject = row if row is not None else (None, "")
        if status not in wanted:
            continue
        if capability_intent and not subject:
            # Legend rows such as "`[ ]` absent" and task rows without a
            # capability field describe status syntax or work, not a named
            # capability.
            continue
        body_terms = set(plan_terms(f"{node.label} {body}"))
        overlap = len(query_terms & (path_terms | body_terms)) / max(1, len(query_terms))
        roadmap_path = int("roadmap" in path_terms)
        # The status marker is the hard gate. These continuous tie-breakers
        # choose the most query-local literal row without repository-specific
        # labels or score constants.
        score = 1.0 + overlap + roadmap_path
        match = Match(
            node,
            score,
            (
                "literal_document_status",
                "document_status:absent" if status == "" else "document_status:partial",
            ),
        )
        ranked.append((
            (
                -score,
                0 if roadmap_intent and roadmap_path else 1,
                node.line or 10**9,
                node.id,
            ),
            match,
        ))
    return tuple(match for _rank, match in sorted(ranked)[:12])

def _constrain_document_status_packet(
    graph: Graph,
    nodes: set[str],
    edges: list[Edge],
    evidence_ids: set[str],
) -> tuple[set[str], list[Edge]]:
    """Project a status query to matching rows plus their document ancestors."""
    keep = set(evidence_ids)
    for node_id in tuple(evidence_ids):
        node = graph.nodes.get(node_id)
        if node is not None and node.parent in graph.nodes:
            keep.add(str(node.parent))
    for edge in graph.edges:
        if edge.active and edge.type == "section_of" and edge.source in keep:
            if edge.target in graph.nodes:
                keep.add(edge.target)
    constrained_nodes = nodes & keep
    constrained_nodes.update(evidence_ids)
    constrained_nodes.update(node_id for node_id in keep if node_id in graph.nodes)
    constrained_edges = [
        edge
        for edge in edges
        if edge.source in constrained_nodes and edge.target in constrained_nodes
    ]
    # The expansion budget may stop at the section parent. Preserve its direct
    # section/file relation without reopening sibling paragraph expansion.
    seen = {(edge.source, edge.target, edge.type) for edge in constrained_edges}
    for edge in graph.edges:
        key = (edge.source, edge.target, edge.type)
        if (
            edge.active
            and edge.type in {"contains", "section_of"}
            and edge.source in constrained_nodes
            and edge.target in constrained_nodes
            and key not in seen
        ):
            constrained_edges.append(edge)
            seen.add(key)
    return constrained_nodes, constrained_edges
