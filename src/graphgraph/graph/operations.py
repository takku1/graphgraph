from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path

from .core import Edge, Graph, Node, Policy


@dataclass(frozen=True)
class GraphOperation:
    op: str
    target: str
    timestamp: str = ""
    actor: str = ""
    reason: str = ""
    payload: dict[str, object] | None = None


def operation_to_json(op: GraphOperation) -> dict[str, object]:
    return {
        "op": op.op,
        "target": op.target,
        "timestamp": op.timestamp,
        "actor": op.actor,
        "reason": op.reason,
        "payload": op.payload or {},
    }


def operation_from_json(data: dict[str, object]) -> GraphOperation:
    return GraphOperation(
        op=str(data.get("op", "")),
        target=str(data.get("target", "")),
        timestamp=str(data.get("timestamp", "")),
        actor=str(data.get("actor", "")),
        reason=str(data.get("reason", "")),
        payload=dict(data.get("payload") or {}),
    )


def append_operation(path: Path, op: GraphOperation) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(operation_to_json(op), ensure_ascii=False, separators=(",", ":")) + "\n")


def read_operations(path: Path) -> list[GraphOperation]:
    if not path.exists():
        return []
    ops: list[GraphOperation] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            ops.append(operation_from_json(json.loads(line)))
    return ops


def add_node(graph: Graph, node: Node) -> tuple[Graph, GraphOperation]:
    nodes = dict(graph.nodes)
    nodes[node.id] = node
    return Graph(nodes=nodes, edges=list(graph.edges), metadata=dict(graph.metadata)), GraphOperation("AddNode", node.id)


def add_edge(graph: Graph, edge: Edge) -> tuple[Graph, GraphOperation]:
    edges = list(graph.edges)
    key = (edge.source, edge.target, edge.type)
    if not any((e.source, e.target, e.type) == key for e in edges):
        edges.append(edge)
    return Graph(nodes=dict(graph.nodes), edges=edges, metadata=dict(graph.metadata)), GraphOperation("AddEdge", "|".join(key))


def expire_edge(
    graph: Graph,
    source: str,
    target: str,
    edge_type: str,
    valid_to: str,
    reason: str = "",
) -> tuple[Graph, GraphOperation]:
    edges = [
        replace(edge, active=False, valid_to=valid_to)
        if edge.source == source and edge.target == target and edge.type == edge_type
        else edge
        for edge in graph.edges
    ]
    return (
        Graph(nodes=dict(graph.nodes), edges=edges, metadata=dict(graph.metadata)),
        GraphOperation("ExpireEdge", f"{source}|{edge_type}|{target}", timestamp=valid_to, reason=reason),
    )


def expire_node(
    graph: Graph,
    node_id: str,
    valid_to: str,
    reason: str = "",
    expire_incident_edges: bool = True,
) -> tuple[Graph, GraphOperation]:
    """Soft-delete *node_id*: mark it inactive rather than removing it.

    This is the missing symmetric counterpart to ``expire_edge`` -- the
    "rmvN" half of the minimal add/remove-node/edge instruction set (see
    ``docs/incremental-update-instruction-set.md``). Kept as a soft delete,
    consistent with ``expire_edge``, so the operation log stays a true
    append-only history: nothing is destroyed, `active=False` plus
    `valid_to` records when and why it stopped being current.

    By default also expires any edge touching this node (both directions),
    since a "live" edge pointing at a dead node is a dangling reference that
    would otherwise silently reappear in traversals that don't check
    `active` on both endpoints.
    """
    nodes = dict(graph.nodes)
    if node_id in nodes:
        nodes[node_id] = replace(nodes[node_id], active=False, updated_at=valid_to)

    edges = list(graph.edges)
    if expire_incident_edges:
        edges = [
            replace(edge, active=False, valid_to=valid_to)
            if (edge.source == node_id or edge.target == node_id) and edge.active
            else edge
            for edge in edges
        ]

    return (
        Graph(nodes=nodes, edges=edges, metadata=dict(graph.metadata)),
        GraphOperation("ExpireNode", node_id, timestamp=valid_to, reason=reason),
    )


