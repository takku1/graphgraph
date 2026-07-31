"""Monotone type facts and bounded obligation discharge.

The lattice is the finite powerset of observed concrete type names:

    unknown (empty) < concrete (singleton) < ambiguous (two or more)

Join is set union, so propagation is monotone, deterministic, and terminates
once no binding gains evidence.  Attribute traversal is separately bounded;
this is deliberately not an unbounded whole-program fixpoint.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Mapping


class TypeState(str, Enum):
    UNKNOWN = "unknown"
    CONCRETE = "concrete"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True, order=True)
class Evidence:
    kind: str
    source: str


@dataclass(frozen=True)
class TypeFact:
    types: frozenset[str] = frozenset()
    evidence: tuple[Evidence, ...] = ()

    @classmethod
    def from_evidence(cls, type_name: str, evidence: Evidence) -> TypeFact:
        return cls(frozenset({type_name}), (evidence,)) if type_name else cls()

    @property
    def state(self) -> TypeState:
        if not self.types:
            return TypeState.UNKNOWN
        return TypeState.CONCRETE if len(self.types) == 1 else TypeState.AMBIGUOUS

    @property
    def concrete(self) -> str | None:
        return next(iter(self.types)) if len(self.types) == 1 else None

    def join(self, other: TypeFact) -> TypeFact:
        return TypeFact(
            self.types | other.types,
            tuple(sorted(set(self.evidence) | set(other.evidence))),
        )


@dataclass(frozen=True, order=True)
class TypeObligation:
    target: str
    root: str
    fields: tuple[str, ...] = ()
    provenance: str = "assignment"


@dataclass(frozen=True, order=True)
class UnresolvedTypeObligation:
    target: str
    root: str
    fields: tuple[str, ...]
    reason: str


@dataclass(frozen=True)
class TypeSolution:
    facts: Mapping[str, TypeFact]
    unresolved: tuple[UnresolvedTypeObligation, ...]

    @property
    def concrete_types(self) -> dict[str, str]:
        return {
            binding: concrete
            for binding, fact in sorted(self.facts.items())
            if (concrete := fact.concrete) is not None
        }


def solve_type_obligations(
    seeds: Iterable[tuple[str, str, Evidence]],
    obligations: Iterable[TypeObligation],
    field_types: Mapping[tuple[str, str], str],
    *,
    max_attribute_depth: int,
) -> TypeSolution:
    """Join facts and discharge only obligations affected by changed roots."""
    if max_attribute_depth < 0:
        raise ValueError("max_attribute_depth must be non-negative")

    facts: dict[str, TypeFact] = {}
    for binding, type_name, evidence in seeds:
        current = facts.get(binding, TypeFact())
        facts[binding] = current.join(TypeFact.from_evidence(type_name, evidence))

    ordered = tuple(sorted(set(obligations)))
    dependents: dict[str, list[TypeObligation]] = defaultdict(list)
    for obligation in ordered:
        dependents[obligation.root].append(obligation)

    queue = deque(ordered)
    queued = set(ordered)
    while queue:
        obligation = queue.popleft()
        queued.discard(obligation)
        if len(obligation.fields) > max_attribute_depth:
            continue
        root_fact = facts.get(obligation.root, TypeFact())
        root_type = root_fact.concrete
        if root_type is None:
            continue
        resolved = root_type
        for field in obligation.fields:
            resolved = field_types.get((resolved, field), "")
            if not resolved:
                break
        if not resolved:
            continue
        candidate = TypeFact(
            frozenset({resolved}),
            tuple(
                sorted(
                    set(root_fact.evidence)
                    | {Evidence(obligation.provenance, _obligation_expression(obligation))}
                )
            ),
        )
        previous = facts.get(obligation.target, TypeFact())
        joined = previous.join(candidate)
        if joined == previous:
            continue
        facts[obligation.target] = joined
        for dependent in dependents.get(obligation.target, ()):
            if dependent not in queued:
                queue.append(dependent)
                queued.add(dependent)

    unresolved: list[UnresolvedTypeObligation] = []
    for obligation in ordered:
        reason = _unresolved_reason(
            obligation,
            facts,
            field_types,
            max_attribute_depth=max_attribute_depth,
        )
        if reason:
            unresolved.append(
                UnresolvedTypeObligation(
                    obligation.target,
                    obligation.root,
                    obligation.fields,
                    reason,
                )
            )
    return TypeSolution(dict(sorted(facts.items())), tuple(unresolved))


def _obligation_expression(obligation: TypeObligation) -> str:
    return ".".join((obligation.root, *obligation.fields))


def _unresolved_reason(
    obligation: TypeObligation,
    facts: Mapping[str, TypeFact],
    field_types: Mapping[tuple[str, str], str],
    *,
    max_attribute_depth: int,
) -> str:
    if len(obligation.fields) > max_attribute_depth:
        return "depth_limit"
    root = facts.get(obligation.root, TypeFact())
    if root.state is TypeState.UNKNOWN:
        return "unknown_root"
    if root.state is TypeState.AMBIGUOUS:
        return "ambiguous_root"
    resolved = root.concrete or ""
    for field in obligation.fields:
        resolved = field_types.get((resolved, field), "")
        if not resolved:
            return "unknown_field"
    target = facts.get(obligation.target, TypeFact())
    if target.state is TypeState.AMBIGUOUS:
        return "ambiguous_target"
    return ""
