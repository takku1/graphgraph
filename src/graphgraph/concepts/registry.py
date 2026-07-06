from __future__ import annotations

import re
from dataclasses import dataclass

from ..graph.core import Edge, Node
from .terms import concept_id, term_key


@dataclass(frozen=True)
class InterpretationConcept:
    label: str
    kind: str
    layer: str
    aliases: tuple[str, ...]
    facts: tuple[str, ...] = ()


INTERPRETATION_CONCEPTS: tuple[InterpretationConcept, ...] = (
    InterpretationConcept(
        label="Personalized PageRank",
        kind="algorithm",
        layer="retrieval",
        aliases=("Personalized PageRank", "PageRank", "QS-PPR", "Joint Query-Session Personalized PageRank"),
        facts=("layer:retrieval", "role:anchor_ranking", "math:power_iteration"),
    ),
    InterpretationConcept(
        label="Tree Knapsack Dynamic Programming",
        kind="algorithm",
        layer="budgeting",
        aliases=("Tree Knapsack", "Knuth-style Tree Knapsack", "Knuth-Optimal Context Partitioning", "Dynamic Programming"),
        facts=("layer:budgeting", "role:connected_context_partition", "math:dynamic_programming"),
    ),
    InterpretationConcept(
        label="Geodesic Spatial Bias Tensor",
        kind="math_concept",
        layer="packet",
        aliases=("Geodesic Spatial Bias Tensor", "Spatial Bias Tensor", "attention bias", "self-attention heads"),
        facts=("layer:packet", "role:attention_topology", "math:geodesic_distance_matrix"),
    ),
    InterpretationConcept(
        label="Monte Carlo Tree Search",
        kind="algorithm",
        layer="planning",
        aliases=("Monte Carlo Tree Search", "MCTS"),
        facts=("layer:planning", "role:tree_search", "math:stochastic_tree_search"),
    ),
    InterpretationConcept(
        label="Alpha-Beta Search",
        kind="algorithm",
        layer="planning",
        aliases=("Alpha-Beta Search", "alpha beta search", "alpha-beta pruning"),
        facts=("layer:planning", "role:tree_search", "math:minimax_pruning"),
    ),
    InterpretationConcept(
        label="KKT Optimization",
        kind="math_concept",
        layer="budgeting",
        aliases=("KKT", "Karush-Kuhn-Tucker", "KKT optimization", "Lagrangian"),
        facts=("layer:budgeting", "role:constrained_optimization", "math:kkt_conditions"),
    ),
    InterpretationConcept(
        label="Bellman Optimality Equation",
        kind="math_concept",
        layer="planning",
        aliases=("Bellman Optimality Equation", "Bellman", "MDP", "Markov Decision Process"),
        facts=("layer:planning", "role:sequential_decision", "math:dynamic_programming"),
    ),
    InterpretationConcept(
        label="Spreading Activation",
        kind="algorithm",
        layer="retrieval",
        aliases=("Spreading Activation", "activation state", "query energy injection"),
        facts=("layer:retrieval", "role:context_propagation", "math:graph_diffusion"),
    ),
    InterpretationConcept(
        label="KV Cache",
        kind="runtime_concept",
        layer="hardware",
        aliases=("KV Cache", "Key-Value Cache", "prompt prefix caching"),
        facts=("layer:hardware", "role:attention_state_reuse", "runtime:transformer_cache"),
    ),
)

_ALIAS_INDEX = {
    term_key(alias): concept
    for concept in INTERPRETATION_CONCEPTS
    for alias in concept.aliases
    if term_key(alias)
}


def interpretation_concept_id(concept: InterpretationConcept) -> str:
    return concept_id(concept.label, prefix=concept.kind)


def detect_interpretation_concepts(text: str) -> tuple[InterpretationConcept, ...]:
    """Return known algorithm/math concepts mentioned in source or docs.

    This is intentionally registry-backed. Generic concept extraction is useful
    for orientation, but interpretation-layer nodes need stable semantics,
    repeatable IDs, and facts that tests can assert against.
    """
    if not text.strip():
        return ()
    normalized = f" {term_key(text)} "
    found: list[InterpretationConcept] = []
    seen: set[str] = set()
    for alias_key, concept in sorted(_ALIAS_INDEX.items(), key=lambda item: (-len(item[0]), item[0])):
        if not alias_key or concept.label in seen:
            continue
        pattern = rf"(?<![a-z0-9]){re.escape(alias_key)}(?![a-z0-9])"
        if re.search(pattern, normalized):
            found.append(concept)
            seen.add(concept.label)
    return tuple(found)


def concept_node(concept: InterpretationConcept, *, source: str = "") -> Node:
    return Node(
        id=interpretation_concept_id(concept),
        label=concept.label,
        kind=concept.kind,
        summary=f"interpretation layer: {concept.layer}",
        facts=concept.facts,
        source=source,
        confidence=0.9,
    )


def link_interpretation_concepts(
    source_id: str,
    text: str,
    *,
    source: str = "",
    source_location: str = "",
) -> tuple[dict[str, Node], list[Edge]]:
    nodes: dict[str, Node] = {}
    edges: list[Edge] = []
    for concept in detect_interpretation_concepts(text):
        node = concept_node(concept, source=source)
        nodes[node.id] = node
        edges.append(Edge(
            source_id,
            node.id,
            "formalizes",
            weight=1.0,
            confidence=0.85,
            provenance="interpretation_registry",
            source_location=source_location,
        ))
    return nodes, edges


def link_source_interpretation_concepts(
    node: Node,
    *,
    source_location: str = "",
) -> tuple[dict[str, Node], list[Edge]]:
    text = " ".join((node.label, node.path, node.summary, " ".join(node.facts)))
    nodes: dict[str, Node] = {}
    edges: list[Edge] = []
    for concept in detect_interpretation_concepts(text):
        target = concept_node(concept, source=node.source)
        nodes[target.id] = target
        edges.append(Edge(
            node.id,
            target.id,
            "implements_algorithm",
            weight=1.0,
            confidence=0.8,
            provenance="interpretation_registry",
            source_location=source_location or node.path,
        ))
    return nodes, edges