def merge_node(graph: Graph, source_id: str, target_id: str, reason: str = "") -> tuple[Graph, GraphOperation]:
    if source_id not in graph.nodes or target_id not in graph.nodes:
        return Graph(nodes=dict(graph.nodes), edges=list(graph.edges), metadata=dict(graph.metadata)), GraphOperation("MergeEntity", source_id, reason=reason)

    nodes = dict(graph.nodes)
    source = nodes[source_id]
    target = nodes[target_id]
    nodes[target_id] = replace(
        target,
        summary=target.summary or source.summary,
        facts=target.facts + tuple(f for f in source.facts if f not in target.facts),
        confidence=max(target.confidence, source.confidence),
        updated_at=target.updated_at or source.updated_at,
    )
    del nodes[source_id]

    # Redirect any other node's parent reference the same way edges are
    # redirected below -- source_id no longer exists, so leaving `parent`
    # pointing at it would dangle. target_id is the surviving identity
    # source_id was absorbed into, so that's the correct redirect target
    # (same treatment as an edge whose source/target was source_id).
    for nid, node in list(nodes.items()):
        if node.parent == source_id:
            nodes[nid] = replace(node, parent=target_id)

    edges: list[Edge] = []
    seen: set[tuple[str, str, str]] = set()
    for edge in graph.edges:
        src = target_id if edge.source == source_id else edge.source
        tgt = target_id if edge.target == source_id else edge.target
        if src == tgt:
            continue
        key = (src, tgt, edge.type)
        if key not in seen:
            seen.add(key)
            edges.append(replace(edge, source=src, target=tgt))
    return Graph(nodes=nodes, edges=edges, metadata=dict(graph.metadata)), GraphOperation("MergeEntity", f"{source_id}->{target_id}", reason=reason)


def policy_to_node(policy: Policy) -> Node:
    return Node(
        id=f"policy_{policy.id}",
        label=policy.id,
        kind="policy",
        summary=policy.compact,
        facts=(policy.content,) if policy.content else (),
        scope=",".join(policy.applies_to),
        source="policy",
        confidence=1.0,
    )


def add_policy_node(graph: Graph, policy: Policy) -> tuple[Graph, GraphOperation]:
    return add_node(graph, policy_to_node(policy))


def _dedupe_edges(edges: list[Edge]) -> list[Edge]:
    seen: set[tuple[str, str, str]] = set()
    out: list[Edge] = []
    for edge in edges:
        key = (edge.source, edge.target, edge.type)
        if key not in seen:
            seen.add(key)
            out.append(edge)
    return out


def add_decision_trace(
    graph: Graph,
    trace_id: str,
    summary: str,
    inputs: tuple[str, ...] = (),
    policies: tuple[str, ...] = (),
    outcome: str = "",
    timestamp: str = "",
    actor: str = "",
) -> tuple[Graph, GraphOperation]:
    node = Node(
        id=trace_id,
        label=trace_id,
        kind="decision_trace",
        summary=summary,
        facts=((f"outcome:{outcome}",) if outcome else ()) + tuple(f"input:{i}" for i in inputs),
        source=actor,
        created_at=timestamp,
        updated_at=timestamp,
    )
    graph, _ = add_node(graph, node)
    edges = list(graph.edges)
    for input_id in inputs:
        if input_id in graph.nodes:
            edges.append(Edge(trace_id, input_id, "used_input", provenance="decision_trace", valid_from=timestamp))
    for policy_id in policies:
        node_id = policy_id if policy_id in graph.nodes else f"policy_{policy_id}"
        if node_id in graph.nodes:
            edges.append(Edge(trace_id, node_id, "applied_policy", provenance="decision_trace", valid_from=timestamp))
    return (
        Graph(nodes=dict(graph.nodes), edges=edges, metadata=dict(graph.metadata)),
        GraphOperation("AddDecisionTrace", trace_id, timestamp=timestamp, actor=actor),
    )
