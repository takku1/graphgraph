"""Exact-oracle laboratory for global-project-attention hypotheses.

This module deliberately does not participate in production retrieval. It
defines small-graph mathematical ceilings and receipts against which proposed
multiresolution candidates can be tested before integration.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import fsum, log2
from typing import Iterable, Mapping

from ..graph.core import Graph
from ..graph.coupling import EDGE_COUPLINGS, coupled_graph


class Hierarchy:
    """A rooted forest whose leaves are project entities and internals are cells."""

    def __init__(self, children: Mapping[str, Iterable[str]], roots: Iterable[str]):
        self.children = {node: tuple(items) for node, items in children.items()}
        self.roots = tuple(roots)
        self._leaf_cache: dict[str, frozenset[str]] = {}
        self._validate()

    def _validate(self) -> None:
        if not self.roots:
            raise ValueError("hierarchy requires at least one root")
        if len(set(self.roots)) != len(self.roots):
            raise ValueError("hierarchy roots must be unique")
        parents: dict[str, str] = {}
        for parent, children in self.children.items():
            if not children:
                raise ValueError(f"internal cell {parent!r} has no children")
            if len(set(children)) != len(children):
                raise ValueError(f"internal cell {parent!r} repeats a child")
            for child in children:
                if child == parent:
                    raise ValueError(f"hierarchy cycle at {parent!r}")
                if child in parents:
                    raise ValueError(f"hierarchy node {child!r} has multiple parents")
                parents[child] = parent
        for root in self.roots:
            if root in parents:
                raise ValueError(f"root {root!r} also has a parent")

        visited: set[str] = set()
        active: set[str] = set()

        def walk(node: str) -> None:
            if node in active:
                raise ValueError(f"hierarchy cycle at {node!r}")
            if node in visited:
                return
            active.add(node)
            for child in self.children.get(node, ()):
                walk(child)
            active.remove(node)
            visited.add(node)

        for root in self.roots:
            walk(root)
        unreachable = set(self.children) - visited
        if unreachable:
            raise ValueError(f"unreachable hierarchy cells: {sorted(unreachable)}")

    @property
    def nodes(self) -> frozenset[str]:
        values = set(self.roots)
        for parent, children in self.children.items():
            values.add(parent)
            values.update(children)
        return frozenset(values)

    @property
    def leaves(self) -> frozenset[str]:
        return frozenset(node for node in self.nodes if node not in self.children)

    def cell_leaves(self, cell: str) -> frozenset[str]:
        if cell not in self.nodes:
            raise ValueError(f"unknown hierarchy cell {cell!r}")
        cached = self._leaf_cache.get(cell)
        if cached is not None:
            return cached
        if cell not in self.children:
            result = frozenset({cell})
        else:
            result = frozenset().union(*(self.cell_leaves(child) for child in self.children[cell]))
        self._leaf_cache[cell] = result
        return result


@dataclass(frozen=True)
class CoverPlan:
    """One non-overlapping hierarchy antichain plus sparse exact exceptions."""

    cover: tuple[str, ...]
    residual: frozenset[str] = frozenset()

    @property
    def representation_units(self) -> int:
        return len(self.cover) + len(self.residual)


def _normalized_field(field: Mapping[str, float], universe: frozenset[str]) -> dict[str, float]:
    unknown = set(field) - set(universe)
    if unknown:
        raise ValueError(f"field contains unknown entities: {sorted(unknown)}")
    values = {node: float(field.get(node, 0.0)) for node in universe}
    if any(value < 0.0 for value in values.values()):
        raise ValueError("influence mass must be non-negative")
    total = fsum(values.values())
    if total <= 0.0:
        raise ValueError("influence field must have positive total mass")
    return {node: value / total for node, value in values.items()}


def exact_influence_field(
    graph: Graph,
    seeds: Mapping[str, float],
    *,
    damping: float = 0.85,
    max_iter: int = 1000,
    tolerance: float = 1e-12,
) -> dict[str, float]:
    """Compute the small-graph exact-PPR oracle used only by research tests."""
    field = graph.personalized_pagerank(
        dict(seeds),
        damping=damping,
        max_iter=max_iter,
        tol=tolerance,
    )
    active = frozenset(node_id for node_id, node in graph.nodes.items() if node.active)
    return _normalized_field(field, active)


# Re-exported so research call sites keep one name for the stage while the
# implementation stays in production, where the hybrid representation also
# needs it. Research may depend on production; production never on research.
FIELD_COUPLINGS = EDGE_COUPLINGS


def influence_field(
    graph: Graph,
    seeds: Mapping[str, float],
    *,
    coupling: str = "directed",
    damping: float = 0.85,
    max_iter: int = 30,
    tolerance: float = 1e-7,
) -> dict[str, float]:
    """Query-conditioned influence field under a selectable edge coupling.

    The coupling is the stage under test: every downstream cover, refinement,
    and packet formula consumes this field unchanged, so swapping it isolates
    the substrate from the representation built on top of it.
    """
    coupled = coupled_graph(graph, coupling)
    field = coupled.personalized_pagerank(dict(seeds), damping=damping, max_iter=max_iter, tol=tolerance)
    active = frozenset(node_id for node_id, node in graph.nodes.items() if node.active)
    return _normalized_field(field, active)


def field_support_receipt(field: Mapping[str, float], *, top_k: int = 64) -> dict[str, object]:
    """Machine-checkable degeneracy receipt for an influence field.

    ``GPA-DEF-001`` requires every entity to carry nonzero query-conditioned
    influence. ``support_fraction`` measures how far a field is from that
    definition, and the mass/entropy terms distinguish "spread but peaked"
    from "collapsed onto a handful of entities".
    """
    values = [max(0.0, float(value)) for value in field.values()]
    universe = len(values)
    if universe == 0:
        raise ValueError("field support receipt requires a non-empty field")
    total = fsum(values)
    if total <= 0.0:
        raise ValueError("field support receipt requires positive total mass")
    normalized = sorted((value / total for value in values), reverse=True)
    support = sum(1 for value in normalized if value > 0.0)
    entropy = -fsum(value * log2(value) for value in normalized if value > 0.0)
    return {
        "universe": universe,
        "support": support,
        "support_fraction": support / universe,
        "top_k": top_k,
        "mass_in_top_k": fsum(normalized[:top_k]),
        "mass_outside_top_k": max(0.0, 1.0 - fsum(normalized[:top_k])),
        "entropy_bits": entropy,
        # 2**entropy: how many equally-weighted entities the field behaves like.
        "effective_entities": 2.0**entropy,
        "max_mass": normalized[0],
    }


def coverage_receipt(hierarchy: Hierarchy, plan: CoverPlan) -> dict[str, object]:
    counts = {leaf: 0 for leaf in hierarchy.leaves}
    unknown: set[str] = set()
    for cell in plan.cover:
        if cell not in hierarchy.nodes:
            unknown.add(cell)
            continue
        for leaf in hierarchy.cell_leaves(cell):
            counts[leaf] += 1
    for leaf in plan.residual:
        if leaf not in counts:
            unknown.add(leaf)
        else:
            counts[leaf] += 1
    missing = tuple(sorted(leaf for leaf, count in counts.items() if count == 0))
    duplicate = tuple(sorted(leaf for leaf, count in counts.items() if count > 1))
    represented = sum(count > 0 for count in counts.values())
    valid = not missing and not duplicate and not unknown
    return {
        "valid": valid,
        "universe": len(counts),
        "represented": represented,
        "coverage": represented / max(1, len(counts)),
        "missing": missing,
        "duplicate": duplicate,
        "unknown": tuple(sorted(unknown)),
        "representation_units": plan.representation_units,
    }


def _cell_squared_error(hierarchy: Hierarchy, field: Mapping[str, float], cell: str) -> float:
    leaves = hierarchy.cell_leaves(cell)
    mean = fsum(field[leaf] for leaf in leaves) / len(leaves)
    return fsum((field[leaf] - mean) ** 2 for leaf in leaves)


def _cell_formula_cost(
    hierarchy: Hierarchy,
    field: Mapping[str, float],
    cell: str,
    exactness_weight: float,
    resolution_weight: float = 0.0,
) -> float:
    if cell not in hierarchy.children:
        return 0.0
    mass = fsum(field[leaf] for leaf in hierarchy.cell_leaves(cell))
    leaf_count = len(hierarchy.cell_leaves(cell))
    universe_count = len(hierarchy.leaves)
    normalized_log_size = log2(leaf_count) / log2(universe_count) if leaf_count > 1 and universe_count > 1 else 0.0
    return (
        _cell_squared_error(hierarchy, field, cell)
        + exactness_weight * mass
        + resolution_weight * mass * normalized_log_size
    )


def _subtree_options(
    hierarchy: Hierarchy,
    field: Mapping[str, float],
    cell: str,
    max_units: int,
    exactness_weight: float = 0.0,
    resolution_weight: float = 0.0,
) -> dict[int, tuple[float, tuple[str, ...]]]:
    options = {
        1: (
            _cell_formula_cost(
                hierarchy,
                field,
                cell,
                exactness_weight,
                resolution_weight,
            ),
            (cell,),
        )
    }
    children = hierarchy.children.get(cell)
    if not children:
        return options
    combined: dict[int, tuple[float, tuple[str, ...]]] = {0: (0.0, ())}
    for child in children:
        child_options = _subtree_options(
            hierarchy,
            field,
            child,
            max_units,
            exactness_weight,
            resolution_weight,
        )
        next_combined: dict[int, tuple[float, tuple[str, ...]]] = {}
        for left_cost, (left_error, left_cover) in combined.items():
            for right_cost, (right_error, right_cover) in child_options.items():
                cost = left_cost + right_cost
                if cost > max_units:
                    continue
                candidate = (left_error + right_error, left_cover + right_cover)
                incumbent = next_combined.get(cost)
                if incumbent is None or candidate < incumbent:
                    next_combined[cost] = candidate
        combined = next_combined
    for cost, candidate in combined.items():
        incumbent = options.get(cost)
        if incumbent is None or candidate < incumbent:
            options[cost] = candidate
    return options


def compile_optimal_cover(hierarchy: Hierarchy, field: Mapping[str, float], max_units: int) -> CoverPlan:
    """Return the exhaustive L2-optimal hierarchy cover for a small graph.

    Aggregate cells preserve their oracle total mass and distribute it uniformly
    over member leaves. This is a mathematical ceiling, not a deployable query
    algorithm: a production candidate must estimate those masses without the
    answer key.
    """
    if max_units < len(hierarchy.roots):
        raise ValueError("max_units cannot be smaller than the root count")
    oracle = _normalized_field(field, hierarchy.leaves)
    combined: dict[int, tuple[float, tuple[str, ...]]] = {0: (0.0, ())}
    for root in hierarchy.roots:
        root_options = _subtree_options(hierarchy, oracle, root, max_units)
        next_combined: dict[int, tuple[float, tuple[str, ...]]] = {}
        for left_cost, (left_error, left_cover) in combined.items():
            for right_cost, (right_error, right_cover) in root_options.items():
                cost = left_cost + right_cost
                if cost > max_units:
                    continue
                candidate = (left_error + right_error, left_cover + right_cover)
                incumbent = next_combined.get(cost)
                if incumbent is None or candidate < incumbent:
                    next_combined[cost] = candidate
        combined = next_combined
    if not combined:
        raise ValueError("no hierarchy cover fits max_units")
    _cost, (_error, cover) = min(combined.items(), key=lambda item: (item[1][0], item[0], item[1][1]))
    return CoverPlan(tuple(sorted(cover)))


def compile_optimal_formula_cover(
    hierarchy: Hierarchy,
    field: Mapping[str, float],
    max_units: int,
    *,
    exactness_weight: float,
    resolution_weight: float = 0.0,
) -> CoverPlan:
    """Minimize L2 plus unresolved-mass and log-resolution penalties exactly.

    The objective is additive over aggregate cells::

        J(P) = sum_K [L2(K) + exactness_weight * mass(K)
                      + resolution_weight * mass(K) * normalized_log_size(K)]

    Leaves have zero cost. The influence field is a candidate input; gold task
    evidence is deliberately absent from this interface.
    """
    if exactness_weight < 0.0 or resolution_weight < 0.0:
        raise ValueError("formula weights must be non-negative")
    if max_units < len(hierarchy.roots):
        raise ValueError("max_units cannot be smaller than the root count")
    field = _normalized_field(field, hierarchy.leaves)
    combined: dict[int, tuple[float, tuple[str, ...]]] = {0: (0.0, ())}
    for root in hierarchy.roots:
        root_options = _subtree_options(
            hierarchy,
            field,
            root,
            max_units,
            exactness_weight,
            resolution_weight,
        )
        next_combined: dict[int, tuple[float, tuple[str, ...]]] = {}
        for left_cost, (left_error, left_cover) in combined.items():
            for right_cost, (right_error, right_cover) in root_options.items():
                cost = left_cost + right_cost
                if cost > max_units:
                    continue
                candidate = (left_error + right_error, left_cover + right_cover)
                incumbent = next_combined.get(cost)
                if incumbent is None or candidate < incumbent:
                    next_combined[cost] = candidate
        combined = next_combined
    if not combined:
        raise ValueError("no hierarchy cover fits max_units")
    _cost, (_objective, cover) = min(
        combined.items(),
        key=lambda item: (item[1][0], item[0], item[1][1]),
    )
    return CoverPlan(tuple(sorted(cover)))


def compile_greedy_cover(hierarchy: Hierarchy, field: Mapping[str, float], max_units: int) -> CoverPlan:
    """Greedily refine the cell with greatest immediate L2-error reduction per unit."""
    return compile_greedy_formula_cover(
        hierarchy,
        field,
        max_units,
        exactness_weight=0.0,
    )


def compile_greedy_formula_cover(
    hierarchy: Hierarchy,
    field: Mapping[str, float],
    max_units: int,
    *,
    exactness_weight: float,
    resolution_weight: float = 0.0,
) -> CoverPlan:
    """Greedily reduce the declared formula objective per added unit.

    This is a scalable candidate, not an optimality claim. Phase 0 already
    contains a counterexample for one-step greedy refinement.
    """
    if exactness_weight < 0.0 or resolution_weight < 0.0:
        raise ValueError("formula weights must be non-negative")
    if max_units < len(hierarchy.roots):
        raise ValueError("max_units cannot be smaller than the root count")
    oracle = _normalized_field(field, hierarchy.leaves)
    cover = set(hierarchy.roots)
    cost_cache: dict[str, float] = {}

    def cell_cost(cell: str) -> float:
        cached = cost_cache.get(cell)
        if cached is None:
            cached = _cell_formula_cost(
                hierarchy,
                oracle,
                cell,
                exactness_weight,
                resolution_weight,
            )
            cost_cache[cell] = cached
        return cached

    while True:
        choices: list[tuple[float, float, str, int]] = []
        for cell in cover:
            children = hierarchy.children.get(cell)
            if not children:
                continue
            extra_units = len(children) - 1
            if len(cover) + extra_units > max_units:
                continue
            current_error = cell_cost(cell)
            refined_error = fsum(cell_cost(child) for child in children)
            gain = max(0.0, current_error - refined_error)
            choices.append((gain / max(1, extra_units), gain, cell, extra_units))
        if not choices:
            break
        _ratio, gain, cell, _extra = max(choices, key=lambda item: (item[0], item[1], item[2]))
        if gain <= 1e-18:
            break
        cover.remove(cell)
        cover.update(hierarchy.children[cell])
    return CoverPlan(tuple(sorted(cover)))


def _approximate_field(
    hierarchy: Hierarchy,
    oracle: Mapping[str, float],
    plan: CoverPlan,
) -> dict[str, float]:
    approximation = {leaf: 0.0 for leaf in hierarchy.leaves}
    for cell in plan.cover:
        leaves = hierarchy.cell_leaves(cell)
        mass = fsum(oracle[leaf] for leaf in leaves)
        share = mass / len(leaves)
        for leaf in leaves:
            approximation[leaf] = share
    for leaf in plan.residual:
        approximation[leaf] = oracle[leaf]
    return approximation


def evaluate_cover(hierarchy: Hierarchy, field: Mapping[str, float], plan: CoverPlan) -> dict[str, object]:
    oracle = _normalized_field(field, hierarchy.leaves)
    coverage = coverage_receipt(hierarchy, plan)
    if not coverage["valid"]:
        raise ValueError(f"invalid coverage plan: {coverage}")
    approximation = _approximate_field(hierarchy, oracle, plan)
    exact = set(plan.residual)
    exact.update(cell for cell in plan.cover if cell not in hierarchy.children)
    exact_mass = fsum(oracle[leaf] for leaf in exact)
    aggregate_mass = 1.0 - exact_mass
    l1 = fsum(abs(oracle[leaf] - approximation[leaf]) for leaf in hierarchy.leaves)
    l2 = fsum((oracle[leaf] - approximation[leaf]) ** 2 for leaf in hierarchy.leaves)
    rwc = exact_mass
    cell_receipts = []
    for cell in plan.cover:
        if cell not in hierarchy.children:
            continue
        leaves = hierarchy.cell_leaves(cell)
        mass = fsum(oracle[leaf] for leaf in leaves)
        share = mass / len(leaves)
        total_variation = 0.5 * fsum(abs(oracle[leaf] - share) for leaf in leaves)
        fidelity = 1.0 if mass <= 0.0 else max(0.0, 1.0 - total_variation / mass)
        rwc += mass * fidelity
        cell_receipts.append({"cell": cell, "leaves": len(leaves), "mass": mass, "fidelity": fidelity})
    return {
        "coverage": coverage,
        "l1_error": l1,
        "l2_error": l2,
        "mass_error": abs(1.0 - fsum(approximation.values())),
        "exact_attention_mass_capture": exact_mass,
        "aggregate_mass": aggregate_mass,
        "resolution_weighted_coverage": rwc,
        "cells": cell_receipts,
        "approximation": approximation,
    }


def effective_influence_receipt(
    hierarchy: Hierarchy,
    field: Mapping[str, float],
    plan: CoverPlan,
    *,
    minimum_mass: float,
) -> dict[str, object]:
    """Report non-vacuous influence above a declared oracle-mass threshold."""
    if minimum_mass < 0.0 or minimum_mass > 1.0:
        raise ValueError("minimum_mass must be between zero and one")
    oracle = _normalized_field(field, hierarchy.leaves)
    coverage = coverage_receipt(hierarchy, plan)
    if not coverage["valid"]:
        raise ValueError(f"invalid coverage plan: {coverage}")
    exact = set(plan.residual)
    exact.update(cell for cell in plan.cover if cell not in hierarchy.children)
    effective = {leaf for leaf, mass in oracle.items() if mass >= minimum_mass}
    exact_effective = effective & exact
    effective_mass = fsum(oracle[leaf] for leaf in effective)
    exact_effective_mass = fsum(oracle[leaf] for leaf in exact_effective)
    return {
        "minimum_mass": minimum_mass,
        "effective_entities": len(effective),
        "effective_exact_entities": len(exact_effective),
        "effective_exact_recall": len(exact_effective) / max(1, len(effective)),
        "effective_mass": effective_mass,
        "effective_exact_mass": exact_effective_mass,
        "effective_aggregate_mass": effective_mass - exact_effective_mass,
    }


def evaluate_top_k(field: Mapping[str, float], k: int) -> dict[str, float]:
    """Evaluate a non-global top-k baseline that assigns zero mass elsewhere."""
    if k < 0:
        raise ValueError("k must be non-negative")
    universe = frozenset(field)
    oracle = _normalized_field(field, universe)
    selected = set(sorted(universe, key=lambda node: (-oracle[node], node))[:k])
    approximation = {node: oracle[node] if node in selected else 0.0 for node in universe}
    return {
        "coverage": len(selected) / max(1, len(universe)),
        "l1_error": fsum(abs(oracle[node] - approximation[node]) for node in universe),
        "l2_error": fsum((oracle[node] - approximation[node]) ** 2 for node in universe),
        "mass_error": abs(1.0 - fsum(approximation.values())),
        "exact_attention_mass_capture": fsum(oracle[node] for node in selected),
    }
