"""Demand-driven one-hop relation queries for latency-sensitive agents."""

from __future__ import annotations

from collections import defaultdict
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from ..graph.core import Edge, Graph, Node
from ..storage.sectioned import (
    _CALL,
    _INDEX_REF,
    _NODE_LITE,
    _U32,
    PackedRelationView,
    RelationNode,
    SectionedRelationView,
    _index_hash,
    is_sectioned_graph,
    load_packed_relation_view,
    load_sectioned_relation_view,
)
from .predicates import caller_evidence_quality
from .scoping import _is_test_material

RelationDirection = Literal["callers", "callees"]

_CODE_SYMBOL_KINDS = frozenset(
    {
        "function",
        "method",
        "constructor",
        "class",
        "struct",
        "trait",
        "interface",
        "enum",
        "type",
        "test",
    }
)
_EXTERNAL_KINDS = frozenset({"external", "runtime_external"})


def _normalized(value: str) -> str:
    return value.replace("\\", "/").strip().strip("/ ").casefold()


def _node_row(node: Node) -> dict[str, Any]:
    return {
        "id": node.id,
        "label": node.label,
        "kind": node.kind,
        "path": node.path,
        "line": node.line,
    }


def _candidate_order(node: Node) -> tuple[str, int, str, str]:
    return (
        _normalized(node.path),
        node.line or 0,
        node.label.casefold(),
        node.id,
    )


def _resolve_target(graph: Graph, target: str) -> tuple[str, tuple[Node, ...]]:
    """Resolve a relation target with exact code identities before fuzzy text.

    The relation lane intentionally has no ranked fallback. A fuzzy anchor is
    useful for exploratory context, but a direct adjacency lookup must either
    identify the requested symbol exactly or say that it cannot.
    """
    raw = target.strip()
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in {"`", "'", '"'}:
        raw = raw[1:-1].strip()
    if not raw:
        return "not_found", ()

    exact_id = graph.nodes.get(raw)
    if exact_id is not None and exact_id.active:
        return "ok", (exact_id,)

    active = tuple(node for node in graph.nodes.values() if node.active)
    if "::" in raw:
        path_text, label_text = raw.rsplit("::", 1)
        wanted_path = _normalized(path_text)
        wanted_label = label_text.strip().casefold()
        qualified = tuple(
            node
            for node in active
            if node.label.casefold() == wanted_label
            and (_normalized(node.path) == wanted_path or _normalized(node.path).endswith("/" + wanted_path))
        )
        if qualified:
            ordered = tuple(sorted(qualified, key=_candidate_order))
            return ("ok" if len(ordered) == 1 else "ambiguous"), ordered

    wanted = raw.casefold()
    label_matches = tuple(node for node in active if node.label.casefold() == wanted)
    code_matches = tuple(node for node in label_matches if node.kind.casefold() in _CODE_SYMBOL_KINDS)
    matches = code_matches or label_matches
    if matches:
        ordered = tuple(sorted(matches, key=_candidate_order))
        return ("ok" if len(ordered) == 1 else "ambiguous"), ordered

    wanted_path = _normalized(raw)
    path_matches = tuple(node for node in active if node.path and _normalized(node.path) == wanted_path)
    if path_matches:
        ordered = tuple(sorted(path_matches, key=_candidate_order))
        return ("ok" if len(ordered) == 1 else "ambiguous"), ordered
    return "not_found", ()


def _node_role(node: Node) -> str:
    if node.kind.casefold() in _EXTERNAL_KINDS:
        return "external"
    if _is_test_material(node):
        return "test"
    path_parts = {_normalized(part) for part in node.path.split("/") if part}
    if path_parts & {"bench", "benchmark", "benchmarks"}:
        return "benchmark"
    return "production"


def _role_order(role: str) -> int:
    return {"production": 0, "benchmark": 1, "test": 2, "external": 3}.get(role, 4)


def _topology_receipt(graph: Graph) -> tuple[str, str]:
    complete, detail = caller_evidence_quality(graph)
    if detail.startswith("no member-call telemetry"):
        return "unknown", detail
    return ("complete" if complete else "partial"), detail


