from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .core import Edge, Node
from .terms import canonical_concept_label, concept_id, normalize_label, term_key


_MD_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)
_RST_HEADING = re.compile(r"^(.+)\n([=\-~^\"#*+])\2{2,}\s*$", re.MULTILINE)
_HTML_HEADING = re.compile(r"<h([1-6])[^>]*>(.*?)</h\1>", re.IGNORECASE | re.DOTALL)
_EMPHASIS = re.compile(r"`([^`\n]{3,80})`|\*\*([^*\n]{3,80})\*\*")
_CAP_PHRASE = re.compile(r"\b([A-Z][A-Za-z0-9]+(?:\s+[A-Z][A-Za-z0-9]+){1,3})\b")
_WORD = re.compile(r"[A-Za-z][A-Za-z0-9_]{2,}")
_SENTENCE = re.compile(r"([A-Z0-9][^.!?\n]{20,220}[.!?])")

_STOP_CONCEPTS = {
    "The", "This", "That", "These", "Those", "And", "But", "For", "With",
    "From", "Into", "When", "Where", "What", "Why", "How", "TODO", "README",
    "Graph", "Code", "Rust", "Python", "Markdown", "JSON", "TOML",
}


@dataclass(frozen=True)
class DocumentInput:
    path: Path
    rel: str
    file_node_id: str
    text: str


def extract_document_context(
    docs: list[DocumentInput],
    file_map: dict[str, str],
    max_concepts_per_doc: int = 24,
) -> tuple[dict[str, Node], list[Edge]]:
    nodes: dict[str, Node] = {}
    edges: list[Edge] = []

    label_to_file = _file_label_index(file_map)

    for doc in docs:
        sections = _sections(doc)
        concept_counts: dict[str, int] = {}
        section_ids: list[str] = []

        for index, (level, title, start, end) in enumerate(sections):
            section_id = f"{doc.file_node_id}__section_{index + 1}"
            summary = normalize_label(title)
            nodes[section_id] = Node(
                id=section_id,
                label=summary,
                kind="section",
                path=doc.rel,
                summary=f"L{doc.text[:start].count(chr(10)) + 1}",
                facts=_section_facts(doc.text[start:end]),
                source=str(doc.path),
                confidence=0.85,
            )
            section_ids.append(section_id)
            edges.append(Edge(
                section_id,
                doc.file_node_id,
                "section_of",
                confidence=0.85,
                provenance="doc_heading",
                source_location=f"{doc.rel}:{doc.text[:start].count(chr(10)) + 1}",
            ))

            body = doc.text[start:end]
            for concept in _concepts(title + "\n" + body):
                key = term_key(concept)
                if not key:
                    continue
                concept_counts[key] = concept_counts.get(key, 0) + 1
                cid = concept_id(concept)
                if cid not in nodes:
                    nodes[cid] = Node(
                        id=cid,
                        label=canonical_concept_label(concept),
                        kind="concept",
                        summary="document concept",
                        confidence=0.7,
                        source=str(doc.path),
                    )
                edges.append(Edge(
                    section_id,
                    cid,
                    "discusses",
                    weight=1.0,
                    confidence=0.65,
                    provenance="doc_heading",
                    source_location=doc.rel,
                ))

            for file_label, target_id in label_to_file.items():
                if file_label.lower() in body.lower() and target_id != doc.file_node_id:
                    edges.append(Edge(
                        section_id,
                        target_id,
                        "mentions",
                        weight=0.5,
                        confidence=0.5,
                        provenance="doc_reference",
                        source_location=doc.rel,
                    ))

        # If a document has no headings, make one coarse section so docs are not
        # invisible to graph retrieval.
        if not section_ids and doc.text.strip():
            section_id = f"{doc.file_node_id}__section_1"
            title = Path(doc.rel).stem.replace("-", " ").replace("_", " ").title()
            nodes[section_id] = Node(
                id=section_id,
                label=title,
                kind="section",
                path=doc.rel,
                summary="L1",
                facts=_section_facts(doc.text),
                source=str(doc.path),
                confidence=0.65,
            )
            edges.append(Edge(section_id, doc.file_node_id, "section_of", confidence=0.65, provenance="doc_coarse"))
            for concept in _concepts(doc.text)[:max_concepts_per_doc]:
                cid = concept_id(concept)
                nodes.setdefault(cid, Node(cid, canonical_concept_label(concept), "concept", summary="document concept", confidence=0.6))
                edges.append(Edge(section_id, cid, "discusses", confidence=0.55, provenance="doc_coarse"))

        # Cap concept fanout per document deterministically after extraction.
        if len(concept_counts) > max_concepts_per_doc:
            keep = {
                concept_key for concept_key, _count in sorted(concept_counts.items(), key=lambda item: (-item[1], item[0]))[:max_concepts_per_doc]
            }
            edges = [
                edge for edge in edges
                if edge.type != "discusses"
                or edge.target not in nodes
                or term_key(nodes[edge.target].label) in keep
                or not edge.source.startswith(doc.file_node_id + "__section_")
            ]

    return nodes, _dedupe_edges(edges)


