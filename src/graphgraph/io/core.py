from __future__ import annotations

import csv
import json
import re
import tempfile
from pathlib import Path

from ..graph.core import Edge, Graph, Node, Policy
from ..packets.validation import ValidationResult, validate_graph_json, validate_graph_object
from ..storage.backends import (
    is_binary_gg,
    load_graph_binary,
    save_graph_binary,
)

_BINARY_GRAPH_SUFFIXES = frozenset({".gg", ".ggb"})
# Self-describing version markers for the legacy text adjacency `.gg` format.
_GG_TEXT_VERSIONS = frozenset({"gg/1", "gg/2"})
# Column names that identify a header row in a CSV/TSV edge list.
_CSV_SOURCE_HEADERS = frozenset({"source", "from", "src", "node1", "subject", "edge_source"})


def _label_to_id(lbl: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]", "_", lbl)


def load_graph(path: Path, *, normalize_external_refs: bool = False) -> Graph:
    """Load a graph from GraphGraph's legacy/interop JSON schema.

    Despite the generic-sounding name, this is JSON-only. For a native
    ``.gg``/``.ggb`` binary graph (or any file whose format you don't know
    ahead of time), use ``load_any`` instead -- it dispatches on the file's
    actual format. Calling this on a binary graph used to fail deep inside
    ``json.loads`` with a raw ``UnicodeDecodeError``; it now fails fast here
    with a message that says what to do instead.
    """
    if is_binary_gg(path):
        raise ValueError(
            f"{path} is a native .gg/.ggb binary graph, not JSON -- load_graph() only reads "
            "GraphGraph's JSON schema. Use load_any() instead, which dispatches on the file's "
            "actual format (.gg/.ggb binary, JSON, CSV, TSV)."
        )
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(
            f"{path} is not valid UTF-8 text, so it can't be GraphGraph's JSON schema. "
            "Use load_any() instead, which dispatches on the file's actual format."
        ) from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"{path} is not valid JSON, so it can't be GraphGraph's JSON graph schema. "
            "Use load_any() instead, which dispatches on the file's actual format."
        ) from exc
    nodes = {
        item["id"]: Node(
            id=item["id"],
            label=item.get("label") or item.get("name") or item["id"],
            kind=item.get("kind") or item.get("file_type") or item.get("type") or "unknown",
            path=item.get("path") or item.get("source_file") or "",
            summary=item.get("summary") or item.get("properties", {}).get("description") or "",
            facts=tuple(item.get("facts") or []),
            scope=item.get("scope") or item.get("community") or "",
            parent=item.get("parent") or item.get("parent_id") or "",
            source=item.get("source") or item.get("source_uri") or "",
            confidence=_float_or(item.get("confidence"), 1.0),
            active=bool(item.get("active", True)),
            created_at=item.get("created_at") or "",
            updated_at=item.get("updated_at") or "",
        )
        for item in data["nodes"]
    }
    edges_data = data.get("edges") or data.get("links") or []
    edges = [
        Edge(
            source=item["source"],
            target=item["target"],
            type=item.get("type") or item.get("relation") or "dependency",
            weight=float(item.get("weight") if item.get("weight") is not None else 1.0),
            confidence=_float_or(item.get("confidence"), 1.0),
            provenance=item.get("provenance") or item.get("kind") or item.get("source_type") or "extracted",
            evidence=item.get("evidence") or item.get("description") or "",
            source_location=item.get("source_location") or item.get("loc") or "",
            valid_from=item.get("valid_from") or item.get("created_at") or "",
            valid_to=item.get("valid_to") or "",
            active=bool(item.get("active", True)),
        )
        for item in edges_data
    ]
    metadata = {str(k): str(v) for k, v in (data.get("metadata") or {}).items()}
    if normalize_external_refs:
        added = _add_external_reference_nodes(nodes, edges)
        if added:
            metadata["external_reference_nodes"] = str(added)
    graph = Graph(nodes=nodes, edges=edges, metadata=metadata)
    centrality = data.get("centrality") or {}
    if isinstance(centrality, dict):
        pagerank_payload = centrality.get("pagerank")
        if isinstance(pagerank_payload, dict):
            raw_scores = pagerank_payload.get("scores")
            if isinstance(raw_scores, list):
                pagerank_payload = dict(pagerank_payload)
                pagerank_payload["scores"] = {
                    str(row["id"]): float(row["score"])
                    for row in raw_scores
                    if isinstance(row, dict) and "id" in row and "score" in row
                }
            graph.seed_pagerank_cache(pagerank_payload)
    return graph


