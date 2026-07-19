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
        aliases=("Tree Knapsack", "Topologically-Connected Tree Knapsack", "Connected Tree Knapsack", "Dynamic Programming"),
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
        label="Regularized Utility Budgeting",
        kind="math_concept",
        layer="budgeting",
        aliases=("Regularized Utility", "Regularized Budget Heuristic", "Information-Gain Regularization", "budget allocation"),
        facts=("layer:budgeting", "role:budget_allocation", "math:optimization"),
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

_ALIAS_INDEX: dict[str, InterpretationConcept] = {}
for _concept in INTERPRETATION_CONCEPTS:
    for _alias in _concept.aliases:
        if _alias_key := term_key(_alias):
            _ALIAS_INDEX[_alias_key] = _concept

# The registry is immutable at runtime, so compile its longest-first matcher
# once. Scans call concept detection per source node; rebuilding this ordering
# and every regex per call was pure repeated work.
_ALIAS_MATCHERS = tuple(
    (
        re.compile(rf"(?<![a-z0-9]){re.escape(alias_key)}(?![a-z0-9])"),
        concept,
    )
    for alias_key, concept in sorted(
        _ALIAS_INDEX.items(),
        key=lambda item: (-len(item[0]), item[0]),
    )
)

_INTERPRETATION_PROVENANCE = "interpretation_registry"
_FORMALIZES_CONFIDENCE = 0.85
_IMPLEMENTS_CONFIDENCE = 0.8


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
    normalized = term_key(text)
    found: list[InterpretationConcept] = []
    seen: set[str] = set()
    for pattern, concept in _ALIAS_MATCHERS:
        if concept.label in seen:
            continue
        if pattern.search(normalized):
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
    return _link_detected_concepts(
        source_id,
        text,
        relation="formalizes",
        confidence=_FORMALIZES_CONFIDENCE,
        source=source,
        source_location=source_location,
    )


def link_source_interpretation_concepts(
    node: Node,
    *,
    source_location: str = "",
) -> tuple[dict[str, Node], list[Edge]]:
    text = " ".join((node.label, node.path, node.summary, " ".join(node.facts)))
    return _link_detected_concepts(
        node.id,
        text,
        relation="implements_algorithm",
        confidence=_IMPLEMENTS_CONFIDENCE,
        source=node.source,
        source_location=source_location or node.path,
    )


def _link_detected_concepts(
    source_id: str,
    text: str,
    *,
    relation: str,
    confidence: float,
    source: str,
    source_location: str,
) -> tuple[dict[str, Node], list[Edge]]:
    """Materialize registry matches as nodes plus one typed edge per match."""
    nodes: dict[str, Node] = {}
    edges: list[Edge] = []
    for concept in detect_interpretation_concepts(text):
        target = concept_node(concept, source=source)
        nodes[target.id] = target
        edges.append(Edge(
            source_id,
            target.id,
            relation,
            weight=1.0,
            confidence=confidence,
            provenance=_INTERPRETATION_PROVENANCE,
            source_location=source_location,
        ))
    return nodes, edges
