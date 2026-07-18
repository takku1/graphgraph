from __future__ import annotations

import json
import re
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

from ..graph.core import Graph
from ..io import graph_to_json


def export_graph(graph: Graph, path: Path, format_name: str = "auto") -> dict[str, object]:
    format_name = _format(path, format_name)
    if format_name == "json":
        content = graph_to_json(graph) + "\n"
    elif format_name == "graphml":
        content = _graphml(graph)
    elif format_name == "cypher":
        content = _cypher(graph)
    elif format_name == "jsonl":
        content = _jsonl(graph)
    else:
        raise ValueError(f"unsupported portable export format: {format_name}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return {"format": format_name, "output": str(path), "nodes": len(graph.nodes), "edges": len(graph.edges)}


def _format(path: Path, value: str) -> str:
    if value != "auto":
        return value
    return {".graphml": "graphml", ".cypher": "cypher", ".jsonl": "jsonl"}.get(path.suffix.casefold(), "json")


def _graphml(graph: Graph) -> str:
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<graphml xmlns="http://graphml.graphdrawing.org/xmlns">',
        '<key id="label" for="node" attr.name="label" attr.type="string"/>',
        '<key id="kind" for="node" attr.name="kind" attr.type="string"/>',
        '<key id="relation" for="edge" attr.name="relation" attr.type="string"/>',
        '<graph id="graphgraph" edgedefault="directed">',
    ]
    for node in graph.nodes.values():
        lines.append(f'<node id={quoteattr(node.id)}><data key="label">{escape(node.label)}</data><data key="kind">{escape(node.kind)}</data></node>')
    for index, edge in enumerate(graph.edges):
        lines.append(f'<edge id="e{index}" source={quoteattr(edge.source)} target={quoteattr(edge.target)}><data key="relation">{escape(edge.type)}</data></edge>')
    return "\n".join(lines + ["</graph>", "</graphml>", ""])


def _cypher(graph: Graph) -> str:
    lines = []
    for node in graph.nodes.values():
        props = "{" + ", ".join(
            f"{key}: {json.dumps(value, ensure_ascii=False)}"
            for key, value in {"id": node.id, "label": node.label, "kind": node.kind, "path": node.path}.items()
        ) + "}"
        lines.append(f"MERGE (n:GraphGraphNode {{id: {json.dumps(node.id)}}}) SET n += {props};")
    for edge in graph.edges:
        relation = re.sub(r"[^A-Za-z0-9_]", "_", edge.type).upper() or "RELATES"
        lines.append(f"MATCH (a:GraphGraphNode {{id: {json.dumps(edge.source)}}}), (b:GraphGraphNode {{id: {json.dumps(edge.target)}}}) MERGE (a)-[:{relation}]->(b);")
    return "\n".join(lines) + "\n"


def _jsonl(graph: Graph) -> str:
    rows = [json.dumps({"record": "node", **node.__dict__}, ensure_ascii=False) for node in graph.nodes.values()]
    rows.extend(json.dumps({"record": "edge", **edge.__dict__}, ensure_ascii=False) for edge in graph.edges)
    return "\n".join(rows) + "\n"
