from __future__ import annotations

import csv
import json
import re
import tempfile
from pathlib import Path

from .core import Edge, Graph, Node, Policy
from .validate import ValidationResult, validate_graph_json


def _label_to_id(lbl: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]", "_", lbl)


def load_graph(path: Path) -> Graph:
    data = json.loads(path.read_text(encoding="utf-8"))
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
    graph = Graph(nodes=nodes, edges=edges, metadata=metadata)
    centrality = data.get("centrality") or {}
    if isinstance(centrality, dict):
        pagerank_payload = centrality.get("pagerank")
        if isinstance(pagerank_payload, dict):
            graph.seed_pagerank_cache(pagerank_payload)
    return graph


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
    if path.suffix.lower() == ".gg":
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
            "pagerank": graph.pagerank_cache_payload(),
        },
    }
    return json.dumps(data, indent=2, ensure_ascii=False)


def save_validated_graph(graph: Graph, path: Path) -> ValidationResult:
    if path.suffix.lower() == ".gg":
        save_gg(graph, path)
        return ValidationResult(True, "gg", len(graph.nodes), len(graph.edges))

    payload = graph_to_json(graph)
    result = validate_graph_json(payload)
    if not result.ok:
        raise ValueError(
            "Refusing to write invalid graph JSON: "
            + "; ".join(result.errors[:5])
            + (f"; ... {len(result.errors) - 5} more" if len(result.errors) > 5 else "")
        )

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
    """Load a native .gg adjacency-list file.

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
        if stripped in ("gg/1", "gg/2"):
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
            if nid in nodes and nodes[nid].label != label:
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
    """Save a Graph as a native .gg adjacency-list file.

    Token-optimal for LLM ingest: self-describing format, no schema needed,
    outgoing edges co-located with each node for attention locality.
    """
    outgoing: dict[str, list[Edge]] = {}
    for edge in graph.edges:
        outgoing.setdefault(edge.source, []).append(edge)

    lines = ["gg/1"]
    for nid in sorted(graph.nodes, key=lambda x: graph.nodes[x].label.lower()):
        node = graph.nodes[nid]
        parts = [node.label]
        if node.kind and node.kind != "unknown":
            parts.append(f"[{node.kind}]")
        if node.path:
            parts.append(node.path)
        lines.append(" ".join(parts))
        if node.summary:
            lines.append(f"  # {node.summary}")
        for edge in sorted(outgoing.get(nid, []), key=lambda e: e.type):
            tgt = graph.nodes.get(edge.target)
            tgt_ref = tgt.label if tgt else edge.target
            if edge.weight != 1.0:
                lines.append(f"  {edge.type} {tgt_ref} {edge.weight:g}")
            else:
                lines.append(f"  {edge.type} {tgt_ref}")
        lines.append("")

    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


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
    is_header = any(h in ("source", "from", "src", "node1", "subject", "edge_source") for h in header)
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


def load_any(path: Path) -> Graph:
    """Load a graph from any supported format: .gg, .json, .csv, .tsv."""
    suffix = path.suffix.lower()
    if suffix == ".gg":
        return load_gg(path)
    if suffix in (".csv", ".tsv"):
        return load_csv_edges(path)
    return load_graph(path)


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


_NATIVE_GRAPH_CANDIDATES = [
    ".graphgraph/graph.gg",
    ".graphgraph/graph.json",
]

_EXTERNAL_GRAPH_CANDIDATES = [
    ".code-review-graph/graph.json",
    "graphify-out/graph.json",
    ".graphify/graph.json",
    "graphify/graph.json",
]


def find_graphify_path(workspace_root: Path = Path(".")) -> Path | None:
    for c in _EXTERNAL_GRAPH_CANDIDATES:
        if "graphify" not in c:
            continue
        p = workspace_root / c
        if p.exists():
            return p
    return None


def find_external_graph_path(workspace_root: Path = Path(".")) -> Path | None:
    """Find a non-native graph that can be ingested explicitly.

    External graphs are explicit interop inputs. They are deliberately excluded
    from default graph discovery so generated exports do not silently pollute
    native scans.
    """
    for c in _EXTERNAL_GRAPH_CANDIDATES:
        p = workspace_root / c
        if p.exists():
            return p
    return None


def find_graph_path(workspace_root: Path = Path("."), *, include_external: bool = False) -> Path:
    candidates = [workspace_root / c for c in _NATIVE_GRAPH_CANDIDATES]
    if include_external:
        candidates.extend(workspace_root / c for c in _EXTERNAL_GRAPH_CANDIDATES)
    for c in candidates:
        if c.exists():
            return c
    raise FileNotFoundError(
        "Could not find a native GraphGraph file in default paths: "
        f"{[str(c) for c in candidates]}. Run `graphgraph scan --output .graphgraph/graph.json` "
        "or specify a graph path explicitly. External graphs must be passed to `graphgraph ingest --input ...`."
    )


def find_policies_path(workspace_root: Path = Path(".")) -> Path | None:
    candidates = [
        workspace_root / ".graphgraph" / "policies.json",
        workspace_root / "policies.json",
        workspace_root / ".code-review-graph" / "policies.json",
        workspace_root / ".agents" / "policies.json",
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


def find_lessons_path(workspace_root: Path = Path(".")) -> Path | None:
    candidates = [
        workspace_root / ".graphgraph" / "lessons.md",
        workspace_root / ".graphgraph" / "reflections" / "LESSONS.md",
        workspace_root / "lessons.md",
    ]
    for c in candidates:
        if c.exists():
            return c
    return None
