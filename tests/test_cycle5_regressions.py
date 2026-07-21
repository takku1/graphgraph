from __future__ import annotations

import tempfile
import unittest
from json import loads
from pathlib import Path
from types import SimpleNamespace

from graphgraph import Graph, Node
from graphgraph.acceptance.live_validation import _prepare_validation_graph
from graphgraph.platform.semantic import SemanticIndex
from graphgraph.runtime.manifest import Manifest
from graphgraph.scanner import scan_directory
from graphgraph.services.context import _actionable_receipt
from graphgraph.services.native import scope_freshness
from graphgraph.services.snippets import render_source_snippets


class CycleFiveRegressionTest(unittest.TestCase):
    def test_source_snippet_cites_anchor_and_always_includes_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "src" / "pipeline.rs"
            source.parent.mkdir()
            source.write_text(
                "\n".join(
                    (
                        "// prelude",
                        "// context 2",
                        "// context 3",
                        "// context 4",
                        "// context 5",
                        "/// leading documentation",
                        "/// more documentation",
                        "pub fn fuse_elementwise() {",
                        "    run();",
                        "}",
                    )
                )
                + "\n",
                encoding="utf-8",
            )
            graph_path = root / ".graphgraph" / "graph.gg"
            graph = Graph(
                nodes={
                    "FUSE": Node(
                        "FUSE",
                        "fuse_elementwise",
                        "function",
                        "src/pipeline.rs",
                        summary="L8 pub fn fuse_elementwise()",
                    )
                }
            )

            excerpt = render_source_snippets(
                starts=["FUSE"],
                graph_path=graph_path,
                graph=graph,
                context_lines=6,
                max_lines=3,
            )

        self.assertIn("`src/pipeline.rs:8`", excerpt)
        self.assertIn("8 | pub fn fuse_elementwise() {", excerpt)
        self.assertNotIn("`src/pipeline.rs:2`", excerpt)

    def test_structural_facet_evidence_precedes_document_mentions(self) -> None:
        code = Node(
            "CODE",
            "default_advisors",
            "function",
            "src/lib.rs",
            summary="L30 fn default_advisors",
        )
        doc = Node(
            "DOC",
            "old audit",
            "paragraph",
            "docs/audit.md",
            summary="L12 audit",
        )
        result = SimpleNamespace(
            metadata={
                "answerability": {"status": "answerable"},
                "facet_coverage": {
                    "fulfilled": [{"facet": "registers advisor banks", "evidence": ["DOC"]}],
                    "unfulfilled": [],
                },
                "structural_facet_coverage": {
                    "fulfilled": [{"facet": "registers advisor banks", "evidence": ["CODE"]}],
                    "unfulfilled": [],
                },
            },
            matches=(
                SimpleNamespace(node=doc),
                SimpleNamespace(node=code),
            ),
            starts=("DOC",),
            edges=(),
        )

        receipt = _actionable_receipt(
            result,
            {"freshness": {"fresh": True}},
            query_class="reverse_lookup",
            graph=Graph(nodes={"CODE": code, "DOC": doc}),
        )

        self.assertEqual(receipt["evidence_points"][0]["id"], "CODE")
        self.assertNotIn("freshness", receipt)
        self.assertEqual(receipt["freshness_ref"], "$.freshness")

    def test_freshness_paths_are_emitted_once(self) -> None:
        receipt = scope_freshness(
            {
                "fresh": False,
                "changed_count": 2,
                "deleted_count": 0,
                "changed_paths": ["src/a.py", "src/b.py"],
                "deleted_paths": [],
            }
        )
        rendered = str(receipt)

        self.assertEqual(rendered.count("src/a.py"), 1)
        self.assertEqual(rendered.count("src/b.py"), 1)
        self.assertEqual(receipt["remaining_stale_count"], 2)
        self.assertEqual(receipt["unrelated_changed_count"], 2)

    def test_validation_uses_compact_graph_and_removes_legacy_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            legacy = out_dir / "live.graph.json"
            legacy.write_text("large generated snapshot", encoding="utf-8")

            graph_path = _prepare_validation_graph(out_dir)

            self.assertEqual(graph_path.name, "live.graph.gg")
            self.assertFalse(legacy.exists())

    def test_semantic_index_uses_compact_vectors_and_loads_v2(self) -> None:
        graph = Graph(
            nodes={
                "A": Node("A", "alpha_parser", "function", "src/a.py"),
                "B": Node("B", "beta_renderer", "function", "src/b.py"),
            }
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "semantic.json"
            built = SemanticIndex(path).build(graph)
            expected = [node_id for node_id, _score in built.query("alpha parser")]
            payload = loads(path.read_text(encoding="utf-8"))
            loaded = SemanticIndex.load(path)

            legacy_path = Path(tmp) / "legacy.json"
            legacy_path.write_text(
                '{"version":2,"dimensions":32,"signature":"old",'
                '"vectors":{"A":{"1":0.5,"2":-0.25}}}',
                encoding="utf-8",
            )
            legacy = SemanticIndex.load(legacy_path)

        self.assertEqual(payload["version"], 3)
        self.assertEqual(payload["vector_encoding"], "base85-u32-f32-le")
        self.assertIsInstance(payload["vectors"]["A"], str)
        self.assertEqual(
            [node_id for node_id, _score in loaded.query("alpha parser")],
            expected,
        )
        self.assertEqual(legacy.vectors["A"], {1: 0.5, 2: -0.25})

    def test_manifest_is_compact_and_round_trips(self) -> None:
        manifest = Manifest()
        manifest.update_file(
            "src/a.py",
            "hash",
            "symbols",
            "tree_sitter",
            False,
            ["A"],
            [("A", "B", "calls")],
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "graph.gg.manifest.json"
            manifest.save(path)
            text = path.read_text(encoding="utf-8")
            loaded = Manifest.load(path)

        self.assertNotIn("\n", text)
        loaded_info = loaded.get_file_info("src/a.py")
        expected_info = manifest.get_file_info("src/a.py")
        assert loaded_info is not None and expected_info is not None
        self.assertEqual(loaded_info["hash"], expected_info["hash"])
        self.assertEqual(loaded_info["nodes"], expected_info["nodes"])
        self.assertEqual(
            [tuple(edge) for edge in loaded_info["edges"]],
            expected_info["edges"],
        )

    def test_rust_variants_do_not_reference_unrelated_cross_crate_type(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            files = {
                "Cargo.toml": (
                    '[workspace]\nmembers = ["crates/core-pkg", "crates/engine"]\n'
                    'resolver = "2"\n'
                ),
                "crates/core-pkg/Cargo.toml": (
                    '[package]\nname = "core-pkg"\nversion = "0.1.0"\n'
                ),
                "crates/core-pkg/src/lib.rs": (
                    "pub enum SymbolAccessKind { Read, Write }\n"
                    "impl SymbolAccessKind {\n"
                    "    pub fn as_str(self) -> &'static str {\n"
                    "        match self { Self::Read => \"read\", Self::Write => \"write\" }\n"
                    "    }\n"
                    "}\n"
                ),
                "crates/engine/Cargo.toml": (
                    '[package]\nname = "engine"\nversion = "0.1.0"\n'
                    '[dependencies]\ncore-pkg = { path = "../core-pkg" }\n'
                ),
                "crates/engine/src/lib.rs": (
                    "use core_pkg::SymbolAccessKind;\n"
                    "pub struct Read;\n"
                    "pub enum Effect { Read(String), Write(String) }\n"
                    "pub fn conflict(effect: Effect) -> bool {\n"
                    "    matches!(effect, Effect::Read(_))\n"
                    "}\n"
                    "pub fn classify(value: SymbolAccessKind) -> bool {\n"
                    "    matches!(value, SymbolAccessKind::Read)\n"
                    "}\n"
                ),
            }
            for rel, text in files.items():
                path = root / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")

            graph = scan_directory(
                root,
                depth="symbols",
                frontend="tree_sitter",
                docs=False,
            )

        read_id = next(
            node.id
            for node in graph.nodes.values()
            if node.label == "Read" and node.kind == "struct"
        )
        symbol_access_id = next(
            node.id
            for node in graph.nodes.values()
            if node.label == "SymbolAccessKind"
        )
        false_sources = {
            node.id
            for node in graph.nodes.values()
            if node.label in {"as_str", "conflict"}
        }
        self.assertFalse(
            any(
                edge.type == "references"
                and edge.source in false_sources
                and edge.target == read_id
                for edge in graph.edges
            )
        )
        classify_id = next(
            node.id for node in graph.nodes.values() if node.label == "classify"
        )
        self.assertTrue(
            any(
                edge.type == "references"
                and edge.source == classify_id
                and edge.target == symbol_access_id
                for edge in graph.edges
            )
        )
        self.assertGreaterEqual(
            int(graph.metadata["rust_reference_rejected_qualified_suffix"]),
            2,
        )


if __name__ == "__main__":
    unittest.main()