def _sections(doc: DocumentInput) -> list[tuple[int, str, int, int]]:
    headings: list[tuple[int, str, int]] = []
    suffix = doc.path.suffix.lower()
    if suffix in {".md", ".mdx", ".txt"}:
        for m in _MD_HEADING.finditer(doc.text):
            headings.append((len(m.group(1)), normalize_label(m.group(2)), m.start()))
    elif suffix == ".rst":
        for m in _RST_HEADING.finditer(doc.text):
            headings.append((1, normalize_label(m.group(1)), m.start()))
    elif suffix in {".html", ".htm"}:
        for m in _HTML_HEADING.finditer(doc.text):
            headings.append((int(m.group(1)), normalize_label(re.sub(r"<[^>]+>", "", m.group(2))), m.start()))

    sections: list[tuple[int, str, int, int]] = []
    for idx, (level, title, start) in enumerate(headings):
        end = headings[idx + 1][2] if idx + 1 < len(headings) else len(doc.text)
        sections.append((level, title, start, end))
    return sections


def _concepts(text: str) -> list[str]:
    concepts: list[str] = []
    for m in _EMPHASIS.finditer(text):
        value = normalize_label(m.group(1) or m.group(2) or "")
        if _valid_concept(value):
            concepts.append(value)
    for m in _CAP_PHRASE.finditer(text):
        value = normalize_label(m.group(1))
        if _valid_concept(value):
            concepts.append(value)
    # Add snake_case / kebab-like technical terms sparingly.
    for word in _WORD.findall(text):
        if ("_" in word or len(word) >= 12) and _valid_concept(word):
            concepts.append(word)
    return list(dict.fromkeys(concepts))


def _valid_concept(value: str) -> bool:
    if not value or value in _STOP_CONCEPTS:
        return False
    if len(value) < 3 or len(value) > 80:
        return False
    if value.isdigit():
        return False
    if len(value.split()) == 1 and value[0].isupper() and value[1:].islower():
        return False
    return True


def _section_facts(text: str, limit: int = 1) -> tuple[str, ...]:
    body = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
    body = re.sub(r"`([^`]+)`", r"\1", body)
    body = re.sub(r"\[[^\]]+\]\([^)]+\)", " ", body)
    facts: list[str] = []
    for match in _SENTENCE.finditer(body):
        fact = normalize_label(match.group(1))
        if fact and not fact.startswith("#") and fact not in facts:
            facts.append(fact[:220])
        if len(facts) >= limit:
            break
    return tuple(facts)


def _file_label_index(file_map: dict[str, str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for rel, node_id in file_map.items():
        path = Path(rel)
        if len(path.name) >= 3:
            out[path.name] = node_id
        if len(path.stem) >= 3:
            out[path.stem] = node_id
    return out


def _dedupe_edges(edges: list[Edge]) -> list[Edge]:
    seen: set[tuple[str, str, str]] = set()
    out: list[Edge] = []
    for edge in edges:
        key = (edge.source, edge.target, edge.type)
        if key not in seen:
            seen.add(key)
            out.append(edge)
    return out
