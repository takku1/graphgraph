from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from graphgraph import (
    scan_directory,
)
from graphgraph.concepts.terms import term_key
from graphgraph.graph.ontology import relation_spec
from graphgraph.scanner.doc import DocumentInput, extract_document_context
from graphgraph.scanner.frontends import (
    ExtractionResult,
    SourceFile,
)


class DocsScannerTest(unittest.TestCase):
    """scanner/doc.py: document extraction and sectioning."""

    def test_scanner_markdown_links(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "index.md").write_text("See [guide](./guide.md) for details.\n", encoding="utf-8")
            (root / "guide.md").write_text("# Guide\n", encoding="utf-8")
            graph = scan_directory(root)
            self.assertEqual(len(graph.nodes), 2)
            edge_types = {e.type for e in graph.edges}
            self.assertIn("links", edge_types)

    def test_document_context_extracts_sections_and_concepts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            doc = root / "README.md"
            doc.write_text("# Auth System\n\nThe **Token Store** calls `AuthService`.\n", encoding="utf-8")
            file_map = {"README.md": "README_md", "auth.py": "auth_py"}
            nodes, edges = extract_document_context(
                [DocumentInput(doc, "README.md", "README_md", doc.read_text(encoding="utf-8"))],
                file_map,
            )
            kinds = {node.kind for node in nodes.values()}
            edge_types = {edge.type for edge in edges}
            self.assertIn("section", kinds)
            self.assertIn("concept", kinds)
            self.assertIn("section_of", edge_types)
            self.assertIn("discusses", edge_types)
            self.assertEqual(
                relation_spec("explains").description,
                "Source text explains target concept or implementation detail.",
            )
            section = next(node for node in nodes.values() if node.kind == "section")
            self.assertTrue(section.facts)

    def test_document_context_indexes_body_paragraphs_and_reports_truncation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            doc = root / "roadmap.md"
            text = (
                "# Phase 3\n\n"
                "2026-07-14: The real-source benchmark now records a phase profile.\n\n"
                "The preview command must preserve every requested implementation facet.\n\n"
                "The remaining exit criterion is grounded roadmap retrieval from body text.\n"
            )
            doc.write_text(text, encoding="utf-8")
            profiles: list[tuple[str, float, int, int, bool]] = []
            nodes, edges = extract_document_context(
                [DocumentInput(doc, "docs/roadmap.md", "roadmap_md", text)],
                {"docs/roadmap.md": "roadmap_md"},
                max_paragraphs_per_section=2,
                profile=lambda *values: profiles.append(values),
            )
            paragraphs = [node for node in nodes.values() if node.kind == "paragraph"]
            self.assertEqual(len(paragraphs), 2)
            self.assertTrue(any("real-source benchmark" in node.facts[0] for node in paragraphs))
            self.assertEqual(len([edge for edge in edges if edge.type == "contains"]), 2)
            self.assertEqual(profiles[0][0], "docs/roadmap.md")
            self.assertEqual(profiles[0][2:], (1, 2, True))

    def test_document_context_indexes_each_markdown_list_item_as_a_paragraph(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            doc = root / "contract.md"
            text = (
                "# Decision rules\n\n"
                "1. Audit ignore rules before building the graph.\n"
                "2. Validate the saved graph before querying it.\n"
                "3. Accept a build only after checking the selected frontend, "
                "fallback counts, validation, and truncation.\n"
            )
            doc.write_text(text, encoding="utf-8")

            nodes, _edges = extract_document_context(
                [DocumentInput(doc, "contract.md", "contract_md", text)],
                {"contract.md": "contract_md"},
            )

            paragraphs = sorted(
                (node for node in nodes.values() if node.kind == "paragraph"),
                key=lambda node: node.line or 0,
            )
            self.assertEqual([node.line for node in paragraphs], [3, 4, 5])
            self.assertEqual(paragraphs[2].label, "Accept a build only after checking the selected frontend, fallback counts, validation, and truncation")
            self.assertNotIn("1.", paragraphs[0].label)

    def test_document_context_indexes_each_unordered_list_item_as_a_paragraph(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            doc = root / "roadmap.md"
            text = (
                "## Probability & Statistics\n"
                "* `[~]` **Statistics:** Conjugate updates are implemented.\n"
                "* `[~]` **Stochastic Processes:** A Markov foothold is recognized, "
                "but stationarity remains unproved.\n"
                "* `[ ]` **Learning Theory:** PAC support remains absent.\n"
            )
            doc.write_text(text, encoding="utf-8")

            nodes, _edges = extract_document_context(
                [DocumentInput(doc, "roadmap.md", "roadmap_md", text)],
                {"roadmap.md": "roadmap_md"},
            )

            paragraphs = sorted(
                (node for node in nodes.values() if node.kind == "paragraph"),
                key=lambda node: node.line or 0,
            )
            self.assertEqual([node.line for node in paragraphs], [2, 3, 4])
            self.assertIn("Stochastic Processes", paragraphs[1].label)
            self.assertIn("stationarity remains unproved", paragraphs[1].facts[0])
            self.assertFalse(paragraphs[1].label.startswith("*"))

    def test_document_context_indexes_table_rows_and_reserves_rare_statuses(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            doc = root / "coverage.md"
            text = (
                "# Capability coverage\n\n"
                "| Capability | Status | Note |\n"
                "| --- | --- | --- |\n"
                "| Parser | `[x]` | Complete. |\n"
                "| Emitter | `[x]` | Complete. |\n"
                "| Optimizer | `[x]` | Complete. |\n"
                "| Solver | `[~]` | Bounded fragment only. |\n"
                "| Verifier | `[~]` | Partial proof surface. |\n"
                "| Symbolic PAC learning | `[ ]` | Not implemented. |\n"
            )
            doc.write_text(text, encoding="utf-8")

            nodes, _edges = extract_document_context(
                [DocumentInput(doc, "docs/roadmap/coverage.md", "coverage_md", text)],
                {"docs/roadmap/coverage.md": "coverage_md"},
                max_paragraphs_per_section=2,
            )

            paragraphs = sorted(
                (node for node in nodes.values() if node.kind == "paragraph"),
                key=lambda node: node.line or 0,
            )
            facts = [node.facts[0] for node in paragraphs]
            self.assertTrue(any("Symbolic PAC learning" in fact for fact in facts))
            self.assertTrue(any("| `[~]` |" in fact for fact in facts))
            self.assertTrue(all("\n" not in fact for fact in facts))
            self.assertFalse(any("| --- | --- |" in fact for fact in facts))

    def test_document_context_coarse_document_still_indexes_paragraphs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            doc = root / "notes.txt"
            text = (
                "The first implementation note contains enough grounded detail for retrieval.\n\n"
                "The second implementation note records the remaining validation requirement.\n"
            )
            doc.write_text(text, encoding="utf-8")
            nodes, edges = extract_document_context(
                [DocumentInput(doc, "notes.txt", "notes_txt", text)],
                {"notes.txt": "notes_txt"},
            )
            paragraphs = [node for node in nodes.values() if node.kind == "paragraph"]
            self.assertEqual(len(paragraphs), 2)
            self.assertTrue(all(node.parent == "notes_txt__section_1" for node in paragraphs))
            self.assertEqual(len([edge for edge in edges if edge.type == "contains"]), 2)

    def test_document_context_keeps_answer_at_end_of_bounded_long_paragraph(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            doc = root / "roadmap.md"
            text = (
                "# Phase 3\n\n"
                + "The benchmark records representative measurements and exact evidence gates. " * 10
                + "Phase 3 still needs pinned per-strategy yield thresholds.\n"
            )
            doc.write_text(text, encoding="utf-8")
            nodes, _edges = extract_document_context(
                [DocumentInput(doc, "roadmap.md", "roadmap_md", text)],
                {"roadmap.md": "roadmap_md"},
            )
            paragraph = next(node for node in nodes.values() if node.kind == "paragraph")
            self.assertIn("Phase 3 still needs pinned per-strategy yield thresholds", paragraph.facts[0])
            self.assertLessEqual(len(paragraph.facts[0]), 1200)

    def test_document_context_bounds_explains_and_requires_symbol_boundaries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            aliases = {f"symbol_{i}": f"S{i}" for i in range(20)}
            text = "# Details\n" + " ".join(aliases) + " running only\n"
            doc = root / "guide.md"
            doc.write_text(text, encoding="utf-8")
            aliases["run"] = "RUN"
            _nodes, edges = extract_document_context(
                [DocumentInput(doc, "guide.md", "guide_md", text)],
                {"guide.md": "guide_md"},
                symbol_map=aliases,
                max_explains_per_section=5,
            )
            explains = [edge for edge in edges if edge.type == "explains"]
            self.assertEqual(len(explains), 5)
            self.assertNotIn("RUN", {edge.target for edge in explains})

    def test_document_context_mentions_requires_word_boundary(self) -> None:
        # Regression: the "mentions" edge used a raw substring check
        # (file_label.lower() in body.lower()), so a short/generic file stem
        # like "core" matched inside unrelated words too -- e.g. "score"
        # contains "core" -- producing a false-positive mentions edge to the
        # wrong file. A genuine standalone mention (as its own word, or as
        # the full "core.py" filename) must still be detected.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            file_map = {"server/core.py": "server_core_py"}

            false_positive_doc = root / "R1.md"
            false_positive_doc.write_text(
                "# Notes\n\nThis module keeps a high score across requests.\n", encoding="utf-8"
            )
            _, edges1 = extract_document_context(
                [DocumentInput(false_positive_doc, "R1.md", "r1_md", false_positive_doc.read_text(encoding="utf-8"))],
                file_map,
            )
            self.assertFalse(
                [e for e in edges1 if e.type == "mentions"],
                "‘score’ must not match the file stem ‘core’ as a false-positive mention",
            )

            genuine_doc = root / "R2.md"
            genuine_doc.write_text("# Notes\n\nSee core.py for the implementation.\n", encoding="utf-8")
            _, edges2 = extract_document_context(
                [DocumentInput(genuine_doc, "R2.md", "r2_md", genuine_doc.read_text(encoding="utf-8"))],
                file_map,
            )
            mentions2 = [e for e in edges2 if e.type == "mentions"]
            self.assertEqual(len(mentions2), 1)
            self.assertEqual(mentions2[0].target, "server_core_py")

    def test_document_context_preserves_ambiguous_same_basename_mentions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            doc = root / "guide.md"
            text = "# Wiring\n\nBoth packages expose a core.py implementation entry point.\n"
            doc.write_text(text, encoding="utf-8")
            _, edges = extract_document_context(
                [DocumentInput(doc, "guide.md", "guide_md", text)],
                {
                    "server/core.py": "server_core_py",
                    "client/core.py": "client_core_py",
                    "guide.md": "guide_md",
                },
            )
            targets = {edge.target for edge in edges if edge.type == "mentions"}
            self.assertEqual(targets, {"server_core_py", "client_core_py"})

    def test_document_context_normalizes_duplicate_concepts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            doc = root / "README.md"
            doc.write_text(
                "# Concepts\n\nThe **Token Store** relates to `token-store` and Token Store.\n", encoding="utf-8"
            )
            nodes, edges = extract_document_context(
                [DocumentInput(doc, "README.md", "README_md", doc.read_text(encoding="utf-8"))],
                {"README.md": "README_md"},
            )
            token_nodes = [
                node for node in nodes.values() if node.kind == "concept" and term_key(node.label) == "token store"
            ]
            self.assertEqual(len(token_nodes), 1)
            discusses = [edge for edge in edges if edge.type == "discusses" and edge.target == token_nodes[0].id]
            self.assertEqual(len(discusses), 1)

    def test_document_context_prunes_concepts_removed_by_fanout_cap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            doc = root / "README.md"
            concepts = " ".join(f"`TechnicalConcept{i}`" for i in range(12))
            doc.write_text(f"# Concepts\n\n{concepts}\n", encoding="utf-8")
            nodes, edges = extract_document_context(
                [DocumentInput(doc, "README.md", "README_md", doc.read_text(encoding="utf-8"))],
                {"README.md": "README_md"},
                max_concepts_per_doc=3,
            )
            document_concepts = [node for node in nodes.values() if node.kind == "concept"]
            incident = {edge.source for edge in edges} | {edge.target for edge in edges}
            self.assertLessEqual(len(document_concepts), 3)
            self.assertTrue(all(node.id in incident for node in document_concepts))

    def test_scanner_docs_flag_adds_concepts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text(
                "# Runtime Context Graph\n\nDocuments mention AuthService.\n", encoding="utf-8"
            )
            graph = scan_directory(root, docs=True)
            self.assertEqual(graph.metadata["docs"], "true")
            self.assertIn("section", {node.kind for node in graph.nodes.values()})
            self.assertIn("concept", {node.kind for node in graph.nodes.values()})

    def test_scanner_docs_flag_links_symbols_to_docs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("# API\n\nThe `render_packet` helper is used here.\n", encoding="utf-8")
            (root / "render.py").write_text("def render_packet():\n    return None\n", encoding="utf-8")
            graph = scan_directory(root, docs=True, depth="symbols", frontend="regex")
            edge_types = {e.type for e in graph.edges}
            self.assertIn("explains", edge_types)
            self.assertTrue(any(edge.type == "explains" for edge in graph.edges))

    def test_scanner_generic_mentions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.txt").write_text("See the config module for settings.\n", encoding="utf-8")
            (root / "config.py").write_text("# config\n", encoding="utf-8")
            graph = scan_directory(root, generic_mentions=True)
            edge_types = {e.type for e in graph.edges}
            self.assertIn("references", edge_types)

    def test_symbol_extractor_receives_source_files_not_documents(self) -> None:
        captured_paths: list[str] = []

        class CapturingExtractor:
            def extract_symbols(
                self,
                files: list[SourceFile],
                max_total_symbols: int,
                context_nodes: dict | None = None,
            ) -> ExtractionResult:
                captured_paths.extend(source.rel for source in files)
                return ExtractionResult(nodes={}, edges=[], frontend="capture")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "app.py").write_text("def run():\n    pass\n", encoding="utf-8")
            (root / "README.md").write_text("# Usage\n\nRun the application.\n", encoding="utf-8")

            with patch(
                "graphgraph.scanner.core.select_extractor",
                return_value=CapturingExtractor(),
            ):
                graph = scan_directory(root, depth="symbols", docs=True)

        self.assertEqual(captured_paths, ["app.py"])
        self.assertTrue(
            any(
                node.path == "README.md" and node.kind == "section"
                for node in graph.nodes.values()
            )
        )
