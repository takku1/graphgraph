from __future__ import annotations

import json
from pathlib import Path

from ..graph.core import Edge, Graph, Node
from .persistence import file_lock

_COVERAGE_CALLER = "runtime:coverage"
_ANONYMOUS_NAMES = frozenset({"", "(anonymous)", "anonymous"})


def ingest_runtime_trace(graph: Graph, path: Path, *, trace_id: str = "runtime") -> tuple[Graph, dict[str, object]]:
    """Ingest JSON/JSONL traces or V8/Istanbul coverage into observed_calls.

    Native events keep ``caller``/``callee``. Coverage formats only name the
    executed function; those emit ``runtime:coverage -> callee`` with
    ``runtime_trace`` provenance so static ``calls`` stay distinct.
    """
    with file_lock(path):
        raw = path.read_text(encoding="utf-8")
    events, source_format = _load_runtime_events(path, raw)
    nodes = dict(graph.nodes)
    edges = list(graph.edges)
    by_handle: dict[str, list[str]] = {}
    for node in nodes.values():
        for handle in _node_handles(node):
            by_handle.setdefault(handle, []).append(node.id)
    emitted = 0
    unresolved: set[str] = set()
    keys = {(edge.source, edge.target, edge.type) for edge in edges}
    for event in events:
        if not isinstance(event, dict):
            continue
        caller_raw = str(event.get("caller", "") or "")
        callee_raw = str(event.get("callee", "") or "")
        if not caller_raw and not callee_raw:
            continue
        location = str(event.get("location", "") or "")
        caller = _resolve(by_handle, caller_raw, nodes, location=location)
        callee = _resolve(by_handle, callee_raw, nodes, location=location)
        if not caller:
            caller = _external_node(nodes, caller_raw or _COVERAGE_CALLER, trace_id)
            if caller_raw and caller_raw != _COVERAGE_CALLER:
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
            weight=float(event.get("count", 1.0) or 1.0),
            confidence=1.0,
            provenance="runtime_trace",
            evidence=str(event.get("evidence", "")),
            source_location=location,
            valid_from=str(event.get("timestamp", "")),
        ))
        keys.add(key)
        emitted += 1
    metadata = dict(graph.metadata)
    metadata["runtime_trace"] = trace_id
    metadata["runtime_trace_format"] = source_format
    return Graph(nodes=nodes, edges=edges, metadata=metadata), {
        "events": len(events),
        "edges_emitted": emitted,
        "unresolved_handles": sorted(unresolved),
        "format": source_format,
    }


def _load_runtime_events(path: Path, raw: str) -> tuple[list[dict[str, object]], str]:
    if not raw.strip():
        return [], "empty"
    if path.suffix.casefold() == ".jsonl":
        events: list[dict[str, object]] = []
        for line in raw.splitlines():
            if not line.strip():
                continue
            payload = json.loads(line)
            events.extend(_normalize_runtime_payload(payload)[0])
        return events, "jsonl"
    payload = json.loads(raw)
    return _normalize_runtime_payload(payload)


def _normalize_runtime_payload(data: object) -> tuple[list[dict[str, object]], str]:
    kind = _runtime_payload_kind(data)
    if kind == "v8_coverage":
        payload = data if isinstance(data, dict) else {"result": data}
        return _events_from_v8(payload), kind
    if kind == "istanbul_coverage" and isinstance(data, dict):
        return _events_from_istanbul(data), kind
    if kind == "events":
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)], kind
        if isinstance(data, dict) and isinstance(data.get("events"), list):
            return [item for item in data["events"] if isinstance(item, dict)], kind
        if isinstance(data, dict):
            return [data], kind
    return [], "unknown"


def _runtime_payload_kind(data: object) -> str:
    if isinstance(data, list):
        first = data[0] if data and isinstance(data[0], dict) else {}
        if "functions" in first:
            return "v8_coverage"
        return "events"
    if not isinstance(data, dict):
        return "unknown"
    if isinstance(data.get("events"), list) or "caller" in data or "callee" in data:
        return "events"
    if isinstance(data.get("result"), list):
        return "v8_coverage"
    istanbul = any(
        isinstance(value, dict) and ("fnMap" in value or "f" in value)
        for value in data.values()
    )
    return "istanbul_coverage" if istanbul else "unknown"


def _events_from_v8(data: dict[str, object]) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    scripts = data.get("result", [])
    if not isinstance(scripts, list):
        return events
    for script in scripts:
        if isinstance(script, dict):
            events.extend(_events_from_v8_script(script))
    return events