def query_relations(
    graph: Graph,
    target: str,
    *,
    direction: RelationDirection,
    relation: str = "calls",
    limit: int = 50,
    include_tests: bool = True,
    include_external: bool = False,
    details: bool = False,
    freshness: str = "unchecked",
) -> dict[str, Any]:
    """Return one exact adjacency slice without planning, ranking, or packet expansion."""
    if direction not in {"callers", "callees"}:
        raise ValueError("direction must be 'callers' or 'callees'")
    if relation != "calls":
        raise ValueError("relation currently supports only 'calls'")
    if limit < 0:
        raise ValueError("limit must be non-negative")

    resolution, candidates = _resolve_target(graph, target)
    if resolution == "not_found":
        return {
            "status": "not_found",
            "query": target,
            "suggestion": "Use search_nodes to find an exact node id or pass path::symbol.",
        }
    if resolution == "ambiguous":
        return {
            "status": "ambiguous",
            "query": target,
            "candidates": [_node_row(node) for node in candidates],
            "suggestion": "Pass one candidate id or path::symbol.",
        }

    target_node = candidates[0]
    edges = (
        graph.incoming().get(target_node.id, ()) if direction == "callers" else graph.outgoing().get(target_node.id, ())
    )
    matching = tuple(edge for edge in edges if edge.type == relation and edge.active)

    by_neighbor: dict[str, list[Edge]] = defaultdict(list)
    for edge in matching:
        neighbor_id = edge.source if direction == "callers" else edge.target
        if neighbor_id in graph.nodes and graph.nodes[neighbor_id].active:
            by_neighbor[neighbor_id].append(edge)

    filtered_tests = 0
    filtered_external = 0
    rows: list[dict[str, Any]] = []
    for neighbor_id, neighbor_edges in by_neighbor.items():
        node = graph.nodes[neighbor_id]
        role = _node_role(node)
        if role == "test" and not include_tests:
            filtered_tests += 1
            continue
        if role == "external" and not include_external:
            filtered_external += 1
            continue
        best = max(neighbor_edges, key=lambda edge: edge.confidence)
        row = {
            **_node_row(node),
            "role": role,
            "confidence": round(best.confidence, 3),
        }
        if details:
            row.update(
                {
                    "edge_count": len(neighbor_edges),
                    "provenance": best.provenance,
                    "source_location": best.source_location,
                    "evidence": best.evidence,
                }
            )
        rows.append(row)

    rows.sort(
        key=lambda row: (
            _role_order(str(row["role"])),
            _normalized(str(row["path"])),
            int(row["line"] or 0),
            str(row["label"]).casefold(),
            str(row["id"]),
        )
    )
    total = len(rows)
    returned_rows = rows[:limit]
    topology_status, topology_detail = _topology_receipt(graph)
    complete_within_graph = len(returned_rows) == total
    answer_complete = complete_within_graph and topology_status == "complete" and freshness == "fresh"
    return {
        "status": "ok",
        "direction": direction,
        "relation": relation,
        "target": _node_row(target_node),
        "matched_total": len(by_neighbor),
        "total": total,
        "returned": len(returned_rows),
        "omitted": total - len(returned_rows),
        "filtered": {"tests": filtered_tests, "external": filtered_external},
        "neighbors": returned_rows,
        "receipt": {
            "complete_within_graph": complete_within_graph,
            "call_topology_status": topology_status,
            "call_topology_evidence": topology_detail,
            "answer_complete": answer_complete,
            "freshness": freshness,
        },
    }


def _view_node_row(node: RelationNode) -> dict[str, Any]:
    return {"id": node.id, "label": node.label, "kind": node.kind, "path": node.path, "line": node.line}


def _view_node_order(node: RelationNode) -> tuple[str, int, str, str]:
    return (_normalized(node.path), node.line or 0, node.label.casefold(), node.id)


