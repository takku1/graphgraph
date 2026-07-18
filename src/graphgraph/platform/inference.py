from __future__ import annotations

from dataclasses import dataclass

from ..graph.core import Edge, Graph


@dataclass(frozen=True)
class InferenceRule:
    name: str
    left: str
    right: str
    output: str
    confidence: float = 0.55


DEFAULT_RULES = (
    InferenceRule("transitive-call", "calls", "calls", "calls_candidate", 0.45),
    InferenceRule("import-use", "imports", "contains", "uses", 0.6),
    InferenceRule("test-dependency", "tests", "calls", "tests", 0.65),
    InferenceRule("configuration-use", "configures", "uses", "configures", 0.6),
)


def infer_edges(
    graph: Graph,
    rules: tuple[InferenceRule, ...] = DEFAULT_RULES,
    *,
    max_edges: int = 1000,
) -> tuple[Graph, dict[str, object]]:
    """Apply bounded two-hop Horn-style rules with explicit provenance."""
    by_source: dict[str, list[Edge]] = {}
    for edge in graph.edges:
        if edge.active:
            by_source.setdefault(edge.source, []).append(edge)
    existing = {(edge.source, edge.target, edge.type) for edge in graph.edges}
    added: list[Edge] = []
    per_rule: dict[str, int] = {}
    for rule in rules:
        for first in graph.edges:
            if not first.active or first.type != rule.left:
                continue
            for second in by_source.get(first.target, ()):
                key = (first.source, second.target, rule.output)
                if second.type != rule.right or first.source == second.target or key in existing:
                    continue
                edge = Edge(
                    first.source,
                    second.target,
                    rule.output,
                    confidence=min(rule.confidence, first.confidence, second.confidence),
                    provenance="inferred",
                    evidence=f"rule:{rule.name}; via:{first.target}",
                )
                added.append(edge)
                existing.add(key)
                per_rule[rule.name] = per_rule.get(rule.name, 0) + 1
                if len(added) >= max_edges:
                    break
            if len(added) >= max_edges:
                break
        if len(added) >= max_edges:
            break
    result = Graph(nodes=dict(graph.nodes), edges=list(graph.edges) + added, metadata=dict(graph.metadata))
    return result, {"added": len(added), "truncated": len(added) >= max_edges, "rules": per_rule}
