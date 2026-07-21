from __future__ import annotations

import json
from pathlib import Path

from ..graph.core import Edge, Graph, Node
from .persistence import file_lock


def ingest_runtime_trace(graph: Graph, path: Path, *, trace_id: str = "runtime") -> tuple[Graph, dict[str, object]]:
    """Ingest JSON/JSONL runtime events with caller, callee, timestamp, and optional count."""
    with file_lock(path):
        raw = path.read_text(encoding="utf-8")
    if path.suffix.casefold() == ".jsonl":
        events = [json.loads(line) for line in raw.splitlines() if line.strip()]
    else:
        data = json.loads(raw)
        events = data if isinstance(data, list) else data.get("events", [])
    nodes = dict(graph.nodes)
    edges = list(graph.edges)
    by_handle: dict[str, list[str]] = {}
    for node in nodes.values():
        for handle in (node.id, node.label, node.path):
            if handle:
                by_handle.setdefault(handle.casefold(), []).append(node.id)
    emitted = 0
    unresolved: set[str] = set()
    keys = {(edge.source, edge.target, edge.type) for edge in edges}
    for event in events:
        caller_raw = str(event.get("caller", ""))
        callee_raw = str(event.get("callee", ""))
        caller = _resolve(by_handle, caller_raw, nodes)
        callee = _resolve(by_handle, callee_raw, nodes)
        if not caller:
            caller = _external_node(nodes, caller_raw, trace_id)
            unresolved.add(caller_raw)
        if not callee:
            callee = _external_node(nodes, callee_raw, trace_id)
            unresolved.add(callee_raw)
        key = (caller, callee, "observed_calls")
        if key in keys:
            continue
        edges.append(Edge(
            caller,
            callee,
            "observed_calls",
            weight=float(event.get("count", 1.0)),
            confidence=1.0,
            provenance="runtime_trace",
            evidence=str(event.get("evidence", "")),
            source_location=str(event.get("location", "")),
            valid_from=str(event.get("timestamp", "")),
        ))
        keys.add(key)
        emitted += 1
    metadata = dict(graph.metadata)
    metadata["runtime_trace"] = trace_id
    return Graph(nodes=nodes, edges=edges, metadata=metadata), {
        "events": len(events), "edges_emitted": emitted, "unresolved_handles": sorted(unresolved)
    }


def _resolve(handles: dict[str, list[str]], raw: str, nodes: dict[str, Node]) -> str:
    matches = handles.get(raw.casefold(), ())
    if len(matches) == 1:
        return matches[0]
    ranked = sorted(
        matches,
        key=lambda node_id: (
            nodes[node_id].kind not in {"function", "method", "class", "module", "file"},
            not bool(nodes[node_id].path),
            node_id,
        ),
    )
    if not ranked:
        return ""
    best = ranked[0]
    if len(ranked) == 1:
        return best
    best_node = nodes[best]
    next_node = nodes[ranked[1]]
    best_score = (best_node.kind in {"function", "method", "class", "module", "file"}, bool(best_node.path))
    next_score = (next_node.kind in {"function", "method", "class", "module", "file"}, bool(next_node.path))
    return best if best_score > next_score else ""


def _external_node(nodes: dict[str, Node], handle: str, trace_id: str) -> str:
    node_id = f"trace:{trace_id}:{handle or 'unknown'}"
    nodes.setdefault(node_id, Node(node_id, handle or "unknown", kind="runtime_external", confidence=0.5))
    return node_id