def _events_from_v8_script(script: dict[str, object]) -> list[dict[str, object]]:
    path = _coverage_path(str(script.get("url", "") or ""))
    functions = script.get("functions", [])
    if not isinstance(functions, list):
        return []
    events: list[dict[str, object]] = []
    for function in functions:
        event = _event_from_v8_function(function, path)
        if event is not None:
            events.append(event)
    return events


def _event_from_v8_function(function: object, path: str) -> dict[str, object] | None:
    if not isinstance(function, dict):
        return None
    name = _coverage_function_name(str(function.get("functionName", "") or ""))
    count = _v8_hit_count(function.get("ranges"))
    if not name or count <= 0:
        return None
    return {
        "caller": _COVERAGE_CALLER,
        "callee": name,
        "count": count,
        "location": path,
        "evidence": "v8_coverage",
    }


def _v8_hit_count(ranges: object) -> int:
    if not isinstance(ranges, list):
        return 0
    return sum(int(item.get("count", 0) or 0) for item in ranges if isinstance(item, dict))


def _events_from_istanbul(data: dict[str, object]) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    for file_path, payload in data.items():
        if not isinstance(payload, dict):
            continue
        fn_map = payload.get("fnMap")
        hits = payload.get("f")
        if not isinstance(fn_map, dict) or not isinstance(hits, dict):
            continue
        path = _coverage_path(str(payload.get("path") or file_path))
        for key, meta in fn_map.items():
            if not isinstance(meta, dict):
                continue
            name = _coverage_function_name(str(meta.get("name") or ""))
            if not name:
                continue
            count = int(hits.get(str(key), hits.get(key, 0)) or 0)
            if count <= 0:
                continue
            events.append({
                "caller": _COVERAGE_CALLER,
                "callee": name,
                "count": count,
                "location": _istanbul_location(path, meta),
                "evidence": "istanbul_coverage",
            })
    return events


def _istanbul_location(path: str, meta: dict[str, object]) -> str:
    loc = meta.get("loc") or meta.get("decl") or {}
    if isinstance(loc, dict):
        start = loc.get("start")
        if isinstance(start, dict) and start.get("line") is not None:
            return f"{path}:{start['line']}"
    return path


def _coverage_function_name(name: str) -> str:
    trimmed = name.strip()
    if not trimmed or trimmed.casefold() in _ANONYMOUS_NAMES or trimmed.startswith("(anonymous"):
        return ""
    if "." in trimmed:
        return trimmed.rsplit(".", 1)[-1]
    return trimmed


def _coverage_path(url: str) -> str:
    text = url.replace("\\", "/")
    if text.startswith("file://"):
        text = text[7:]
        if len(text) >= 3 and text[0] == "/" and text[2] == ":":
            text = text[1:]
    return text


def _node_handles(node: Node) -> tuple[str, ...]:
    handles = {node.id.casefold(), node.label.casefold()}
    path = node.path.replace("\\", "/").casefold()
    if path:
        handles.add(path)
        handles.add(Path(path).name)
        if node.label:
            handles.add(f"{path}::{node.label.casefold()}")
            handles.add(f"{Path(path).name}::{node.label.casefold()}")
    return tuple(handle for handle in handles if handle)


def _resolve(
    handles: dict[str, list[str]],
    raw: str,
    nodes: dict[str, Node],
    *,
    location: str = "",
) -> str:
    if not raw:
        return ""
    matches = _location_matches(handles, raw, nodes, location)
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
    callable_kinds = {"function", "method", "class", "module", "file"}
    best_score = (nodes[best].kind in callable_kinds, bool(nodes[best].path))
    next_score = (nodes[ranked[1]].kind in callable_kinds, bool(nodes[ranked[1]].path))
    return best if best_score > next_score else ""


def _location_matches(
    handles: dict[str, list[str]],
    raw: str,
    nodes: dict[str, Node],
    location: str,
) -> list[str]:
    matches = list(handles.get(raw.casefold(), ()))
    location_path = _coverage_path(location.split(":", 1)[0] if location else "").casefold()
    if not location_path:
        return matches
    qualified = list(handles.get(f"{location_path}::{raw.casefold()}", ()))
    if len(qualified) == 1:
        return qualified
    path_matches = [
        node_id
        for node_id in matches
        if _path_matches_coverage(nodes[node_id].path, location_path)
    ]
    return path_matches or matches


def _path_matches_coverage(node_path: str, location_path: str) -> bool:
    left = node_path.replace("\\", "/").casefold()
    right = location_path.replace("\\", "/").casefold()
    return bool(left) and (left.endswith(right) or right.endswith(left))


def _external_node(nodes: dict[str, Node], handle: str, trace_id: str) -> str:
    node_id = f"trace:{trace_id}:{handle or 'unknown'}"
    nodes.setdefault(node_id, Node(node_id, handle or "unknown", kind="runtime_external", confidence=0.5))
    return node_id
