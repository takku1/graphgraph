from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .core import Edge, Graph, Node
from .terms import canonical_concept_label, concept_id, term_key


@dataclass(frozen=True)
class SemanticTriple:
    source: str
    relation: str
    target: str
    confidence: float = 0.65
    evidence: str = ""
    provenance: str = "semantic_llm"


def load_semantic_triples(path: Path) -> list[SemanticTriple]:
    data = json.loads(path.read_text(encoding="utf-8"))
    items = data.get("triples", data) if isinstance(data, dict) else data
    triples: list[SemanticTriple] = []
    for item in items:
        triples.append(SemanticTriple(
            source=str(item["source"]),
            relation=str(item.get("relation") or item.get("type") or "relates"),
            target=str(item["target"]),
            confidence=float(item.get("confidence", 0.65)),
            evidence=str(item.get("evidence", "")),
            provenance=str(item.get("provenance", "semantic_llm")),
        ))
    return triples


def merge_semantic_triples(graph: Graph, triples: list[SemanticTriple]) -> Graph:
    nodes = dict(graph.nodes)
    edges = list(graph.edges)
    label_index = {term_key(node.label): node_id for node_id, node in nodes.items() if term_key(node.label)}

    def ensure_concept(label: str) -> str:
        key = term_key(label)
        if key in label_index:
            return label_index[key]
        node_id = concept_id(label)
        suffix = 2
        base = node_id
        while node_id in nodes:
            node_id = f"{base}_{suffix}"
            suffix += 1
        nodes[node_id] = Node(
            id=node_id,
            label=canonical_concept_label(label),
            kind="concept",
            summary="semantic concept",
            confidence=0.65,
            source="semantic",
        )
        label_index[key] = node_id
        return node_id

    seen = {(edge.source, edge.target, edge.type) for edge in edges}
    for triple in triples:
        src = ensure_concept(triple.source)
        tgt = ensure_concept(triple.target)
        key = (src, tgt, triple.relation)
        if key in seen:
            continue
        seen.add(key)
        edges.append(Edge(
            source=src,
            target=tgt,
            type=triple.relation,
            weight=1.0,
            confidence=triple.confidence,
            provenance=triple.provenance,
            evidence=triple.evidence,
        ))
    metadata = dict(graph.metadata)
    metadata["semantic_triples"] = str(len(triples))
    return Graph(nodes=nodes, edges=edges, metadata=metadata)
