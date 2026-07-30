"""Exception-aware multiresolution project representation.

This module is production code.  It accepts only graph state, query seeds, and
an explicit token budget: answer keys and evaluation labels are intentionally
not part of its interface.  The resulting packet keeps a high-value exact
frontier while every other active entity remains represented by exactly one
aggregate cell.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from math import fsum, log2
from pathlib import PurePosixPath
from typing import Iterable, Mapping

from ..graph.core import Edge, Graph
from ..graph.coupling import EDGE_COUPLINGS, coupled_graph
from ..packets import estimate_tokens, render_packet, token_units
from ..surface import (
    REPRESENTATION_DEFAULT,
    REPRESENTATION_DESCRIPTION,
    REPRESENTATION_NAMES,
)

HYBRID_REPRESENTATION_VERSION = "hybrid_reserve_v1"
CELL_PREFIX = "__gg_cell__:"
_SUPPORTED_PACKETS = frozenset({"gg", "gg_hybrid", "gg_lex", "gg_lex_hybrid"})


def representation_schema(*, default: str = REPRESENTATION_DEFAULT) -> dict[str, object]:
    """Machine-readable policy schema, sharing its wording with the CLI help."""
    return {
        "type": "string",
        "enum": list(REPRESENTATION_NAMES),
        "default": default,
        "description": REPRESENTATION_DESCRIPTION,
    }


@dataclass(frozen=True)
class HybridRepresentationConfig:
    token_budget: int = 4096
    exact_fraction: float = 0.72
    max_branching: int = 8
    # Defaults to the incumbent orientation so enabling the representation
    # never silently changes which field a caller gets. `symmetric` is the
    # registered F1 candidate and is measured, not promoted.
    coupling: str = "directed"

    def __post_init__(self) -> None:
        if self.token_budget < 64:
            raise ValueError("hybrid token_budget must be at least 64")
        if not 0.0 < self.exact_fraction < 1.0:
            raise ValueError("hybrid exact_fraction must be between zero and one")
        if self.max_branching < 2:
            raise ValueError("hybrid max_branching must be at least two")
        if self.coupling not in EDGE_COUPLINGS:
            raise ValueError(f"hybrid coupling must be one of {EDGE_COUPLINGS}")


@dataclass(frozen=True)
class HybridRepresentation:
    packet: str
    exact_nodes: frozenset[str]
    aggregate_cells: tuple[str, ...]
    receipt: dict[str, object]
    # Which entities each cover line stands for. The packet already prints the
    # count as `n=`; carrying the membership makes a consumer able to say how
    # precisely any particular entity is located, rather than only how many
    # entities a line summarises.
    cell_members: Mapping[str, frozenset[str]] = field(default_factory=dict)

    def resolution_of(self, node_id: str) -> float:
        """How precisely this packet locates ``node_id``, in (0, 1].

        ``1.0`` means the entity is present exactly. An entity folded into an
        aggregate cell of ``k`` members resolves to ``1/k``: the packet places
        it, but only to within that cell. ``0.0`` means absent entirely, which
        a complete cover should make impossible.
        """
        if node_id in self.exact_nodes:
            return 1.0
        for cell in self.aggregate_cells:
            members = self.cell_members.get(cell)
            if members and node_id in members:
                return 1.0 / len(members)
        return 0.0


def accept_representation(
    representation: HybridRepresentation,
) -> tuple[str | None, dict[str, object]]:
    """Decide whether a compiled hybrid packet may be used.

    The exact frontier reserves every priority entity unconditionally, so a
    packet can exceed the requested budget when the reserve alone does not fit.
    A caller that asked for a bounded representation and did not get one is
    better served by the flat path, which is budget-shaped upstream -- so the
    packet is withheld and the caller degrades exactly as it does on a compile
    error. The receipt is returned either way so the overflow stays auditable
    instead of silently shipping an over-budget packet.
    """
    receipt = dict(representation.receipt)
    if receipt.get("within_budget"):
        return representation.packet, receipt
    receipt["status"] = "fallback_flat"
    receipt["reason"] = (
        f"hybrid packet needed {receipt.get('proxy_tokens')} proxy tokens for a "
        f"{receipt.get('token_budget')}-token budget; the exact reserve alone exceeds it"
    )
    return None, receipt


@dataclass
class _PathHierarchy:
    children: dict[str, tuple[str, ...]]
    roots: tuple[str, ...]
    labels: dict[str, str]
    leaves: frozenset[str]
    _leaf_cache: dict[str, frozenset[str]]

    def cell_leaves(self, cell: str) -> frozenset[str]:
        cached = self._leaf_cache.get(cell)
        if cached is not None:
            return cached
        children = self.children.get(cell)
        if children is None:
            result = frozenset({cell})
        else:
            result = frozenset().union(*(self.cell_leaves(child) for child in children))
        self._leaf_cache[cell] = result
        return result


def compile_hybrid_representation(
    graph: Graph,
    seeds: Mapping[str, float],
    *,
    packet_format: str = "gg",
    priority: Iterable[str] = (),
    config: HybridRepresentationConfig | None = None,
) -> HybridRepresentation:
    """Compile a bounded exact-frontier plus full-project aggregate cover."""
    config = config or HybridRepresentationConfig()
    if packet_format not in _SUPPORTED_PACKETS:
        raise ValueError(
            "hybrid representation currently requires one of: "
            + ", ".join(sorted(_SUPPORTED_PACKETS))
        )
    active = frozenset(node_id for node_id, node in graph.nodes.items() if node.active)
    if not active:
        raise ValueError("hybrid representation requires at least one active entity")
    seed_weights = {
        node_id: max(0.0, float(weight))
        for node_id, weight in seeds.items()
        if node_id in active and float(weight) > 0.0
    }
    if not seed_weights:
        raise ValueError("hybrid representation requires at least one active positive seed")

    hierarchy, hierarchy_cache = _cached_path_hierarchy(graph, config.max_branching)
    # The coupling changes only which orientation the field diffuses over. The
    # hierarchy, exact frontier, packet, and receipts are all built from the
    # original graph, so the packet's edges stay the project's real edges.
    raw_field = coupled_graph(graph, config.coupling).personalized_pagerank(seed_weights)
    total_mass = fsum(max(0.0, raw_field.get(node_id, 0.0)) for node_id in active)
    if total_mass <= 0.0:
        raise ValueError("query-conditioned influence field has zero mass")
    field = {node_id: max(0.0, raw_field.get(node_id, 0.0)) / total_mass for node_id in active}

    required = tuple(dict.fromkeys(node_id for node_id in priority if node_id in active))
    ranked = tuple(sorted(active, key=lambda node_id: (-field[node_id], node_id)))
    exact_budget = max(32, int(config.token_budget * config.exact_fraction))
    exact = _select_exact_frontier(
        graph,
        ranked,
        required,
        field,
        packet_format,
        exact_budget,
    )
    exact_packet = _render_exact_packet(graph, exact, packet_format, required)

    cover = set(hierarchy.roots)
    refinements = 0
    while True:
        aggregate_lines = _render_aggregate_lines(graph, hierarchy, field, cover, exact)
        current_packet = _inject_aggregates(exact_packet, aggregate_lines)
        current_tokens = estimate_tokens(current_packet)
        best: tuple[float, str, tuple[str, ...], int] | None = None
        for cell in sorted(cover):
            children = hierarchy.children.get(cell)
            if not children:
                continue
            candidate_cover = (cover - {cell}) | set(children)
            candidate_lines = _render_aggregate_lines(
                graph, hierarchy, field, candidate_cover, exact
            )
            candidate_tokens = estimate_tokens(_inject_aggregates(exact_packet, candidate_lines))
            if candidate_tokens > config.token_budget:
                continue
            delta = max(1, candidate_tokens - current_tokens)
            gain = _cell_resolution_cost(hierarchy, field, cell, exact) - fsum(
                _cell_resolution_cost(hierarchy, field, child, exact) for child in children
            )
            candidate = (gain / delta, cell, children, candidate_tokens)
            if gain > 0.0 and (best is None or candidate > best):
                best = candidate
        if best is None:
            break
        _ratio, cell, children, _tokens = best
        cover.remove(cell)
        cover.update(children)
        refinements += 1

    aggregate_lines = _render_aggregate_lines(graph, hierarchy, field, cover, exact)
    packet = _inject_aggregates(exact_packet, aggregate_lines)
    used_tokens = estimate_tokens(packet)
    represented, duplicate = _coverage_counts(hierarchy, cover, exact)
    exact_mass = fsum(field[node_id] for node_id in exact)
    unresolved = fsum(
        _cell_resolution_cost(hierarchy, field, cell, exact) for cell in cover
    )
    aggregate_cells = tuple(
        sorted(cell for cell in cover if hierarchy.cell_leaves(cell) - exact)
    )
    receipt: dict[str, object] = {
        "policy": "hybrid",
        "status": "experimental_opt_in",
        "version": HYBRID_REPRESENTATION_VERSION,
        "token_budget": config.token_budget,
        "proxy_tokens": used_tokens,
        "within_budget": used_tokens <= config.token_budget,
        "exact_fraction": config.exact_fraction,
        "active_entities": len(active),
        "represented_entities": represented,
        "coverage": represented / len(active),
        "duplicate_entities": duplicate,
        "exact_entities": len(exact),
        "aggregate_cells": len(aggregate_cells),
        "exact_mass": exact_mass,
        "aggregate_mass": max(0.0, 1.0 - exact_mass),
        "unresolved_log_resolution": unresolved,
        "exceptions_subtracted": len(exact),
        "refinements": refinements,
        "graph_revision": list(graph.mutation_revision),
        "hierarchy_cache": hierarchy_cache,
        "coupling": config.coupling,
    }
    if represented != len(active) or duplicate:
        raise RuntimeError(f"invalid hybrid coverage receipt: {receipt}")
    cell_members = {
        cell: _cell_effective_leaves(hierarchy, cell, exact) for cell in aggregate_cells
    }
    return HybridRepresentation(
        packet, frozenset(exact), aggregate_cells, receipt, cell_members
    )


def _cached_path_hierarchy(graph: Graph, max_branching: int) -> tuple[_PathHierarchy, str]:
    key = (graph.mutation_revision, max_branching)
    cached = getattr(graph, "_hybrid_path_hierarchy_cache", None)
    if cached is not None and cached[0] == key:
        return cached[1], "hit"
    hierarchy = _build_path_hierarchy(graph, max_branching=max_branching)
    graph._hybrid_path_hierarchy_cache = (key, hierarchy)
    return hierarchy, "miss"


def _build_path_hierarchy(graph: Graph, *, max_branching: int) -> _PathHierarchy:
    selected = tuple(sorted(node_id for node_id, node in graph.nodes.items() if node.active))
    root = f"{CELL_PREFIX}project"
    if root in graph.nodes:
        raise ValueError(f"reserved representation cell ID collides with graph node {root!r}")
    children: dict[str, set[str]] = defaultdict(set)
    labels = {root: "project"}
    for node_id in selected:
        normalized = (graph.nodes[node_id].path or "").replace("\\", "/").strip("/")
        parts = tuple(part for part in PurePosixPath(normalized).parts if part not in {"", "."})
        parent = root
        if not parts:
            cell = f"{CELL_PREFIX}unpathed"
            children[parent].add(cell)
            labels[cell] = "unpathed"
            parent = cell
        else:
            prefix: list[str] = []
            for part in parts:
                prefix.append(part)
                path = "/".join(prefix)
                cell = f"{CELL_PREFIX}{path}"
                if cell in graph.nodes:
                    raise ValueError(f"reserved representation cell ID collides with graph node {cell!r}")
                children[parent].add(cell)
                labels[cell] = path
                parent = cell
        children[parent].add(node_id)
    ordered: dict[str, tuple[str, ...]] = {}
    for parent, items in children.items():
        _add_bounded_children(ordered, labels, parent, tuple(sorted(items)), max_branching)
    hierarchy = _PathHierarchy(ordered, (root,), labels, frozenset(selected), {})
    if hierarchy.cell_leaves(root) != hierarchy.leaves:
        raise RuntimeError("path hierarchy does not cover every active graph entity")
    return hierarchy


def _add_bounded_children(
    output: dict[str, tuple[str, ...]],
    labels: dict[str, str],
    parent: str,
    items: tuple[str, ...],
    max_branching: int,
    depth: int = 0,
) -> None:
    if len(items) <= max_branching:
        output[parent] = items
        return
    chunk_size = (len(items) + max_branching - 1) // max_branching
    buckets: list[str] = []
    for index, offset in enumerate(range(0, len(items), chunk_size)):
        chunk = items[offset : offset + chunk_size]
        bucket = f"{parent}::range:{depth}:{index}"
        buckets.append(bucket)
        first = labels.get(chunk[0], chunk[0]).rsplit("/", 1)[-1]
        last = labels.get(chunk[-1], chunk[-1]).rsplit("/", 1)[-1]
        labels[bucket] = f"{labels.get(parent, parent)}/[{first}..{last}]"
        _add_bounded_children(output, labels, bucket, chunk, max_branching, depth + 1)
    output[parent] = tuple(buckets)


def _node_floor_units(graph: Graph, node_id: str) -> float:
    """Strict lower bound on the token units adding ``node_id`` costs a packet.

    Every renderer in the gg family emits the node's label and path verbatim on
    a space-separated line, and :func:`token_units` is additive over
    newline-joined lines, so those units never merge with their neighbours. The
    real marginal cost is strictly larger: it also carries the node id, the
    ``@``/``:line`` provenance punctuation, any summary or facts, and any
    newly-connected edges. Undercounting is what makes this safe to filter on --
    it can only ever admit a candidate for a full render, never discard one that
    would have fit.

    Measured in unrounded units rather than :func:`estimate_tokens`: rounding
    each part independently can round *up*, which would destroy the lower-bound
    property this filter's correctness rests on.
    """
    node = graph.nodes[node_id]
    return token_units(node.label or "") + token_units(node.path or "")


def _select_exact_frontier(
    graph: Graph,
    ranked: tuple[str, ...],
    required: tuple[str, ...],
    field: Mapping[str, float],
    packet_format: str,
    token_budget: int,
) -> set[str]:
    del field  # Ranking is deliberately computed by the caller once.
    selected: set[str] = set(required)
    required_packet = _render_exact_packet(graph, selected, packet_format, required)
    current_tokens = estimate_tokens(required_packet)
    if current_tokens > token_budget:
        return selected
    for node_id in ranked:
        if node_id in selected:
            continue
        # Rendering the whole packet per candidate is O(|active|) renders and
        # dominates the compile.  The floor is a sound admission test: skipping
        # on it leaves the selected set byte-for-byte identical to the
        # unfiltered greedy while rendering only plausible candidates. The +1
        # absorbs the half-unit that rounding the packet total can move either
        # way, so the filter stays conservative rather than merely usually right.
        if _node_floor_units(graph, node_id) > (token_budget - current_tokens) + 1.0:
            continue
        rendered = _render_exact_packet(graph, selected | {node_id}, packet_format, required)
        rendered_tokens = estimate_tokens(rendered)
        if rendered_tokens <= token_budget:
            selected.add(node_id)
            current_tokens = rendered_tokens
    return selected


def _render_exact_packet(
    graph: Graph,
    nodes: set[str],
    packet_format: str,
    priority: Iterable[str],
) -> str:
    edges: list[Edge] = [
        edge
        for edge in graph.edges
        if edge.active and edge.source in nodes and edge.target in nodes
    ]
    return render_packet(graph, nodes, edges, packet_format, priority=tuple(priority))


def _cell_effective_leaves(
    hierarchy: _PathHierarchy,
    cell: str,
    exact: set[str],
) -> frozenset[str]:
    return hierarchy.cell_leaves(cell) - exact


def _cell_resolution_cost(
    hierarchy: _PathHierarchy,
    field: Mapping[str, float],
    cell: str,
    exact: set[str],
) -> float:
    leaves = _cell_effective_leaves(hierarchy, cell, exact)
    if len(leaves) <= 1:
        return 0.0
    mass = fsum(field[leaf] for leaf in leaves)
    universe = max(2, len(hierarchy.leaves))
    return mass * log2(len(leaves)) / log2(universe)


def _cell_label(graph: Graph, hierarchy: _PathHierarchy, cell: str) -> str:
    """Label a cover member.

    A cover holds synthetic hierarchy cells and, once refinement reaches the
    bottom, bare leaf node IDs.  Only the latter exist in ``graph.nodes``, so
    the graph lookup must stay lazy.
    """
    label = hierarchy.labels.get(cell)
    if label is not None:
        return label
    node = graph.nodes[cell]
    return node.path or node.label


def _render_aggregate_lines(
    graph: Graph,
    hierarchy: _PathHierarchy,
    field: Mapping[str, float],
    cover: set[str],
    exact: set[str],
) -> tuple[str, ...]:
    lines: list[str] = []
    for cell in sorted(cover):
        leaves = _cell_effective_leaves(hierarchy, cell, exact)
        if not leaves:
            continue
        mass = fsum(field[leaf] for leaf in leaves)
        kinds = Counter(graph.nodes[leaf].kind for leaf in leaves)
        kind_summary = ",".join(
            f"{kind}:{count}"
            for kind, count in sorted(kinds.items(), key=lambda item: (-item[1], item[0]))[:3]
        )
        lines.append(
            f" ~K {_cell_label(graph, hierarchy, cell)}"
            f" n={len(leaves)} m={mass:.6g} k={kind_summary}"
        )
    return tuple(lines)


def _inject_aggregates(packet: str, aggregate_lines: tuple[str, ...]) -> str:
    if not aggregate_lines:
        return packet
    # Match the section header as a whole line, not as "\n[e]\n". When the
    # exact frontier has no edges between its own members the renderer emits
    # "[e]" as the final line with no trailing newline, and a substring probe
    # misses it -- which silently sent every edgeless selection down the flat
    # fallback instead of compiling a cover.
    lines = packet.split("\n")
    for index, line in enumerate(lines):
        if line == "[e]":
            break
    else:
        raise ValueError("hybrid representation requires a gg-family packet with an [e] section")
    return "\n".join([*lines[:index], " [a] global-cover", *aggregate_lines, *lines[index:]])


def _coverage_counts(
    hierarchy: _PathHierarchy,
    cover: set[str],
    exact: set[str],
) -> tuple[int, int]:
    counts = {leaf: int(leaf in exact) for leaf in hierarchy.leaves}
    for cell in cover:
        for leaf in _cell_effective_leaves(hierarchy, cell, exact):
            counts[leaf] += 1
    return sum(count > 0 for count in counts.values()), sum(count > 1 for count in counts.values())
