"""Compile unrestricted user text into a small, typed read-only query plan.

The compiler is intentionally conservative.  Exact operators are selected only
when the request can be represented without dropping a clause; everything else
falls back to the existing context compiler.  Mutating lifecycle operations are
never inferred from prose.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum

QUERY_COMPILER_VERSION = "query_compiler_v1_conservative_read_only"


class QueryOperator(str, Enum):
    CONTEXT = "context"
    RELATIONS = "relations"
    SELECT = "select"
    SEARCH = "search"
    STATUS = "status"


@dataclass(frozen=True)
class QueryPlan:
    operator: QueryOperator
    confidence: float
    arguments: dict[str, object] = field(default_factory=dict)
    reasons: tuple[str, ...] = ()
    fallback: QueryOperator | None = None
    cost_class: str = "ranked_retrieval"
    mutating: bool = False
    compiler_version: str = QUERY_COMPILER_VERSION


_TARGET = r"[A-Za-z_$][\w$]*(?:(?:::|[.#/])[A-Za-z_$][\w$]*)*"
_RELATION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "callers",
        re.compile(
            rf"^(?:what|who)\s+calls?\s+(?P<target>{_TARGET})\s*[?!.]*$",
            re.IGNORECASE,
        ),
    ),
    (
        "callers",
        re.compile(
            rf"^(?:show|list|find)?\s*(?:the\s+)?callers?\s+(?:of|for)\s+(?P<target>{_TARGET})\s*[?!.]*$",
            re.IGNORECASE,
        ),
    ),
    (
        "callees",
        re.compile(
            rf"^what\s+does\s+(?P<target>{_TARGET})\s+calls?\s*[?!.]*$",
            re.IGNORECASE,
        ),
    ),
    (
        "callees",
        re.compile(
            rf"^(?:show|list|find)?\s*(?:the\s+)?callees?\s+(?:of|for)\s+(?P<target>{_TARGET})\s*[?!.]*$",
            re.IGNORECASE,
        ),
    ),
)

_MUTATION_REQUEST = re.compile(
    r"^(?:please\s+)?(?:delete|remove|build|rebuild|update|index|scan|export|migrate)\b",
    re.IGNORECASE,
)
_STATUS_INTENT = re.compile(
    r"\b(?:project\s+status|graph\s+(?:status|health)|healthy|fresh|stale|doctor)\b",
    re.IGNORECASE,
)
_SEARCH_INTENT = re.compile(
    rf"^(?:find|locate|search\s+for)\s+(?:the\s+)?(?:symbol|node|path|file)?\s*(?P<target>{_TARGET})\s*[?!.]*$",
    re.IGNORECASE,
)
_PREDICATE_FIELD = re.compile(
    r"(?:^|\band\s+)(?:production_callers|callers|kind|path|crate|label|include_tests)\s*(?:=|!=|>=|<=|>|<|\bcontains\b|\bexcludes\b|\bin\s*\[)",
    re.IGNORECASE,
)
_COMPOUND_INTENT = re.compile(
    r"\b(?:and|also|then)\b.*\b(?:tests?|change|impact|path|explain|why|how|status|count)\b",
    re.IGNORECASE,
)


def _relation_arguments(query: str) -> dict[str, object] | None:
    for direction, pattern in _RELATION_PATTERNS:
        match = pattern.fullmatch(query.strip())
        if match:
            return {
                "target": match.group("target").rstrip("?.!"),
                "direction": direction,
            }
    return None


def _validated_predicate(query: str) -> bool:
    if not _PREDICATE_FIELD.search(query):
        return False
    from ..retrieval.predicates import parse_criteria

    try:
        parse_criteria(query)
    except ValueError:
        return False
    return True


def compile_query(
    query: str,
    *,
    mode: str = "auto",
    result_mode: str = "select",
    target: str = "",
    direction: str = "",
    predicate: str = "",
) -> QueryPlan:
    """Return a deterministic, language-agnostic read-only operator plan."""
    text = " ".join((query or "").split())
    requested = (mode or "auto").strip().casefold()
    valid_modes = {"auto", *(operator.value for operator in QueryOperator)}
    if requested not in valid_modes:
        raise ValueError(
            f"unknown query mode: {mode!r}; expected one of {', '.join(sorted(valid_modes))}"
        )
    if result_mode not in {"select", "count", "exists"}:
        raise ValueError("result_mode must be select, count, or exists")

    if requested != "auto":
        operator = QueryOperator(requested)
        arguments: dict[str, object] = {"query": text}
        if operator is QueryOperator.RELATIONS:
            relation = (
                {"target": target, "direction": direction}
                if target and direction
                else _relation_arguments(text)
            )
            if not relation or relation.get("direction") not in {"callers", "callees"}:
                raise ValueError(
                    "relations mode requires an exact callers/callees question or explicit target and direction"
                )
            arguments = relation
        elif operator is QueryOperator.SELECT:
            expression = predicate or text
            if not _validated_predicate(expression):
                raise ValueError("select mode requires a fully supported typed predicate")
            arguments = {"predicate": expression, "mode": result_mode}
        elif operator is QueryOperator.SEARCH:
            arguments = {"query": target or text}
        return QueryPlan(
            operator=operator,
            confidence=1.0,
            arguments=arguments,
            reasons=("explicit operator override",),
            cost_class={
                QueryOperator.RELATIONS: "indexed_one_hop",
                QueryOperator.SELECT: "whole_graph_filter",
                QueryOperator.SEARCH: "indexed_search",
                QueryOperator.STATUS: "metadata",
            }.get(operator, "ranked_retrieval"),
        )

    if _MUTATION_REQUEST.search(text):
        return QueryPlan(
            QueryOperator.CONTEXT,
            0.2,
            {"query": text},
            ("mutation language is never executed by the read-only query facade",),
        )
    if _STATUS_INTENT.search(text):
        return QueryPlan(
            QueryOperator.STATUS,
            0.95,
            {"query": text},
            ("project-health intent",),
            cost_class="metadata",
        )
    if _validated_predicate(text):
        return QueryPlan(
            QueryOperator.SELECT,
            0.99,
            {"predicate": text, "mode": result_mode},
            ("complete typed predicate validated",),
            cost_class="whole_graph_filter",
        )
    if _COMPOUND_INTENT.search(text):
        return QueryPlan(
            QueryOperator.CONTEXT,
            0.9,
            {"query": text},
            ("compound request requires facet-aware context retrieval",),
        )
    if relation := _relation_arguments(text):
        return QueryPlan(
            QueryOperator.RELATIONS,
            0.99,
            relation,
            ("exact one-target one-hop relation",),
            fallback=QueryOperator.CONTEXT,
            cost_class="indexed_one_hop",
        )
    if match := _SEARCH_INTENT.fullmatch(text):
        return QueryPlan(
            QueryOperator.SEARCH,
            0.95,
            {"query": match.group("target")},
            ("exact location intent",),
            fallback=QueryOperator.CONTEXT,
            cost_class="indexed_search",
        )
    return QueryPlan(
        QueryOperator.CONTEXT,
        0.7,
        {"query": text},
        ("no lossless specialized operator; use general retrieval",),
    )


__all__ = [
    "QUERY_COMPILER_VERSION",
    "QueryOperator",
    "QueryPlan",
    "compile_query",
]
