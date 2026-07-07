from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RelationSpec:
    name: str
    family: str
    direction: str = "directed"
    strength: float = 1.0
    traversable: bool = True
    weak: bool = False
    inverse: str = ""
    description: str = ""


DEFAULT_RELATIONS: dict[str, RelationSpec] = {
    "calls": RelationSpec("calls", "execution", strength=1.0, description="Source invokes target."),
    "imports": RelationSpec("imports", "dependency", strength=0.95, description="Source imports target module/file."),
    "imports_from": RelationSpec("imports_from", "dependency", strength=0.95, description="Source imports symbol from target."),
    "reads": RelationSpec("reads", "dataflow", strength=0.9, description="Source reads target data."),
    "writes": RelationSpec("writes", "dataflow", strength=0.9, description="Source writes target data."),
    "uses": RelationSpec("uses", "dependency", strength=0.8, description="Source uses target."),
    "tests": RelationSpec("tests", "validation", strength=0.85, description="Source tests target."),
    "configures": RelationSpec("configures", "configuration", strength=0.85, description="Source configures target."),
    "contains": RelationSpec("contains", "hierarchy", strength=0.7, description="Source contains target."),
    "implements": RelationSpec("implements", "type", strength=0.9, description="Source implements target contract."),
    "references": RelationSpec("references", "mention", strength=0.7, description="Source mentions target."),
    "fixes": RelationSpec("fixes", "history", strength=0.75, description="Source commit fixed/touched target file (from git log)."),
    "links": RelationSpec("links", "document", strength=0.55, weak=True, description="Source links to target."),
    "includes": RelationSpec("includes", "document", strength=0.6, weak=True, description="Source includes target."),
    "mentions": RelationSpec("mentions", "document", strength=0.5, weak=True, description="Source text mentions target concept."),
    "discusses": RelationSpec("discusses", "document", strength=0.65, description="Source document section discusses target concept."),
    "section_of": RelationSpec("section_of", "document", strength=0.08, weak=True, description="Source section belongs to target document."),
    "explains": RelationSpec("explains", "document", strength=0.95, description="Source text explains target concept or implementation detail."),
    "formalizes": RelationSpec("formalizes", "interpretation", strength=0.9, description="Source grounds a known algorithm, math, runtime, or model-interpretation concept."),
    "implements_algorithm": RelationSpec("implements_algorithm", "interpretation", strength=0.9, description="Source implements a known algorithmic or mathematical concept."),
    "relates": RelationSpec("relates", "generic", strength=0.35, weak=True, description="Generic relation."),
    "similar_to": RelationSpec("similar_to", "similarity", direction="symmetric", strength=0.4, weak=True),
    "contradicts": RelationSpec("contradicts", "logic", strength=0.9, description="Source contradicts target."),
    "supports": RelationSpec("supports", "logic", strength=0.8, description="Source supports target."),
    "used_input": RelationSpec("used_input", "decision_trace", strength=0.9, description="Decision trace used target input."),
    "applied_policy": RelationSpec("applied_policy", "decision_trace", strength=1.0, description="Decision trace applied target policy."),
    "constrained_by": RelationSpec("constrained_by", "governance", strength=0.9, description="Source is constrained by target policy."),
    "ast_child": RelationSpec("ast_child", "ast", strength=0.75, description="AST parent contains child node."),
    "control_flow": RelationSpec("control_flow", "control", strength=0.85, description="Execution can flow from source to target."),
    "control_dep": RelationSpec("control_dep", "control", strength=0.8, description="Target is control-dependent on source."),
    "data_flow": RelationSpec("data_flow", "dataflow", strength=0.9, description="Data can flow from source to target."),
    "defines": RelationSpec("defines", "symbol", strength=0.9, description="Source defines target symbol."),
    "field_of": RelationSpec("field_of", "type", strength=0.8, description="Source field belongs to target type."),
    "type_of": RelationSpec("type_of", "type", strength=0.8, description="Source has target type."),
    "returns": RelationSpec("returns", "type", strength=0.75, description="Source returns target."),
}


PROVENANCE_CONFIDENCE = {
    "tree_sitter": 0.95,
    "cpg": 0.95,
    "regex_ast": 0.8,
    "regex_import": 0.85,
    "regex_reference": 0.45,
    "semantic_llm": 0.65,
    "human": 1.0,
    "decision_trace": 1.0,
    "imported": 0.75,
    "extracted": 0.8,
    "inferred": 0.55,
    "ambiguous": 0.35,
    "git_history": 0.75,
}


def relation_spec(relation: str) -> RelationSpec:
    return DEFAULT_RELATIONS.get(
        relation,
        RelationSpec(relation, "unknown", strength=0.5, weak=True, description="Unknown relation type."),
    )


def traversal_strength(relation: str) -> float:
    spec = relation_spec(relation)
    return spec.strength if spec.traversable else 0.0


def is_weak_relation(relation: str) -> bool:
    return relation_spec(relation).weak


def provenance_confidence(provenance: str) -> float:
    return PROVENANCE_CONFIDENCE.get(provenance, 0.6)