def _resolve_view_target(view: SectionedRelationView, target: str) -> tuple[str, tuple[int, ...]]:
    raw = target.strip()
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in {"`", "'", '"'}:
        raw = raw[1:-1].strip()
    if not raw:
        return "not_found", ()
    exact = view.by_id.get(raw)
    if exact is not None:
        return "ok", (exact,)
    if "::" in raw:
        path_text, label_text = raw.rsplit("::", 1)
        wanted_path = _normalized(path_text)
        wanted_label = label_text.strip().casefold()
        qualified = tuple(
            index for index, node in enumerate(view.nodes)
            if node.label.casefold() == wanted_label
            and (_normalized(node.path) == wanted_path or _normalized(node.path).endswith("/" + wanted_path))
        )
        if qualified:
            ordered = tuple(sorted(qualified, key=lambda index: _view_node_order(view.nodes[index])))
            return ("ok" if len(ordered) == 1 else "ambiguous"), ordered
    wanted = raw.casefold()
    label_matches = tuple(index for index, node in enumerate(view.nodes) if node.label.casefold() == wanted)
    code_matches = tuple(
        index for index in label_matches if view.nodes[index].kind.casefold() in _CODE_SYMBOL_KINDS
    )
    matches = code_matches or label_matches
    if matches:
        ordered = tuple(sorted(matches, key=lambda index: _view_node_order(view.nodes[index])))
        return ("ok" if len(ordered) == 1 else "ambiguous"), ordered
    wanted_path = _normalized(raw)
    path_matches = tuple(
        index for index, node in enumerate(view.nodes)
        if node.path and _normalized(node.path) == wanted_path
    )
    if path_matches:
        ordered = tuple(sorted(path_matches, key=lambda index: _view_node_order(view.nodes[index])))
        return ("ok" if len(ordered) == 1 else "ambiguous"), ordered
    return "not_found", ()


def query_relation_view(
    view: SectionedRelationView,
    target: str,
    *,
    direction: RelationDirection,
    relation: str = "calls",
    limit: int = 50,
    include_tests: bool = True,
    include_external: bool = False,
    details: bool = False,
    freshness: str = "unchecked",
) -> dict[str, Any]:
    """Query a GGB4 partial view with the resident Graph result contract."""

    if direction not in {"callers", "callees"}:
        raise ValueError("direction must be 'callers' or 'callees'")
    if relation != "calls":
        raise ValueError("relation currently supports only 'calls'")
    if limit < 0:
        raise ValueError("limit must be non-negative")
    resolution, candidates = _resolve_view_target(view, target)
    if resolution == "not_found":
        return {
            "status": "not_found",
            "query": target,
            "suggestion": "Use search_nodes to find an exact node id or pass path::symbol.",
        }
    if resolution == "ambiguous":
        return {
            "status": "ambiguous",
            "query": target,
            "candidates": [_view_node_row(view.nodes[index]) for index in candidates],
            "suggestion": "Pass one candidate id or path::symbol.",
        }
    target_n = candidates[0]
    calls = view.incoming.get(target_n, ()) if direction == "callers" else view.outgoing.get(target_n, ())
    filtered_tests = 0
    filtered_external = 0
    rows: list[dict[str, Any]] = []
    for call in calls:
        neighbor_n = call.source_n if direction == "callers" else call.target_n
        node = view.nodes[neighbor_n]
        if node.role == "test" and not include_tests:
            filtered_tests += 1
            continue
        if node.role == "external" and not include_external:
            filtered_external += 1
            continue
        row = {**_view_node_row(node), "role": node.role, "confidence": round(call.confidence, 3)}
        if details:
            row.update({
                "edge_count": call.edge_count,
                "provenance": call.provenance,
                "source_location": call.source_location,
                "evidence": call.evidence,
            })
        rows.append(row)
    rows.sort(key=lambda row: (
        _role_order(str(row["role"])),
        _normalized(str(row["path"])),
        int(row["line"] or 0),
        str(row["label"]).casefold(),
        str(row["id"]),
    ))
    total = len(rows)
    returned = rows[:limit]
    complete_within_graph = len(returned) == total
    return {
        "status": "ok",
        "direction": direction,
        "relation": relation,
        "target": _view_node_row(view.nodes[target_n]),
        "matched_total": len(calls),
        "total": total,
        "returned": len(returned),
        "omitted": total - len(returned),
        "filtered": {"tests": filtered_tests, "external": filtered_external},
        "neighbors": returned,
        "receipt": {
            "complete_within_graph": complete_within_graph,
            "call_topology_status": view.topology_status,
            "call_topology_evidence": view.topology_detail,
            "answer_complete": (
                complete_within_graph and view.topology_status == "complete" and freshness == "fresh"
            ),
            "freshness": freshness,
        },
    }


