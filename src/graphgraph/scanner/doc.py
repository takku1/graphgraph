from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

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
_ORDERED_LIST_ITEM = re.compile(r"(?m)^[ \t]*\d+[.)]\s+\S")
MAX_PARAGRAPH_FACT_CHARS = 1200

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
    max_mentions_per_section: int = 12,
    max_sections_per_doc: int = 256,
    max_paragraphs_per_section: int = 12,
    profile: Callable[[str, float, int, int, bool], None] | None = None,
) -> tuple[dict[str, Node], list[Edge]]:
    nodes: dict[str, Node] = {}
    edges: list[Edge] = []

    file_index = _file_reference_index(file_map)
    symbol_index = _symbol_reference_index(symbol_map or {})

    for doc in docs:
        doc_started = time.perf_counter()
        all_sections = _sections(doc)
        sections = all_sections[:max_sections_per_doc]
        truncated = len(all_sections) > len(sections)
        concept_counts: dict[str, int] = {}
        section_ids: list[str] = []
        paragraph_count = 0

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

            paragraphs, paragraphs_truncated = _paragraphs(
                doc.text,
                start,
                end,
                limit=max_paragraphs_per_section,
            )
            truncated = truncated or paragraphs_truncated
            for paragraph_index, (line, paragraph) in enumerate(paragraphs, 1):
                paragraph_id = f"{section_id}__paragraph_{paragraph_index}"
                nodes[paragraph_id] = Node(
                    id=paragraph_id,
                    label=_paragraph_label(paragraph),
                    kind="paragraph",
                    path=doc.rel,
                    summary=f"L{line}",
                    facts=(paragraph[:MAX_PARAGRAPH_FACT_CHARS],),
                    parent=section_id,
                    source=str(doc.path),
                    confidence=0.82,
                )
                edges.append(Edge(
                    section_id,
                    paragraph_id,
                    "contains",
                    confidence=0.9,
                    provenance="doc_paragraph",
                    source_location=f"{doc.rel}:{line}",
                ))
                paragraph_count += 1

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

            if symbol_index[0]:
                for target_id, weight in _bounded_symbol_references(
                    body,
                    body_keys,
                    symbol_index,
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

            for target_id in _bounded_file_mentions(
                body,
                file_index,
                exclude=doc.file_node_id,
                limit=max_mentions_per_section,
            ):
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
            paragraphs, paragraphs_truncated = _paragraphs(
                doc.text,
                0,
                len(doc.text),
                limit=max_paragraphs_per_section,
            )
            truncated = truncated or paragraphs_truncated
            for paragraph_index, (line, paragraph) in enumerate(paragraphs, 1):
                paragraph_id = f"{section_id}__paragraph_{paragraph_index}"
                nodes[paragraph_id] = Node(
                    id=paragraph_id,
                    label=_paragraph_label(paragraph),
                    kind="paragraph",
                    path=doc.rel,
                    summary=f"L{line}",
                    facts=(paragraph[:MAX_PARAGRAPH_FACT_CHARS],),
                    parent=section_id,
                    source=str(doc.path),
                    confidence=0.72,
                )
                edges.append(Edge(
                    section_id,
                    paragraph_id,
                    "contains",
                    confidence=0.8,
                    provenance="doc_paragraph",
                    source_location=f"{doc.rel}:{line}",
                ))
                paragraph_count += 1
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
        if profile is not None:
            profile(
                doc.rel,
                (time.perf_counter() - doc_started) * 1000.0,
                len(sections),
                paragraph_count,
                truncated,
            )

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
    symbol_index: tuple[dict[str, str], tuple[int, ...]],
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
    aliases, alias_lengths = symbol_index
    body_tokens = term_key(body).split()
    occurrences: dict[str, int] = {}
    for size in alias_lengths:
        if size > len(body_tokens):
            continue
        for index in range(len(body_tokens) - size + 1):
            candidate = " ".join(body_tokens[index:index + size])
            if candidate in aliases:
                occurrences[candidate] = occurrences.get(candidate, 0) + 1

    best: dict[str, tuple[tuple[int, int, int, str], float]] = {}
    candidate_aliases = set(occurrences) | (body_keys & aliases.keys())
    for normalized_alias in candidate_aliases:
        target_id = aliases[normalized_alias]
        if target_id == exclude:
            continue
        if len(normalized_alias) < 3:
            continue
        canonical = normalized_alias in body_keys
        occurrence_count = occurrences.get(normalized_alias, 0)
        if not canonical and occurrence_count == 0:
            continue
        rank = (1 if canonical else 0, min(occurrence_count, 9), len(normalized_alias), normalized_alias)
        candidate = (rank, 1.0 if canonical else 0.9)
        if target_id not in best or candidate[0] > best[target_id][0]:
            best[target_id] = candidate
    ranked = sorted(best.items(), key=lambda item: item[1][0], reverse=True)
    return [(target_id, value[1]) for target_id, value in ranked[:max(0, limit)]]


def _symbol_reference_index(symbol_map: dict[str, str]) -> tuple[dict[str, str], tuple[int, ...]]:
    """Normalize symbol aliases once for all document sections in a scan."""
    aliases: dict[str, str] = {}
    lengths: set[int] = set()
    for alias, target_id in symbol_map.items():
        normalized = term_key(alias)
        if len(normalized) < 3:
            continue
        aliases.setdefault(normalized, target_id)
        lengths.add(len(normalized.split()))
    return aliases, tuple(sorted(lengths))


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


def _file_reference_index(file_map: dict[str, str]) -> tuple[dict[str, tuple[str, ...]], tuple[int, ...]]:
    targets: dict[str, list[str]] = {}
    lengths: set[int] = set()
    for rel, node_id in file_map.items():
        path = Path(rel)
        for raw in (path.name, path.stem):
            normalized = term_key(raw)
            if len(normalized) >= 3:
                bucket = targets.setdefault(normalized, [])
                if node_id not in bucket:
                    bucket.append(node_id)
                lengths.add(len(normalized.split()))
    return {alias: tuple(node_ids) for alias, node_ids in targets.items()}, tuple(sorted(lengths))


def _bounded_file_mentions(
    body: str,
    index: tuple[dict[str, tuple[str, ...]], tuple[int, ...]],
    *,
    exclude: str,
    limit: int,
) -> list[str]:
    aliases, lengths = index
    tokens = term_key(body).split()
    hits: dict[str, tuple[int, str]] = {}
    for size in lengths:
        if size > len(tokens):
            continue
        for position in range(len(tokens) - size + 1):
            alias = " ".join(tokens[position:position + size])
            targets = aliases.get(alias, ())
            for target in targets:
                if target == exclude:
                    continue
                candidate = (len(alias), alias)
                if target not in hits or candidate > hits[target]:
                    hits[target] = candidate
    return [target for target, _ in sorted(hits.items(), key=lambda item: item[1], reverse=True)[:limit]]


def _paragraphs(text: str, start: int, end: int, *, limit: int) -> tuple[list[tuple[int, str]], bool]:
    body = text[start:end]
    paragraphs: list[tuple[int, str]] = []
    for match in re.finditer(r"(?:^|\n\s*\n)([^\n#][\s\S]*?)(?=\n\s*\n|\Z)", body):
        for offset, raw in _paragraph_chunks(match.group(1)):
            if not raw or raw.startswith("```"):
                continue
            normalized = normalize_label(re.sub(r"\s+", " ", raw))
            if len(normalized) < 24:
                continue
            line = text[:start + match.start(1) + offset].count("\n") + 1
            paragraphs.append((line, normalized))
            if len(paragraphs) > max(0, limit):
                return paragraphs[:max(0, limit)], True
    return paragraphs, False


def _paragraph_chunks(raw: str) -> tuple[tuple[int, str], ...]:
    """Split consecutive Markdown list items without losing continuations."""
    item_starts = [match.start() for match in _ORDERED_LIST_ITEM.finditer(raw)]
    if not item_starts:
        stripped = raw.strip()
        return ((raw.find(stripped), stripped),) if stripped else ()

    boundaries = ([0] if raw[:item_starts[0]].strip() else []) + item_starts + [len(raw)]
    chunks: list[tuple[int, str]] = []
    for chunk_start, chunk_end in zip(boundaries, boundaries[1:]):
        chunk = raw[chunk_start:chunk_end]
        stripped = chunk.strip()
        if not stripped:
            continue
        chunks.append((chunk_start + chunk.find(stripped), stripped))
    return tuple(chunks)


def _paragraph_label(paragraph: str) -> str:
    without_marker = re.sub(r"^\d+[.)]\s+", "", paragraph)
    first = re.split(r"(?<=[.!?])\s+", without_marker, maxsplit=1)[0]
    return first[:120]
