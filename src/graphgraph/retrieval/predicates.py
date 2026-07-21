"""Set-predicate queries over the whole graph.

Every other retrieval entry point is anchored on a named node, so a
whole-repo question ("which symbols have no production caller?") becomes N
round trips. This module answers it in one pass, and adds ``count`` and
``exists`` result modes for the common case where the answer is an integer
or a boolean rather than a subgraph.

The caller distinction is the point. A symbol referenced only by its own
tests is not "used" in the sense that matters for dead-code and island work,
and hand-rolling that split with shell arithmetic is what produced two
contradictory published figures in the field report
(``docs/bugs/2026-07-20-call-resolution-and-agent-throughput.md``, P4).

Only ``calls`` edges count as callers. ``calls_candidate`` is deliberately
excluded: it is weak, non-traversable, name-only evidence, so admitting it
would let a guess mask a genuinely uncalled symbol -- the exact direction of
error this query shape must not make.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Literal

from ..graph.core import Graph, Node
from .scoping import _is_test_node

# Kinds that name a callable symbol. Files, docs, and concepts are not
# candidates for "does this have a caller".
SELECTABLE_KINDS = ("function", "method", "class")

ResultMode = Literal["select", "count", "exists"]


@dataclass(frozen=True)
class SelectionCriteria:
    """A whole-graph predicate. Unset fields do not constrain."""

    kinds: tuple[str, ...] = SELECTABLE_KINDS
    path_contains: str = ""
    label_contains: str = ""
    production_callers: int | None = None
    callers: int | None = None
    include_tests: bool = True
    limit: int = 200


@dataclass
class SelectionResult:
    """Answer to a set-predicate query, plus how it was computed."""

    mode: ResultMode
    total: int
    symbols: list[dict] = field(default_factory=list)
    truncated: bool = False
    criteria_detail: str = ""
    caller_evidence: str = ""
    caller_evidence_complete: bool = True

    @property
    def exists(self) -> bool:
        return self.total > 0


def caller_evidence_quality(graph: Graph) -> tuple[bool, str]:
    """Report how far caller counts can be trusted on this graph.

    A "no caller" answer is only as good as call resolution. Where member
    calls lack receiver evidence they produce no ``calls`` edge, so an
    unresolved method is indistinguishable from an uncalled one and
    ``production_callers = 0`` over-reports. Callers of this module are
    making dead-code and island decisions, so that ceiling has to travel
    with the answer rather than being discoverable only via
    ``project_status``.
    """
    metadata = graph.metadata or {}

    def _count(name: str) -> int:
        for key in (f"member_calls_{name}", f"member_calls_global_{name}"):
            raw = metadata.get(key)
            if raw not in (None, ""):
                try:
                    return int(raw)
                except (TypeError, ValueError):
                    continue
        return 0

    resolved = _count("resolved")
    unknown = _count("unknown_receiver")
    ambiguous = _count("ambiguous")
    typed_eligible = resolved + unknown + ambiguous
    if typed_eligible <= 0:
        return True, "no member-call telemetry on this graph"
    ratio = resolved / typed_eligible
    if unknown == 0:
        return True, f"member-call resolution complete ({resolved}/{typed_eligible})"
    return False, (
        f"member-call resolution {ratio:.1%} ({resolved}/{typed_eligible}); "
        f"{unknown} call sites lack receiver evidence and produce no calls edge, "
        "so zero-caller counts are an upper bound on dead code, not a proof"
    )


def caller_counts(graph: Graph) -> tuple[dict[str, int], dict[str, int]]:
    """Return (all_callers, production_callers) keyed by target node id.

    A caller is counted once per distinct calling symbol, not per call site:
    "has a production caller" is a property of the call graph, and counting
    sites would make one caller in a loop look like many. Self-recursion is
    excluded for the same reason -- it is not evidence of external use.
    """
    all_callers: dict[str, set[str]] = {}
    production: dict[str, set[str]] = {}
    for edge in graph.edges:
        if not edge.active or edge.type != "calls" or edge.source == edge.target:
            continue
        source = graph.nodes.get(edge.source)
        if source is None:
            continue
        all_callers.setdefault(edge.target, set()).add(edge.source)
        if not _is_test_node(source):
            production.setdefault(edge.target, set()).add(edge.source)
    return (
        {nid: len(v) for nid, v in all_callers.items()},
        {nid: len(v) for nid, v in production.items()},
    )


def _matches(
    node: Node,
    criteria: SelectionCriteria,
    all_count: int,
    prod_count: int,
) -> bool:
    if not node.active or node.kind not in criteria.kinds:
        return False
    if criteria.path_contains and criteria.path_contains not in (node.path or ""):
        return False
    if criteria.label_contains and criteria.label_contains.casefold() not in node.label.casefold():
        return False
    if not criteria.include_tests and _is_test_node(node):
        return False
    if criteria.production_callers is not None and prod_count != criteria.production_callers:
        return False
    if criteria.callers is not None and all_count != criteria.callers:
        return False
    return True


def select_symbols(
    graph: Graph,
    criteria: SelectionCriteria,
    *,
    mode: ResultMode = "select",
) -> SelectionResult:
    """Evaluate *criteria* across the whole graph in a single pass.

    ``count`` and ``exists`` never materialize node payloads; ``exists``
    additionally stops at the first match.
    """
    all_counts, prod_counts = caller_counts(graph)
    matched: list[Node] = []
    total = 0
    for node in graph.nodes.values():
        if not _matches(node, criteria, all_counts.get(node.id, 0), prod_counts.get(node.id, 0)):
            continue
        total += 1
        if mode == "exists":
            break
        if mode == "select" and len(matched) < max(0, criteria.limit):
            matched.append(node)

    complete, evidence = caller_evidence_quality(graph)
    result = SelectionResult(
        mode=mode,
        total=total,
        truncated=mode == "select" and total > len(matched),
        criteria_detail=describe_criteria(criteria),
        caller_evidence=evidence,
        caller_evidence_complete=complete,
    )
    if mode == "select":
        matched.sort(key=lambda node: (node.path or "", node.line or 0, node.label))
        result.symbols = [
            {
                "id": node.id,
                "label": node.label,
                "kind": node.kind,
                "path": node.path,
                "line": node.line,
                "callers": all_counts.get(node.id, 0),
                "production_callers": prod_counts.get(node.id, 0),
                "is_test": _is_test_node(node),
            }
            for node in matched
        ]
    return result


def describe_criteria(criteria: SelectionCriteria) -> str:
    parts: list[str] = [f"kind in {list(criteria.kinds)}"]
    if criteria.path_contains:
        parts.append(f"path contains {criteria.path_contains!r}")
    if criteria.label_contains:
        parts.append(f"label contains {criteria.label_contains!r}")
    if criteria.production_callers is not None:
        parts.append(f"production_callers = {criteria.production_callers}")
    if criteria.callers is not None:
        parts.append(f"callers = {criteria.callers}")
    if not criteria.include_tests:
        parts.append("excluding test symbols")
    return " and ".join(parts)


def parse_criteria(expression: str, *, limit: int = 200) -> SelectionCriteria:
    """Parse a small ``where``-style predicate expression.

    Accepts ``field = value`` clauses joined by ``and``::

        production_callers = 0 and path contains locus-engine and kind = method

    Deliberately tiny: this is a filter language, not a query language.
    Anything it cannot express raises rather than being silently
    approximated, because a quietly-wrong set answer is the failure mode this
    whole surface exists to prevent.
    """
    text = expression.strip()
    if text.casefold().startswith("where "):
        text = text[len("where "):].strip()

    kinds: list[str] = []
    path_contains = ""
    label_contains = ""
    production_callers: int | None = None
    callers: int | None = None
    include_tests = True

    for raw_clause in _split_clauses(text):
        clause = raw_clause.strip()
        if not clause:
            continue
        field_name, operator, value = _parse_clause(clause)
        if field_name in {"path", "crate"} and operator == "contains":
            path_contains = value
        elif field_name == "label" and operator == "contains":
            label_contains = value
        elif field_name == "kind" and operator == "=":
            kinds.append(value)
        elif field_name == "production_callers" and operator == "=":
            production_callers = _as_int(value, field_name)
        elif field_name == "callers" and operator == "=":
            callers = _as_int(value, field_name)
        elif field_name == "include_tests" and operator == "=":
            include_tests = value.casefold() not in {"false", "no", "0"}
        else:
            raise ValueError(
                f"unsupported predicate clause: {clause!r} (supported: "
                "production_callers=N, callers=N, kind=K, path contains S, "
                "crate contains S, label contains S, include_tests=BOOL)"
            )

    return SelectionCriteria(
        kinds=tuple(kinds) if kinds else SELECTABLE_KINDS,
        path_contains=path_contains,
        label_contains=label_contains,
        production_callers=production_callers,
        callers=callers,
        include_tests=include_tests,
        limit=limit,
    )


def _split_clauses(text: str) -> Iterable[str]:
    """Split on top-level ``and``, case-insensitively."""
    lowered = text.casefold()
    parts: list[str] = []
    start = 0
    index = 0
    while index < len(lowered):
        if lowered.startswith(" and ", index):
            parts.append(text[start:index])
            index += len(" and ")
            start = index
            continue
        index += 1
    parts.append(text[start:])
    return parts


def _parse_clause(clause: str) -> tuple[str, str, str]:
    lowered = clause.casefold()
    if " contains " in lowered:
        position = lowered.index(" contains ")
        return (
            clause[:position].strip().casefold(),
            "contains",
            clause[position + len(" contains "):].strip().strip("'\""),
        )
    if "=" in clause:
        name, _, value = clause.partition("=")
        return name.strip().casefold(), "=", value.strip().strip("'\"")
    raise ValueError(f"unsupported predicate clause: {clause!r}")


def _as_int(value: str, field_name: str) -> int:
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} expects an integer, got {value!r}") from exc