def _packed_identity_text(view: PackedRelationView, index: int) -> str:
    if index < 0 or (index + 1) * _U32.size > len(view.identity_offsets):
        raise ValueError(f"invalid GGB4 identity string index {index}")
    offset = _U32.unpack_from(view.identity_offsets, index * _U32.size)[0]
    if offset + _U32.size > len(view.identity):
        raise ValueError("invalid GGB4 identity string offset")
    length = _U32.unpack_from(view.identity, offset)[0]
    start = offset + _U32.size
    end = start + length
    if end > len(view.identity):
        raise ValueError("invalid GGB4 identity string bounds")
    return view.identity[start:end].decode("utf-8")


def _packed_node(view: PackedRelationView, node_n: int) -> RelationNode:
    if not 0 <= node_n < view.node_count:
        raise ValueError(f"invalid GGB4 relation node index {node_n}")
    row = _NODE_LITE.unpack_from(view.node_rows, node_n * _NODE_LITE.size)
    id_idx, label, kind, node_path, line, role, active = row
    if not active:
        raise ValueError("GGB4 relation index names an inactive node")
    return RelationNode(
        id=_packed_identity_text(view, id_idx),
        label=_packed_identity_text(view, label),
        kind=_packed_identity_text(view, kind),
        path=_packed_identity_text(view, node_path),
        line=None if line < 0 else line,
        role=_packed_identity_text(view, role),
    )


def _packed_index_candidates(
    view: PackedRelationView,
    namespace: bytes,
    value: str,
) -> tuple[int, ...]:
    wanted = _index_hash(namespace, value)

    def hash_at(index: int) -> int:
        return _INDEX_REF.unpack_from(view.exact_index, index * _INDEX_REF.size)[0]

    low = 0
    high = view.exact_index_count
    while low < high:
        middle = (low + high) // 2
        if hash_at(middle) < wanted:
            low = middle + 1
        else:
            high = middle
    start = low
    high = view.exact_index_count
    while low < high:
        middle = (low + high) // 2
        if hash_at(middle) <= wanted:
            low = middle + 1
        else:
            high = middle
    return tuple(
        _INDEX_REF.unpack_from(view.exact_index, index * _INDEX_REF.size)[1]
        for index in range(start, low)
    )


def _resolve_packed_target(
    view: PackedRelationView,
    target: str,
) -> tuple[str, tuple[tuple[int, RelationNode], ...]]:
    raw = target.strip()
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in {"`", "'", '"'}:
        raw = raw[1:-1].strip()
    if not raw:
        return "not_found", ()

    exact = tuple(
        (node_n, node)
        for node_n in _packed_index_candidates(view, b"id", raw)
        if (node := _packed_node(view, node_n)).id == raw
    )
    if exact:
        return ("ok" if len(exact) == 1 else "ambiguous"), exact

    wanted_label = raw.rsplit("::", 1)[-1].strip().casefold()
    label_matches = tuple(
        (node_n, node)
        for node_n in _packed_index_candidates(view, b"label", wanted_label)
        if (node := _packed_node(view, node_n)).label.casefold() == wanted_label
    )
    if "::" in raw:
        path_text, _label_text = raw.rsplit("::", 1)
        wanted_path = _normalized(path_text)
        qualified = tuple(
            item
            for item in label_matches
            if _normalized(item[1].path) == wanted_path
            or _normalized(item[1].path).endswith("/" + wanted_path)
        )
        if qualified:
            ordered = tuple(sorted(qualified, key=lambda item: _view_node_order(item[1])))
            return ("ok" if len(ordered) == 1 else "ambiguous"), ordered
    code_matches = tuple(
        item for item in label_matches if item[1].kind.casefold() in _CODE_SYMBOL_KINDS
    )
    matches = code_matches or label_matches
    if matches:
        ordered = tuple(sorted(matches, key=lambda item: _view_node_order(item[1])))
        return ("ok" if len(ordered) == 1 else "ambiguous"), ordered

    wanted_path = _normalized(raw)
    path_matches = tuple(
        (node_n, node)
        for node_n in _packed_index_candidates(view, b"path", wanted_path)
        if (node := _packed_node(view, node_n)).path
        and _normalized(node.path) == wanted_path
    )
    if path_matches:
        ordered = tuple(sorted(path_matches, key=lambda item: _view_node_order(item[1])))
        return ("ok" if len(ordered) == 1 else "ambiguous"), ordered
    return "not_found", ()


