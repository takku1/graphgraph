"""Path-hierarchy representation candidate for global-project-attention research.

The candidate consumes a query-conditioned influence field and never receives
task answer keys. It remains outside production retrieval until tournament
gates support promotion.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from math import fsum
from pathlib import PurePosixPath
from typing import Iterable, Mapping

from ..graph.core import Graph
from ..packets import token_units
from .attention_field import CoverPlan, Hierarchy, coverage_receipt

CELL_PREFIX = "__gg_research_cell__:"


@dataclass(frozen=True)
class PathHierarchy:
    hierarchy: Hierarchy
    labels: Mapping[str, str]


def build_path_hierarchy(
    graph: Graph,
    entity_ids: Iterable[str] | None = None,
    *,
    max_branching: int = 8,
) -> PathHierarchy:
    """Build a deterministic project/directory/file/entity hierarchy."""
    if max_branching < 2:
        raise ValueError("max_branching must be at least two")
    selected = tuple(
        sorted(
            node_id
            for node_id in (entity_ids if entity_ids is not None else graph.nodes)
            if node_id in graph.nodes and graph.nodes[node_id].active
        )
    )
    if not selected:
        raise ValueError("path hierarchy requires at least one active entity")

    root = f"{CELL_PREFIX}project"
    if root in graph.nodes:
        raise ValueError(f"reserved research cell ID collides with graph node {root!r}")
    children: dict[str, set[str]] = defaultdict(set)
    labels: dict[str, str] = {root: "project"}

    for node_id in selected:
        node = graph.nodes[node_id]
        normalized = (node.path or "").replace("\\", "/").strip("/")
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
                    raise ValueError(f"reserved research cell ID collides with graph node {cell!r}")
                children[parent].add(cell)
                labels[cell] = path
                parent = cell
        children[parent].add(node_id)

    ordered: dict[str, tuple[str, ...]] = {}
    for parent, items in children.items():
        _add_bounded_children(
            ordered,
            labels,
            parent,
            tuple(sorted(items)),
            max_branching=max_branching,
        )
    return PathHierarchy(Hierarchy(ordered, (root,)), labels)


def _add_bounded_children(
    output: dict[str, tuple[str, ...]],
    labels: dict[str, str],
    parent: str,
    items: tuple[str, ...],
    *,
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
        _add_bounded_children(
            output,
            labels,
            bucket,
            chunk,
            max_branching=max_branching,
            depth=depth + 1,
        )
    output[parent] = tuple(buckets)


def render_cover_plan(
    graph: Graph,
    path_hierarchy: PathHierarchy,
    field: Mapping[str, float],
    plan: CoverPlan,
) -> str:
    """Serialize exact entities and aggregate cells without gold evidence."""
    receipt = coverage_receipt(path_hierarchy.hierarchy, plan)
    if not receipt["valid"]:
        raise ValueError(f"invalid coverage plan: {receipt}")
    total = fsum(max(0.0, float(field.get(leaf, 0.0))) for leaf in path_hierarchy.hierarchy.leaves)
    if total <= 0.0:
        raise ValueError("influence field must have positive total mass")

    lines = ["#ggc1", "[x]"]
    for cell in plan.cover:
        if cell not in path_hierarchy.hierarchy.children:
            node = graph.nodes[cell]
            mass = max(0.0, float(field.get(cell, 0.0))) / total
            lines.append(f"E {cell} {node.label} [{node.kind}] @{node.path} m={mass:.6g}")
            continue
        leaves = path_hierarchy.hierarchy.cell_leaves(cell)
        mass = fsum(max(0.0, float(field.get(leaf, 0.0))) for leaf in leaves) / total
        kinds = Counter(graph.nodes[leaf].kind for leaf in leaves)
        kind_summary = ",".join(
            f"{kind}:{count}" for kind, count in sorted(kinds.items(), key=lambda item: (-item[1], item[0]))[:3]
        )
        label = path_hierarchy.labels.get(cell, cell)
        lines.append(f"K {label} n={len(leaves)} m={mass:.6g} kinds={kind_summary}")
    return "\n".join(lines)


def render_exact_nodes(
    graph: Graph,
    field: Mapping[str, float],
    node_ids: Iterable[str],
) -> str:
    total = fsum(max(0.0, float(value)) for value in field.values())
    if total <= 0.0:
        raise ValueError("influence field must have positive total mass")
    lines = ["#ggc1", "[x]"]
    for node_id in node_ids:
        lines.append(_render_exact_line(graph, field, node_id, total))
    return "\n".join(lines)


def _render_exact_line(
    graph: Graph,
    field: Mapping[str, float],
    node_id: str,
    total: float,
) -> str:
    node = graph.nodes[node_id]
    mass = max(0.0, float(field.get(node_id, 0.0))) / total
    return f"E {node_id} {node.label} [{node.kind}] @{node.path} m={mass:.6g}"


def select_flat_nodes_at_token_budget(
    graph: Graph,
    field: Mapping[str, float],
    token_budget: int,
) -> tuple[str, ...]:
    """Select the largest score-ranked exact prefix that fits the same renderer."""
    if token_budget < 0:
        raise ValueError("token_budget must be non-negative")
    ranked = sorted(
        (node_id for node_id in field if node_id in graph.nodes and graph.nodes[node_id].active),
        key=lambda node_id: (-float(field[node_id]), node_id),
    )
    total = fsum(max(0.0, float(value)) for value in field.values())
    if total <= 0.0:
        raise ValueError("influence field must have positive total mass")
    selected: list[str] = []
    # Accumulate unrounded units and round once, so this incremental accounting
    # stays byte-exact against rendering the whole packet and measuring it.
    used_units = token_units("#ggc1\n[x]")
    for node_id in ranked:
        line_units = token_units(_render_exact_line(graph, field, node_id, total))
        if round(used_units + line_units) > token_budget:
            continue
        selected.append(node_id)
        used_units += line_units
    return tuple(selected)


def evaluate_expected_resolution(
    hierarchy: Hierarchy,
    plan: CoverPlan,
    expected_nodes: Iterable[str],
) -> dict[str, float]:
    """Evaluator-only exact and resolution-weighted evidence recall."""
    expected = tuple(dict.fromkeys(expected_nodes))
    if not expected:
        return {"exact_recall": 1.0, "resolution_recall": 1.0, "worst_resolution": 1.0}
    receipt = coverage_receipt(hierarchy, plan)
    if not receipt["valid"]:
        raise ValueError(f"invalid coverage plan: {receipt}")

    scores: list[float] = []
    exact = set(plan.residual)
    for cell in plan.cover:
        leaves = hierarchy.cell_leaves(cell)
        if cell not in hierarchy.children:
            exact.add(cell)
        score = 1.0 if cell not in hierarchy.children else 1.0 / len(leaves)
        for node_id in expected:
            if node_id in leaves:
                scores.append(score)
    for node_id in expected:
        if node_id not in hierarchy.leaves:
            scores.append(0.0)
    exact_recall = sum(node_id in exact for node_id in expected) / len(expected)
    return {
        "exact_recall": exact_recall,
        "resolution_recall": fsum(scores) / len(expected),
        "worst_resolution": min(scores, default=0.0),
    }
