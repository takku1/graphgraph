from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from ..concepts import link_interpretation_concepts
from ..concepts.terms import canonical_concept_label, concept_id, normalize_label, term_key
from ..graph.core import Edge, Node
from ..graph.operations import _dedupe_edges

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
    symbol_map: dict[str, str] | None = None,
    max_concepts_per_doc: int = 24,
    max_explains_per_section: int = 12,
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
            interpretation_nodes, interpretation_edges = link_interpretation_concepts(
                section_id,
                title + "\n" + body,
                source=str(doc.path),
                source_location=doc.rel,
            )
            nodes.update(interpretation_nodes)
            edges.extend(interpretation_edges)

            body_keys: set[str] = set()
            for concept in _concepts(title + "\n" + body):
                key = term_key(concept)
                if not key:
                    continue
                body_keys.add(key)
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

            if symbol_map:
                for target_id, weight in _bounded_symbol_references(
                    body,
                    body_keys,
                    symbol_map,
                    exclude=doc.file_node_id,
                    limit=max_explains_per_section,
                ):
                    edges.append(Edge(
                        section_id,
                        target_id,
                        "explains",
                        weight=weight,
                        confidence=0.8,
                        provenance="doc_reference",
                        source_location=doc.rel,
                    ))

            for file_label, target_id in label_to_file.items():
                # Word-boundary match, not raw substring: file stems are
                # commonly short/generic words (e.g. "core", "io", "app"),
                # and a bare `in` check matches them inside unrelated words
                # too (e.g. stem "core" inside "score"), producing false
                # "mentions" edges to the wrong file.
                pattern = r"\b" + re.escape(file_label.lower()) + r"\b"
                if target_id != doc.file_node_id and re.search(pattern, body.lower()):
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
            interpretation_nodes, interpretation_edges = link_interpretation_concepts(
                section_id,
                doc.text,
                source=str(doc.path),
                source_location=doc.rel,
            )
            nodes.update(interpretation_nodes)
            edges.extend(interpretation_edges)
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

    deduped_edges = _dedupe_edges(edges)
    incident_nodes = {edge.source for edge in deduped_edges} | {edge.target for edge in deduped_edges}
    nodes = {
        node_id: node
        for node_id, node in nodes.items()
        if node.kind != "concept" or node_id in incident_nodes
    }
    return nodes, deduped_edges


def _bounded_symbol_references(
    body: str,
    body_keys: set[str],
    symbol_map: dict[str, str],
    *,
    exclude: str,
    limit: int,
) -> list[tuple[str, float]]:
    """Return the strongest bounded symbol references in a doc section.

    The old all-alias substring loop linked short names such as ``run`` inside
    unrelated prose and could emit thousands of explains edges per document.
    Token boundaries remove those false positives; one best alias per target
    and a section-local cap keep the semantic layer useful and sublinear.
    """
    normalized_body = term_key(body)
    best: dict[str, tuple[tuple[int, int, int, str], float]] = {}
    for alias, target_id in symbol_map.items():
        if not alias or target_id == exclude:
            continue
        normalized_alias = term_key(alias)
        if len(normalized_alias) < 3:
            continue
        canonical = normalized_alias in body_keys
        pattern = rf"(?<![a-z0-9]){re.escape(normalized_alias)}(?![a-z0-9])"
        occurrences = len(re.findall(pattern, normalized_body))
        if not canonical and occurrences == 0:
            continue
        rank = (1 if canonical else 0, min(occurrences, 9), len(normalized_alias), normalized_alias)
        candidate = (rank, 1.0 if canonical else 0.9)
        if target_id not in best or candidate[0] > best[target_id][0]:
            best[target_id] = candidate
    ranked = sorted(best.items(), key=lambda item: item[1][0], reverse=True)
    return [(target_id, value[1]) for target_id, value in ranked[:max(0, limit)]]


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