def _packed_call_rows(
    view: PackedRelationView,
    node_n: int,
    direction: RelationDirection,
) -> tuple[tuple, ...]:
    payload = view.incoming_calls if direction == "callers" else view.outgoing_calls
    offsets = view.incoming_offsets if direction == "callers" else view.outgoing_offsets
    start = _U32.unpack_from(offsets, node_n * _U32.size)[0]
    end = _U32.unpack_from(offsets, (node_n + 1) * _U32.size)[0]
    row_count = len(payload) // _CALL.size
    if not 0 <= start <= end <= row_count:
        raise ValueError("invalid GGB4 call adjacency span")
    return tuple(
        _CALL.unpack_from(payload, index * _CALL.size)
        for index in range(start, end)
    )


def query_packed_relation_view(
    view: PackedRelationView,
    target: str,
    *,
    direction: RelationDirection,
    relation: str = "calls",
    limit: int = 50,
    include_tests: bool = True,
    include_external: bool = False,
    details: bool = False,
    freshness: str = "unchecked",
) -> dict[str, Any]:
    """Query one packed GGB4 adjacency span without materializing the graph/view."""

    if direction not in {"callers", "callees"}:
        raise ValueError("direction must be 'callers' or 'callees'")
    if relation != "calls":
        raise ValueError("relation currently supports only 'calls'")
    if limit < 0:
        raise ValueError("limit must be non-negative")
    resolution, candidates = _resolve_packed_target(view, target)
    if resolution == "not_found":
        return {
            "status": "not_found",
            "query": target,
            "suggestion": "Use search_nodes to find an exact node id or pass path::symbol.",
        }
    if resolution == "ambiguous":
        return {
            "status": "ambiguous",
            "query": target,
            "candidates": [_view_node_row(node) for _node_n, node in candidates],
            "suggestion": "Pass one candidate id or path::symbol.",
        }
    target_n, target_node = candidates[0]
    calls = _packed_call_rows(view, target_n, direction)
    filtered_tests = 0
    filtered_external = 0
    rows: list[dict[str, Any]] = []
    for source_n, target_n_value, confidence, provenance, location, evidence, edge_count in calls:
        neighbor_n = source_n if direction == "callers" else target_n_value
        node = _packed_node(view, neighbor_n)
        if node.role == "test" and not include_tests:
            filtered_tests += 1
            continue
        if node.role == "external" and not include_external:
            filtered_external += 1
            continue
        row = {
            **_view_node_row(node),
            "role": node.role,
            "confidence": round(float(confidence), 3),
        }
        if details:
            relation_strings = view.relation_strings
            if not all(0 <= index < len(relation_strings) for index in (provenance, location, evidence)):
                raise ValueError("invalid GGB4 call relation string index")
            row.update(
                {
                    "edge_count": edge_count,
                    "provenance": relation_strings[provenance],
                    "source_location": relation_strings[location],
                    "evidence": relation_strings[evidence],
                }
            )
        rows.append(row)
    rows.sort(
        key=lambda row: (
            _role_order(str(row["role"])),
            _normalized(str(row["path"])),
            int(row["line"] or 0),
            str(row["label"]).casefold(),
            str(row["id"]),
        )
    )
    total = len(rows)
    returned = rows[:limit]
    complete_within_graph = len(returned) == total
    return {
        "status": "ok",
        "direction": direction,
        "relation": relation,
        "target": _view_node_row(target_node),
        "matched_total": len(calls),
        "total": total,
        "returned": len(returned),
        "omitted": total - len(returned),
        "filtered": {"tests": filtered_tests, "external": filtered_external},
        "neighbors": returned,
        "receipt": {
            "complete_within_graph": complete_within_graph,
            "call_topology_status": view.topology_status,
            "call_topology_evidence": view.topology_detail,
            "answer_complete": (
                complete_within_graph
                and view.topology_status == "complete"
                and freshness == "fresh"
            ),
            "freshness": freshness,
        },
    }


@lru_cache(maxsize=16)
def _cached_relation_view(path_text: str, mtime_ns: int, size: int) -> SectionedRelationView:
    del mtime_ns, size
    return load_sectioned_relation_view(Path(path_text))


@lru_cache(maxsize=16)
def _cached_packed_relation_view(
    path_text: str,
    mtime_ns: int,
    size: int,
) -> PackedRelationView | None:
    del mtime_ns, size
    return load_packed_relation_view(Path(path_text))


def clear_relation_view_cache() -> int:
    removed = (
        _cached_relation_view.cache_info().currsize
        + _cached_packed_relation_view.cache_info().currsize
    )
    _cached_relation_view.cache_clear()
    _cached_packed_relation_view.cache_clear()
    return removed


