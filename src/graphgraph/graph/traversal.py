from __future__ import annotations

from dataclasses import dataclass

from .ontology import relation_spec


@dataclass(frozen=True)
class TraversalPolicy:
    query_class: str
    preferred_families: tuple[str, ...]
    preferred_relations: tuple[str, ...]
    weak_edge_limit: int
    min_confidence: float
    direction: str = "both"


DEFAULT_POLICY = TraversalPolicy(
    query_class="default",
    preferred_families=("execution", "dependency", "hierarchy", "dataflow"),
    preferred_relations=("calls", "imports", "contains", "reads", "writes", "uses"),
    weak_edge_limit=12,
    min_confidence=0.0,
)

BLAST_IMPACT_RELATIONS = frozenset({"calls", "imports", "imports_from", "tests", "implements", "references"})
BLAST_SUPPORT_RELATIONS = frozenset({"tests", "configures", "contains", "references", "fixes", "explains"})
BLAST_OUTGOING_RELATIONS = frozenset(
    {"calls", "imports", "imports_from", "reads", "writes", "uses", "implements", "contains"}
)
BLAST_IMPACT_SHARE = 0.65
BLAST_SUPPORT_SHARE = 0.20


POLICIES: dict[str, TraversalPolicy] = {
    "direct_lookup": TraversalPolicy(
        "direct_lookup",
        ("hierarchy", "dependency", "execution", "document"),
        ("contains", "imports", "imports_from", "calls", "references", "links"),
        weak_edge_limit=8,
        min_confidence=0.0,
        direction="out",
    ),
    "reverse_lookup": TraversalPolicy(
        "reverse_lookup",
        ("dependency", "execution", "type", "validation", "document", "hierarchy"),
        ("imports", "imports_from", "calls", "implements", "tests", "references", "links", "contains"),
        weak_edge_limit=12,
        min_confidence=0.0,
        direction="in",
    ),
    "affected_tests": TraversalPolicy(
        "affected_tests",
        ("validation", "execution", "mention", "hierarchy", "dependency"),
        ("tests", "calls", "references", "contains", "imports_from", "imports"),
        weak_edge_limit=10,
        min_confidence=0.0,
        direction="both",
    ),
    "multi_hop_path": TraversalPolicy(
        "multi_hop_path",
        ("execution", "dependency", "dataflow", "type"),
        ("calls", "imports", "imports_from", "reads", "writes", "implements", "uses", "contains", "references"),
        weak_edge_limit=6,
        min_confidence=0.2,
    ),
    "blast_radius": TraversalPolicy(
        "blast_radius",
        ("execution", "dependency", "dataflow", "validation", "configuration", "type", "interpretation"),
        ("calls", "imports", "imports_from", "reads", "writes", "tests", "configures", "implements", "formalizes", "implements_algorithm", "contains", "references"),
        weak_edge_limit=10,
        min_confidence=0.0,
    ),
    "subsystem_summary": TraversalPolicy(
        "subsystem_summary",
        ("hierarchy", "dependency", "execution", "interpretation", "document", "type"),
        ("contains", "imports", "imports_from", "calls", "formalizes", "implements_algorithm", "links", "references", "implements", "explains", "discusses", "mentions", "section_of"),
        weak_edge_limit=20,
        min_confidence=0.0,
    ),
    "doc_summary": TraversalPolicy(
        "doc_summary",
        ("document", "hierarchy", "interpretation"),
        ("section_of", "contains", "explains", "discusses", "mentions", "links", "references"),
        weak_edge_limit=20,
        min_confidence=0.0,
        direction="both",
    ),
    "negative_query": TraversalPolicy(
        "negative_query",
        ("execution", "dependency", "hierarchy"),
        ("calls", "imports", "imports_from", "contains", "references"),
        weak_edge_limit=8,
        min_confidence=0.3,
    ),
    # "What changed recently touching this file/subsystem" -- answers with
    # the commit/fixes history data `extract_commit_history` already puts in
    # the graph when a scan runs with history=True, which no other policy
    # prioritizes: "history" was in no preferred_families and "fixes" in no
    # preferred_relations anywhere above, so those edges only ever survived
    # as unprioritized weak-edge-limit leftovers under every other query
    # class. Direction="in" from a file anchor finds the commit nodes that
    # point at it (fixes edges are commit -> file), the same reasoning
    # reverse_lookup uses to find callers.
    "recent_changes": TraversalPolicy(
        "recent_changes",
        ("history", "hierarchy"),
        ("fixes", "contains"),
        weak_edge_limit=20,
        min_confidence=0.0,
        direction="in",
    ),
}


def traversal_policy(query_class: str) -> TraversalPolicy:
    return POLICIES.get(query_class, DEFAULT_POLICY)


def relation_rank(relation: str, policy: TraversalPolicy) -> tuple[int, int, str]:
    spec = relation_spec(relation)
    relation_pos = policy.preferred_relations.index(relation) if relation in policy.preferred_relations else 999
    family_pos = policy.preferred_families.index(spec.family) if spec.family in policy.preferred_families else 999
    return relation_pos, family_pos, relation