def _add_external_reference_nodes(nodes: dict[str, Node], edges: list[Edge]) -> int:
    added = 0
    for edge in edges:
        for endpoint in (edge.source, edge.target):
            if endpoint in nodes:
                continue
            nodes[endpoint] = Node(
                id=endpoint,
                label=endpoint,
                kind="external",
                facts=("external:unresolved",),
                confidence=0.35,
            )
            added += 1
    return added


def load_policies(path: Path) -> list[Policy]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return [
        Policy(
            id=item["id"],
            kind=item["kind"],
            priority=item["priority"],
            applies_to=tuple(item.get("applies_to", [])),
            task_tags=tuple(item.get("task_tags", [])),
            compact=item["compact"],
            content=item.get("content", ""),
        )
        for item in data
    ]


def _float_or(value: object, default: float) -> float:
    try:
        return float(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def save_graph(graph: Graph, path: Path) -> None:
    suffix = path.suffix.lower()
    if suffix in _BINARY_GRAPH_SUFFIXES:
        save_gg(graph, path)
        return
    path.write_text(graph_to_json(graph) + "\n", encoding="utf-8")


def graph_to_json(graph: Graph) -> str:
    data = {
        "nodes": [
            {
                "id": node.id,
                "label": node.label,
                "kind": node.kind,
                "path": node.path,
                "summary": node.summary,
                "facts": list(node.facts),
                "scope": node.scope,
                "parent": node.parent,
                "source": node.source,
                "confidence": node.confidence,
                "active": node.active,
                "created_at": node.created_at,
                "updated_at": node.updated_at,
            }
            for node in graph.nodes.values()
        ],
        "edges": [
            {
                "source": edge.source,
                "target": edge.target,
                "type": edge.type,
                "weight": edge.weight,
                "confidence": edge.confidence,
                "provenance": edge.provenance,
                "evidence": edge.evidence,
                "source_location": edge.source_location,
                "valid_from": edge.valid_from,
                "valid_to": edge.valid_to,
                "active": edge.active,
            }
            for edge in graph.edges
        ],
        "metadata": dict(graph.metadata),
        "centrality": {
            # Rows, not an object keyed by node ID: PowerShell's standard
            # ConvertFrom-Json treats object keys case-insensitively and fails
            # when valid symbols differ only by case (e.g. Lane vs lane).
            "pagerank": _portable_pagerank_payload(graph),
        },
    }
    return json.dumps(data, indent=2, ensure_ascii=False)


def _portable_pagerank_payload(graph: Graph) -> dict[str, object]:
    payload = graph.pagerank_cache_payload()
    scores = payload.get("scores")
    portable = dict(payload)
    portable["scores"] = [
        {"id": node_id, "score": score}
        for node_id, score in sorted(scores.items())
    ] if isinstance(scores, dict) else []
    return portable


def save_validated_graph(graph: Graph, path: Path) -> ValidationResult:
    suffix = path.suffix.lower()
    payload = graph_to_json(graph)
    result = validate_graph_json(payload)
    if not result.ok:
        raise ValueError(
            "Refusing to write invalid graph JSON: "
            + "; ".join(result.errors[:5])
            + (f"; ... {len(result.errors) - 5} more" if len(result.errors) > 5 else "")
        )

    if suffix in _BINARY_GRAPH_SUFFIXES:
        save_graph(graph, path)
        return validate_graph_object(graph, format_name="graph.gg")

    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as tmp:
        tmp.write(payload)
        tmp.write("\n")
        tmp_path = Path(tmp.name)
    tmp_path.replace(path)
    return result


def load_gg(path: Path) -> Graph:
    """Load a native .gg graph file.

    New `.gg` files are full-fidelity GraphGraph binary stores. Legacy text
    adjacency `.gg` files are still accepted for compatibility.
    """
    if is_binary_gg(path):
        return load_graph_binary(path)
    return load_gg_text(path)


def load_gg_text(path: Path) -> Graph:
    """Load a legacy .gg adjacency-list file.

    Format (self-describing, zero LLM schema overhead):
        gg/1
        NodeLabel [kind] path/to/file
          edge_type TargetLabel weight?
          edge_type TargetLabel

        NodeLabel [kind]
          ...
    Lines starting with # are comments. Blank lines are ignored.
    """
    text = path.read_text(encoding="utf-8")
    nodes: dict[str, Node] = {}
    pending_edges: list[tuple[str, str, str, float]] = []  # (src_label, tgt_label, type, weight)
    current_label: str | None = None

    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped in _GG_TEXT_VERSIONS:
            continue

        is_indented = raw_line[0] in (" ", "\t")

        if is_indented:
            if current_label is None:
                continue
            tokens = stripped.split()
            if len(tokens) < 2:
                continue
            edge_type, target_label = tokens[0], tokens[1]
            try:
                weight = float(tokens[2]) if len(tokens) > 2 else 1.0
            except ValueError:
                weight = 1.0
            pending_edges.append((current_label, target_label, edge_type, weight))
        else:
            tokens = stripped.split()
            label = tokens[0]
            kind = "unknown"
            node_path = ""
            rest = tokens[1:]
            if rest and rest[0].startswith("[") and rest[0].endswith("]"):
                kind = rest[0][1:-1]
                rest = rest[1:]
            if rest:
                node_path = rest[0]
            nid = _label_to_id(label)
            if nid in nodes:
                # Rename on ANY collision, not just when labels differ.
                # Two distinct nodes can legitimately share one label (e.g.
                # two different "helper" functions in different files) --
                # this format has no other qualifier per node line. Renaming
                # only when labels differed used to let a same-labeled node
                # silently overwrite the earlier one in `nodes`, discarding
                # it entirely rather than just leaving edge attribution
                # ambiguous (which is an inherent limit of a label-only
                # legacy format, not fixable here without a real qualifier
                # in pending_edges).
                nid = f"{nid}_{len(nodes)}"
            nodes[nid] = Node(id=nid, label=label, kind=kind, path=node_path)
            current_label = label

    # Resolve edges by label — try path fallback for ambiguous labels
    label_map: dict[str, str] = {}
    path_map: dict[str, str] = {}
    for nid, node in nodes.items():
        label_map[node.label] = nid
        if node.path:
            path_map[node.path] = nid

    edges: list[Edge] = []
    seen: set[tuple[str, str, str]] = set()
    for src_lbl, tgt_lbl, etype, weight in pending_edges:
        src_id = label_map.get(src_lbl) or path_map.get(src_lbl)
        tgt_id = label_map.get(tgt_lbl) or path_map.get(tgt_lbl)
        if src_id and tgt_id:
            key = (src_id, tgt_id, etype)
            if key not in seen:
                seen.add(key)
                edges.append(Edge(source=src_id, target=tgt_id, type=etype, weight=weight))

    return Graph(nodes=nodes, edges=edges)


def save_gg(graph: Graph, path: Path) -> None:
    """Save a Graph as the native full-fidelity binary .gg store."""
    save_graph_binary(graph, path)


def load_csv_edges(path: Path) -> Graph:
    """Load a CSV/TSV edge list into a Graph.

    Expects columns: source, target[, type[, weight]]
    First row may be a header (detected automatically).
    Nodes are auto-created from source/target values.
    """
    delimiter = "\t" if path.suffix.lower() == ".tsv" else ","
    with path.open(encoding="utf-8", newline="") as f:
        rows = list(csv.reader(f, delimiter=delimiter))

    if not rows:
        return Graph()

    header = [c.lower().strip() for c in rows[0]]
    is_header = any(column in _CSV_SOURCE_HEADERS for column in header)
    data_rows = rows[1:] if is_header else rows

    nodes: dict[str, Node] = {}
    edges: list[Edge] = []
    seen: set[tuple[str, str, str]] = set()

    for row in data_rows:
        if len(row) < 2:
            continue
        src, tgt = row[0].strip(), row[1].strip()
        if not src or not tgt:
            continue
        etype = row[2].strip() if len(row) > 2 and row[2].strip() else "relates"
        try:
            weight = float(row[3]) if len(row) > 3 and row[3].strip() else 1.0
        except ValueError:
            weight = 1.0

        for lbl in (src, tgt):
            nid = _label_to_id(lbl)
            if nid not in nodes:
                nodes[nid] = Node(id=nid, label=lbl)

        src_id, tgt_id = _label_to_id(src), _label_to_id(tgt)
        key = (src_id, tgt_id, etype)
        if key not in seen:
            seen.add(key)
            edges.append(Edge(source=src_id, target=tgt_id, type=etype, weight=weight))

    return Graph(nodes=nodes, edges=edges)


_graph_load_cache: dict[tuple[str, bool], tuple[int, int, Graph]] = {}


def load_any(path: Path, *, normalize_external_refs: bool = False) -> Graph:
    """Load a graph from any supported format: .gg, .ggb, .json, .csv, .tsv.

    Memoized by (resolved path, normalize_external_refs) plus an (mtime, size)
    fingerprint, so repeated calls against an unchanged file within one
    long-lived process (e.g. the MCP server making many tool calls against
    the same saved graph) skip re-parsing entirely -- measured at ~120ms for
    a ~5k-node/17k-edge native graph, which otherwise dominates per-call
    latency far more than the actual search/retrieval work. Graph is treated
    as immutable everywhere in this codebase (every mutator in
    graph/operations.py returns a new instance rather than mutating in
    place), so sharing the cached object across callers is safe.
    """
    resolved = path.resolve()
    cache_key = (str(resolved), normalize_external_refs)
    try:
        stat = resolved.stat()
    except OSError:
        stat = None

    if stat is not None:
        fingerprint = (stat.st_mtime_ns, stat.st_size)
        cached = _graph_load_cache.get(cache_key)
        if cached is not None and (cached[0], cached[1]) == fingerprint:
            return cached[2]

    suffix = path.suffix.lower()
    if suffix in _BINARY_GRAPH_SUFFIXES:
        graph = load_gg(path)
    elif suffix in (".csv", ".tsv"):
        graph = load_csv_edges(path)
    else:
        graph = load_graph(path, normalize_external_refs=normalize_external_refs)

    if stat is not None:
        _graph_load_cache[cache_key] = (fingerprint[0], fingerprint[1], graph)
    return graph


def validate_graph_file(path: Path) -> ValidationResult:
    suffix = path.suffix.lower()
    if suffix == ".json":
        return validate_graph_json(path.read_text(encoding="utf-8"))
    return validate_graph_object(load_any(path), format_name=f"graph{suffix or '_file'}")


def merge_graphify(base: Graph, overlay: Graph) -> Graph:
    """Merge an overlay graph (e.g. from graphify) into a base (scanned) graph.

    - Nodes whose path matches an existing base node: enrich summary/facts from overlay.
    - Overlay-only nodes: added verbatim.
    - Overlay edges: added if both endpoints resolve into the merged node set.
    """
    path_to_base_id: dict[str, str] = {
        n.path.lstrip("/").replace("\\", "/"): nid
        for nid, n in base.nodes.items()
        if n.path
    }

    new_nodes: dict[str, Node] = dict(base.nodes)
    overlay_id_map: dict[str, str] = {}  # overlay_node_id -> merged_node_id

    for ov_id, ov_node in overlay.nodes.items():
        norm = ov_node.path.lstrip("/").replace("\\", "/")
        if norm in path_to_base_id:
            base_id = path_to_base_id[norm]
            base_node = new_nodes[base_id]
            new_nodes[base_id] = Node(
                id=base_node.id,
                label=base_node.label,
                kind=base_node.kind,
                path=base_node.path,
                summary=ov_node.summary or base_node.summary,
                facts=ov_node.facts if ov_node.facts else base_node.facts,
                scope=ov_node.scope or base_node.scope,
                parent=ov_node.parent or base_node.parent,
                source=ov_node.source or base_node.source,
                confidence=max(base_node.confidence, ov_node.confidence),
                active=base_node.active and ov_node.active,
                created_at=base_node.created_at or ov_node.created_at,
                updated_at=ov_node.updated_at or base_node.updated_at,
            )
            overlay_id_map[ov_id] = base_id
        else:
            new_nodes[ov_id] = ov_node
            overlay_id_map[ov_id] = ov_id

    seen_edges: set[tuple[str, str, str]] = {(e.source, e.target, e.type) for e in base.edges}
    new_edges: list[Edge] = list(base.edges)
    for edge in overlay.edges:
        src = overlay_id_map.get(edge.source, edge.source)
        tgt = overlay_id_map.get(edge.target, edge.target)
        if src in new_nodes and tgt in new_nodes:
            key = (src, tgt, edge.type)
            if key not in seen_edges:
                seen_edges.add(key)
                new_edges.append(Edge(
                    source=src,
                    target=tgt,
                    type=edge.type,
                    weight=edge.weight,
                    confidence=edge.confidence,
                    provenance=edge.provenance,
                    evidence=edge.evidence,
                    source_location=edge.source_location,
                    valid_from=edge.valid_from,
                    valid_to=edge.valid_to,
                    active=edge.active,
                ))

    return Graph(nodes=new_nodes, edges=new_edges, metadata=dict(base.metadata))