def _has_applicable_delta(path: Path) -> bool:
    sidecar = path.with_name(path.name + ".delta")
    if not sidecar.exists():
        return False
    try:
        return sidecar.stat().st_mtime_ns >= path.stat().st_mtime_ns
    except OSError:
        return True


def query_saved_relations(
    path: Path,
    target: str,
    *,
    direction: RelationDirection,
    relation: str = "calls",
    limit: int = 50,
    include_tests: bool = True,
    include_external: bool = False,
    details: bool = False,
    freshness: str = "unchecked",
) -> dict[str, Any]:
    """Use GGB4 partial sections, falling back when legacy/deltas require it."""

    resolved = path.resolve()
    if is_sectioned_graph(resolved) and not _has_applicable_delta(resolved):
        stat = resolved.stat()
        cache_key = (str(resolved), stat.st_mtime_ns, stat.st_size)
        packed = _cached_packed_relation_view(*cache_key)
        query_view = query_packed_relation_view if packed is not None else query_relation_view
        view = packed if packed is not None else _cached_relation_view(*cache_key)
        return query_view(
            view,  # type: ignore[arg-type]
            target,
            direction=direction,
            relation=relation,
            limit=limit,
            include_tests=include_tests,
            include_external=include_external,
            details=details,
            freshness=freshness,
        )
    from ..io import load_any

    return query_relations(
        load_any(resolved),
        target,
        direction=direction,
        relation=relation,
        limit=limit,
        include_tests=include_tests,
        include_external=include_external,
        details=details,
        freshness=freshness,
    )


_MICRO_TARGET_COLUMNS = ("id", "label", "kind", "path", "line")
_MICRO_NEIGHBOR_COLUMNS = ("label", "kind", "path", "line", "role", "confidence")


def encode_relation_micro(result: dict[str, Any]) -> dict[str, Any]:
    """Encode a relation result as a tuple-oriented, low-token agent IR."""
    status = str(result.get("status", "error"))
    if status == "not_found":
        return {
            "v": 2,
            "s": status,
            "q": result.get("query", ""),
            "a": ["search_nodes", "retry_exact_id_or_path_symbol"],
        }
    if status == "ambiguous":
        return {
            "v": 2,
            "s": status,
            "q": result.get("query", ""),
            "ck": list(_MICRO_TARGET_COLUMNS),
            "c": [[item.get(column) for column in _MICRO_TARGET_COLUMNS] for item in result.get("candidates", ())],
            "a": ["retry_candidate_id"],
        }

    receipt = result["receipt"]
    direction = "<-calls" if result["direction"] == "callers" else "calls->"
    actions: list[str] = []
    if result["omitted"]:
        actions.append("raise_limit")
    if receipt["freshness"] == "unchecked":
        actions.append("sync_if_completeness_required")
    elif receipt["freshness"] == "incompatible":
        actions.append("rebuild_graph")
    elif receipt["freshness"] != "fresh":
        actions.append("project_status")
    if receipt["call_topology_status"] != "complete":
        actions.append("verify_absence_or_count")
    payload: dict[str, Any] = {
        "v": 2,
        "s": "ok",
        "d": direction,
        "tk": list(_MICRO_TARGET_COLUMNS),
        "k": list(_MICRO_NEIGHBOR_COLUMNS),
        "t": [result["target"].get(column) for column in _MICRO_TARGET_COLUMNS],
        "n": [[item.get(column) for column in _MICRO_NEIGHBOR_COLUMNS] for item in result["neighbors"]],
        "r": {
            "matched": result["matched_total"],
            "eligible": result["total"],
            "returned": result["returned"],
            "omitted": result["omitted"],
            "filtered": result["filtered"],
            "graph_complete": receipt["complete_within_graph"],
            "topology": receipt["call_topology_status"],
            "answer_complete": receipt["answer_complete"],
            "freshness": receipt["freshness"],
        },
    }
    if result.get("refresh"):
        payload["r"]["refresh"] = result["refresh"]
    if actions:
        payload["a"] = actions
    return payload


__all__ = [
    "clear_relation_view_cache",
    "encode_relation_micro",
    "query_relation_view",
    "query_packed_relation_view",
    "query_relations",
    "query_saved_relations",
]
