from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from graphgraph import (
    Graph,
    remove_paths,
    scan_directory,
    update_paths,
)
from graphgraph.ast_scanner import extract_symbols
from graphgraph.doc_scanner import DocumentInput, extract_document_context
from graphgraph.frontends import (
    ExtractionResult,
    RegexExtractor,
    SourceFile,
    TreeSitterExtractor,
    _imported_symbol_names,
    available_frontends,
    select_extractor,
    tree_sitter_available,
)
from graphgraph.io import (
    graph_to_json,
    save_graph,
)
from graphgraph.manifest import MANIFEST_VERSION
from graphgraph.ontology import relation_spec
from graphgraph.terms import canonical_concept_label, concept_id, term_key
from graphgraph.validate import validate_graph_json


class ScannerTest(unittest.TestCase):
    def test_terms_normalize_concepts_consistently(self) -> None:
        self.assertEqual(term_key("Token Store"), "token store")
        self.assertEqual(term_key("token-store"), "token store")
        self.assertEqual(term_key("TokenStore"), "token store")
        self.assertEqual(concept_id("Token Store"), "concept_token_store")
        self.assertEqual(canonical_concept_label("token store"), "Token Store")

    def test_frontend_capabilities(self) -> None:
        caps = available_frontends()
        names = {cap.name for cap in caps}
        self.assertIn("regex", names)
        self.assertIn("tree_sitter", names)
        self.assertTrue(next(cap for cap in caps if cap.name == "regex").available)

    def test_frontend_capabilities_report_per_language_readiness(self) -> None:
        with patch(
            "graphgraph.scanner.frontends._language_available",
            side_effect=lambda name: name == "python",
        ):
            tree_sitter = next(
                capability
                for capability in available_frontends()
                if capability.name == "tree_sitter"
            )

        self.assertEqual(tree_sitter.ready_languages, ("python",))
        self.assertIn("typescript", tree_sitter.unavailable_languages)
        self.assertTrue(tree_sitter.available)

    def test_language_readiness_requires_a_constructible_parser(self) -> None:
        with patch(
            "graphgraph.scanner.frontends._parser_for_language",
            return_value=None,
        ):
            self.assertFalse(tree_sitter_available())

    def test_transient_grammar_failure_is_retried_instead_of_cached(self) -> None:
        import graphgraph.scanner.frontends as frontends

        class RecoveringPack:
            calls = 0

            @classmethod
            def get_language(cls, _name):
                cls.calls += 1
                if cls.calls == 1:
                    raise PermissionError("temporary read-only cache")
                return object()

        language_name = "retry_language"
        try:
            with (
                patch.object(frontends, "find_spec", return_value=object()),
                patch.object(frontends, "import_module", return_value=RecoveringPack),
            ):
                first = frontends._language_for_name(language_name)
                second = frontends._language_for_name(language_name)

            self.assertIsNone(first)
            self.assertIsNotNone(second)
            self.assertEqual(RecoveringPack.calls, 2)
        finally:
            frontends._LANGUAGE_CACHE.pop(language_name, None)
            frontends._LANGUAGE_LOAD_ERRORS.pop(language_name, None)

    def test_regex_extractor_interface(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            f = root / "mod.py"
            f.write_text("def helper(): pass\n", encoding="utf-8")
            result = RegexExtractor().extract_symbols(
                [SourceFile(f, "mod.py", "mod_py", f.read_text(encoding="utf-8"))],
                max_total_symbols=10,
            )
            self.assertEqual(result.frontend, "regex")
            self.assertTrue(any(node.label == "helper" for node in result.nodes.values()))

    def test_scan_preserves_extraction_confidence_independent_of_centrality(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "main.py").write_text(
                "def _private(): pass\ndef public():\n    _private()\n",
                encoding="utf-8",
            )
            graph = scan_directory(root, depth="symbols", frontend="regex")
            call = next(edge for edge in graph.edges if edge.type == "calls")
            self.assertEqual(call.provenance, "regex_ast")
            self.assertEqual(call.confidence, 0.75)

    def test_select_extractor_regex_forced(self) -> None:
        self.assertIsInstance(select_extractor("regex"), RegexExtractor)

    def test_select_extractor_tree_sitter_requires_dependency(self) -> None:
        if not tree_sitter_available():
            with self.assertRaises(RuntimeError):
                select_extractor("tree_sitter")

    def test_auto_tree_sitter_falls_back_per_file_and_records_reason(self) -> None:
        class TimedOutParser:
            timeout_micros = 0

            def parse(self, _text):
                return None

            def reset(self):
                return None

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_path = root / "slow.rs"
            text = "pub struct Recovered;\n"
            source_path.write_text(text, encoding="utf-8")
            source = SourceFile(source_path, "slow.rs", "slow_rs", text)
            extractor = TreeSitterExtractor(fallback_on_error=True, parse_timeout_micros=1234)

            with patch("graphgraph.scanner.frontends._parser_for_suffix", return_value=TimedOutParser()):
                result = extractor.extract_symbols([source], max_total_symbols=20)

            self.assertEqual(result.frontend, "tree_sitter+regex")
            self.assertEqual(result.fallback_files, ("slow.rs",))
            self.assertEqual(result.failed_files, ("slow.rs:TimeoutError",))
            self.assertEqual(result.timeout_files, ("slow.rs",))
            self.assertEqual(result.unsupported_files, ())
            self.assertEqual(result.parse_error_files, ())
            self.assertTrue(any(node.label == "Recovered" for node in result.nodes.values()))

    def test_explicit_tree_sitter_surfaces_file_failure(self) -> None:
        class BrokenParser:
            timeout_micros = 0

            def parse(self, _text):
                raise ValueError("bad parser state")

            def reset(self):
                return None

        source = SourceFile(Path("broken.rs"), "broken.rs", "broken_rs", "pub struct Broken;\n")
        with patch("graphgraph.scanner.frontends._parser_for_suffix", return_value=BrokenParser()):
            with self.assertRaisesRegex(RuntimeError, "broken.rs"):
                TreeSitterExtractor().extract_symbols([source], max_total_symbols=20)

    def test_explicit_tree_sitter_fails_when_supported_grammar_is_unavailable(self) -> None:
        source = SourceFile(Path("sample.ts"), "sample.ts", "sample_ts", "export function run() {}\n")
        with (
            patch("graphgraph.scanner.frontends._parser_for_suffix", return_value=None),
            patch(
                "graphgraph.scanner.frontends.parser_unavailable_reason",
                return_value="OSError: grammar cache is read-only",
            ),
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                r"sample\.ts.*typescript.*grammar cache is read-only",
            ):
                TreeSitterExtractor().extract_symbols([source], max_total_symbols=20)

    def test_auto_tree_sitter_records_grammar_failure_before_regex_fallback(self) -> None:
        source = SourceFile(Path("sample.go"), "sample.go", "sample_go", "func Run() {}\n")
        with (
            patch("graphgraph.scanner.frontends._parser_for_suffix", return_value=None),
            patch(
                "graphgraph.scanner.frontends.parser_unavailable_reason",
                return_value="PermissionError: grammar cache is read-only",
            ),
        ):
            result = TreeSitterExtractor(fallback_on_error=True).extract_symbols(
                [source],
                max_total_symbols=20,
            )

        self.assertEqual(result.frontend, "tree_sitter+regex")
        self.assertEqual(result.unsupported_files, ("sample.go",))
        self.assertEqual(
            result.grammar_errors,
            ("sample.go:PermissionError: grammar cache is read-only",),
        )
        self.assertTrue(any(node.label == "Run" for node in result.nodes.values()))

    def test_tree_sitter_reports_unsupported_fallback_separately_from_parse_failures(self) -> None:
        source = SourceFile(Path("notes.md"), "notes.md", "notes_md", "# Notes\n")
        result = TreeSitterExtractor(fallback_on_error=True).extract_symbols(
            [source],
            max_total_symbols=20,
        )

        self.assertEqual(result.fallback_files, ("notes.md",))
        self.assertEqual(result.unsupported_files, ("notes.md",))
        self.assertEqual(result.timeout_files, ())
        self.assertEqual(result.parse_error_files, ())
        self.assertEqual(result.failed_files, ())

    def test_tree_sitter_extractor_captures_rust_trait_methods(self) -> None:
        if not tree_sitter_available():
            self.skipTest("tree_sitter is not installed")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            f = root / "lib.rs"
            text = (
                "pub trait ExprVisitor {\n"
                "    fn visit_expr(&mut self, expr: &Expr);\n"
                "    fn visit_condition(&mut self, c: &Condition) -> bool;\n"
                "}\n"
            )
            f.write_text(text, encoding="utf-8")
            result = select_extractor("tree_sitter").extract_symbols(
                [SourceFile(f, "lib.rs", "lib_rs", text)],
                max_total_symbols=20,
            )
            labels = {node.label for node in result.nodes.values()}
            self.assertIn("ExprVisitor", labels)
            self.assertIn("visit_expr", labels)
            self.assertIn("visit_condition", labels)
            trait_id = next(nid for nid, node in result.nodes.items() if node.label == "ExprVisitor")
            method_ids = {nid for nid, node in result.nodes.items() if node.label in {"visit_expr", "visit_condition"}}
            nested = {(edge.source, edge.target, edge.type) for edge in result.edges}
            self.assertTrue(all((trait_id, method_id, "contains") in nested for method_id in method_ids))

    def test_regex_extractor_links_locus_style_cross_crate_rust_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            trait_path = root / "locus-core" / "src" / "pipeline.rs"
            impl_path = root / "locus-pipeline" / "src" / "lib.rs"
            trait_path.parent.mkdir(parents=True)
            impl_path.parent.mkdir(parents=True)
            trait_text = "pub trait DiscoveryPipeline { fn search_candidates(&self); }\n"
            impl_text = (
                "pub struct LocusEngine;\n"
                "impl DiscoveryPipeline for LocusEngine { fn search_candidates(&self) {} }\n"
            )
            trait_path.write_text(trait_text, encoding="utf-8")
            impl_path.write_text(impl_text, encoding="utf-8")
            files = [
                SourceFile(trait_path, "locus-core/src/pipeline.rs", "trait_file", trait_text),
                SourceFile(impl_path, "locus-pipeline/src/lib.rs", "impl_file", impl_text),
            ]

            result = RegexExtractor().extract_symbols(files, max_total_symbols=100)
            nodes = result.nodes
            contracts = {
                (nodes[edge.source].label, nodes[edge.target].label)
                for edge in result.edges
                if edge.type == "implements" and edge.source in nodes and edge.target in nodes
            }
            self.assertIn(("LocusEngine", "DiscoveryPipeline"), contracts)

    def test_incremental_regex_scan_preserves_cross_file_rust_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            trait_path = root / "core.rs"
            impl_path = root / "engine.rs"
            trait_path.write_text("pub trait DiscoveryPipeline { fn run(&self); }\n", encoding="utf-8")
            impl_path.write_text(
                "pub struct LocusEngine;\nimpl DiscoveryPipeline for LocusEngine { fn run(&self) {} }\n",
                encoding="utf-8",
            )
            graph_path = root / "graph.gg"
            manifest_path = root / "manifest.json"
            graph = scan_directory(root, depth="symbols", frontend="regex", manifest_path=manifest_path)
            save_graph(graph, graph_path)

            impl_path.write_text(
                "pub struct LocusEngine;\nimpl DiscoveryPipeline for LocusEngine { fn run(&self) { } }\n",
                encoding="utf-8",
            )
            updated = update_paths(
                root,
                ["engine.rs"],
                depth="symbols",
                frontend="regex",
                previous_graph_path=graph_path,
                manifest_path=manifest_path,
            )
            labels = updated.nodes
            self.assertTrue(
                any(
                    edge.type == "implements"
                    and labels[edge.source].label == "LocusEngine"
                    and labels[edge.target].label == "DiscoveryPipeline"
                    for edge in updated.edges
                )
            )

    def test_tree_sitter_extractor_captures_rust_fields_and_returns(self) -> None:
        if not tree_sitter_available():
            self.skipTest("tree_sitter is not installed")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            f = root / "lib.rs"
            text = (
                "pub struct Point { pub x: f64, y: f64 }\n"
                "pub struct EgraphStageTimingsMs { pub extraction: f64 }\n"
                "pub fn make() -> Point { Point { x: 0.0, y: 0.0 } }\n"
                "pub fn optimize_timed() -> (Point, f32, EgraphStageTimingsMs) { todo!() }\n"
            )
            f.write_text(text, encoding="utf-8")
            result = select_extractor("tree_sitter").extract_symbols(
                [SourceFile(f, "lib.rs", "lib_rs", text)],
                max_total_symbols=20,
            )
            labels = {node.label for node in result.nodes.values()}
            self.assertIn("Point", labels)
            self.assertIn("x", labels)
            self.assertIn("y", labels)
            point_id = next(nid for nid, node in result.nodes.items() if node.label == "Point")
            make_id = next(nid for nid, node in result.nodes.items() if node.label == "make")
            timed_id = next(nid for nid, node in result.nodes.items() if node.label == "optimize_timed")
            timings_id = next(
                nid for nid, node in result.nodes.items() if node.label == "EgraphStageTimingsMs"
            )
            self.assertTrue(any(edge.type == "field_of" and edge.target == point_id for edge in result.edges))
            self.assertTrue(
                any(
                    edge.type == "returns" and edge.source == make_id and edge.target == point_id
                    for edge in result.edges
                )
            )
            self.assertTrue(
                any(
                    edge.type == "returns" and edge.source == timed_id and edge.target == timings_id
                    for edge in result.edges
                )
            )

    def test_collect_files_include_overrides_default_skip(self) -> None:
        from graphgraph.scanner.files import collect_files, find_pruned_dirs

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "game" / "build").mkdir(parents=True)
            (root / "game" / "build" / "README.md").write_text("# guide", encoding="utf-8")
            (root / "src").mkdir()
            (root / "src" / "a.py").write_text("x = 1\n", encoding="utf-8")

            # By default, a directory named 'build' is skipped.
            default = {p.relative_to(root).as_posix() for p in collect_files(root, 100).files}
            self.assertNotIn("game/build/README.md", default)
            # find_pruned_dirs reports it (not silent).
            self.assertIn("build", find_pruned_dirs(root, frozenset({"build"})))
            # --include build keeps it.
            included = {p.relative_to(root).as_posix() for p in collect_files(root, 100, include=frozenset({"build"})).files}
            self.assertIn("game/build/README.md", included)

    def test_collect_files_honors_gitignore_ignore_and_nested_negation(self) -> None:
        from graphgraph.scanner.files import collect_files

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".gitignore").write_text("ignored.py\n*.env\n!keep.env\n", encoding="utf-8")
            (root / ".ignore").write_text("dump-*.json\nignored-corpus/\n", encoding="utf-8")
            (root / "ignored.py").write_text("", encoding="utf-8")
            (root / "secret.env").write_text("SECRET=x", encoding="utf-8")
            (root / "keep.env").write_text("documented=x", encoding="utf-8")
            (root / "dump-analysis.json").write_text("{}", encoding="utf-8")
            nested = root / "nested"
            nested.mkdir()
            (nested / ".gitignore").write_text("*.tmp\n!keep.tmp\n", encoding="utf-8")
            (nested / "drop.tmp").write_text("", encoding="utf-8")
            (nested / "keep.tmp").write_text("", encoding="utf-8")
            ignored_corpus = root / "ignored-corpus"
            ignored_corpus.mkdir()
            (ignored_corpus / "large.py").write_text("x = 1\n", encoding="utf-8")
            (root / "kept.py").write_text("", encoding="utf-8")

            result = collect_files(root, 100)
            files = {path.relative_to(root).as_posix() for path in result.files}
            self.assertEqual(files, {"kept.py", "keep.env", "nested/keep.tmp"})
            self.assertEqual(result.ignore_files, (".gitignore", ".ignore", "nested/.gitignore"))
            self.assertEqual(result.ignored_by_rules, 4)
            self.assertEqual(result.rule_pruned_dirs, ("ignored-corpus",))

    def test_scan_directory_reports_phase_progress_and_ignore_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".ignore").write_text("corpus/\n", encoding="utf-8")
            (root / "app.py").write_text("def run():\n    return 1\n", encoding="utf-8")
            (root / "corpus").mkdir()
            (root / "corpus" / "noise.py").write_text("def noise(): pass\n", encoding="utf-8")
            events: list[tuple[str, str]] = []

            graph = scan_directory(
                root,
                depth="symbols",
                frontend="regex",
                progress=lambda phase, detail: events.append((phase, detail)),
            )

            phases = [phase for phase, _detail in events]
            self.assertEqual(phases[0], "discover")
            self.assertIn("symbols", phases)
            self.assertIn("concepts", phases)
            self.assertEqual(phases[-1], "complete")
            self.assertEqual(graph.metadata["ignore_rule_files"], ".ignore")
            self.assertEqual(graph.metadata["ignore_pruned_dir_count"], "1")
            self.assertFalse(any(node.path.startswith("corpus/") for node in graph.nodes.values()))

    def test_scan_directory_filters_ignored_git_paths_from_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".ignore").write_text("packet.json\n", encoding="utf-8")
            (root / "app.py").write_text("x = 1\n", encoding="utf-8")
            (root / "packet.json").write_text("{}\n", encoding="utf-8")
            with patch(
                "graphgraph.scanner.core._get_git_metadata",
                return_value=({"app.py", "packet.json"}, {"app.py": 2, "packet.json": 9}),
            ):
                graph = scan_directory(root)
        self.assertEqual(graph.metadata["git_dirty"], "app.py")
        self.assertNotIn("packet.json", json.dumps(graph.metadata))

    def test_collect_files_skips_sensitive_and_agent_configuration_by_default(self) -> None:
        from graphgraph.scanner.files import collect_files

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".env").write_text("SECRET=x", encoding="utf-8")
            (root / ".mcp.json").write_text("{}", encoding="utf-8")
            (root / "GEMINI.md").write_text("prompt", encoding="utf-8")
            (root / ".gemini").mkdir()
            (root / ".gemini" / "settings.json").write_text("{}", encoding="utf-8")
            (root / "app.py").write_text("", encoding="utf-8")

            files = {path.relative_to(root).as_posix() for path in collect_files(root, 100).files}
            self.assertEqual(files, {"app.py"})

    def test_collect_files_ignores_skip_listed_ancestor_directory_names(self) -> None:
        # Regression: the skip check used to compare against path.parts (the
        # *absolute* path), so a project checked out under e.g. ~/repos/foo
        # or /tmp/anything -- both "repos" and "tmp" are skip-listed dir
        # names -- silently yielded zero files with no warning, since every
        # file's absolute path contains the skip-listed ancestor component.
        from graphgraph.scanner.files import collect_files

        with tempfile.TemporaryDirectory() as tmp:
            # "repos" is in SKIP_DIRS; put it as an *ancestor* of root, not a
            # subdirectory being scanned.
            root = Path(tmp) / "repos" / "myproject"
            root.mkdir(parents=True)
            (root / "main.py").write_text("def foo(): pass\n", encoding="utf-8")
            files = {p.relative_to(root).as_posix() for p in collect_files(root, 100).files}
            self.assertIn("main.py", files)

    def test_tree_sitter_extractor_captures_csharp_class_and_methods(self) -> None:
        if not tree_sitter_available():
            self.skipTest("tree_sitter is not installed")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            f = root / "RecipeResolver.cs"
            text = (
                "namespace Game.Resolvers {\n"
                "  public class RecipeResolver : IRecipeCanon {\n"
                "    public RecipeResolver() {}\n"
                "    public Recipe Resolve(string id) { return null; }\n"
                "  }\n"
                "  public struct RecipeRecord { public int Id; }\n"
                "  public enum RecipeKind { Weapon, Armor }\n"
                "  public interface IRecipeCanon { }\n"
                "}\n"
            )
            f.write_text(text, encoding="utf-8")
            result = select_extractor("tree_sitter").extract_symbols(
                [SourceFile(f, "RecipeResolver.cs", "RecipeResolver_cs", text)],
                max_total_symbols=50,
            )
            by_label = {node.label: node for node in result.nodes.values()}
            self.assertIn("RecipeResolver", by_label)
            self.assertTrue(any(node.label == "RecipeResolver" and node.kind == "class" for node in result.nodes.values()))
            self.assertEqual(by_label["Resolve"].kind, "method")
            self.assertEqual(by_label["RecipeRecord"].kind, "struct")
            self.assertEqual(by_label["RecipeKind"].kind, "enum")
            self.assertEqual(by_label["IRecipeCanon"].kind, "interface")
            # Method should be nested under the class via a contains edge.
            class_id = next(nid for nid, n in result.nodes.items() if n.label == "RecipeResolver" and n.kind == "class")
            resolve_id = next(nid for nid, n in result.nodes.items() if n.label == "Resolve")
            nested = {(edge.source, edge.target, edge.type) for edge in result.edges}
            self.assertIn((class_id, resolve_id, "contains"), nested)

    def test_tree_sitter_resolves_cross_file_calls_csharp_and_java(self) -> None:
        if not tree_sitter_available():
            self.skipTest("tree_sitter is not installed")
        cases = {
            "csharp": {
                "RecipeResolver.cs": "namespace G { public class RecipeResolver {\n  public int Resolve(string id) { return Compute(id); }\n} }\n",
                "CombatResolver.cs": "namespace G { public class CombatResolver {\n  public int Compute(string id) { return 7; }\n} }\n",
                "expect": ("Resolve", "Compute"),
            },
            "java": {
                "A.java": "class A { int run(){ return help(); } }\n",
                "B.java": "class B { int help(){ return 1; } }\n",
                "expect": ("run", "help"),
            },
        }
        for _lang, spec in cases.items():
            expect = spec.pop("expect")
            with tempfile.TemporaryDirectory() as tmp:
                srcs = []
                for name, text in spec.items():
                    f = Path(tmp) / name
                    f.write_text(text, encoding="utf-8")
                    srcs.append(SourceFile(f, name, name.replace(".", "_"), text))
                result = select_extractor("tree_sitter").extract_symbols(srcs, max_total_symbols=100)
                calls = {
                    (result.nodes[e.source].label, result.nodes[e.target].label)
                    for e in result.edges
                    if e.type == "calls"
                }
                self.assertIn(expect, calls, f"missing cross-file call edge {expect}; got {calls}")

    def test_tree_sitter_does_not_link_calls_across_languages(self) -> None:
        if not tree_sitter_available():
            self.skipTest("tree_sitter is not installed")
        # Regression: found via a real-world scan where a Rust function's call
        # to a std-library-style helper resolved to an unrelated C function of
        # the same name in vendored test fixtures purely because it was the
        # only "count" definition in the whole repo -- producing a nonsensical
        # Rust-calls-C edge (`_add_tree_sitter_calls` in frontends.py).
        rs_text = "pub fn examine() -> i32 { count() }\n"
        c_text = "int count(void) { return 1; }\n"
        with tempfile.TemporaryDirectory() as tmp:
            rs = Path(tmp) / "shape.rs"
            rs.write_text(rs_text, encoding="utf-8")
            c = Path(tmp) / "vendor" / "common.h"
            c.parent.mkdir(parents=True, exist_ok=True)
            c.write_text(c_text, encoding="utf-8")
            srcs = [
                SourceFile(rs, "shape.rs", "shape_rs", rs_text),
                SourceFile(c, "vendor/common.h", "vendor_common_h", c_text),
            ]
            result = select_extractor("tree_sitter").extract_symbols(srcs, max_total_symbols=100)
            calls = {
                (result.nodes[e.source].label, result.nodes[e.target].label) for e in result.edges if e.type == "calls"
            }
            self.assertNotIn(("examine", "count"), calls, f"found Rust->C cross-language call edge: {calls}")

    def test_tree_sitter_resolves_calls_through_python_package_reexports(self) -> None:
        if not tree_sitter_available():
            self.skipTest("tree_sitter is not installed")
        sources = {
            "src/pkg/renderers.py": "def render_packet():\n    return 'ok'\n",
            "src/pkg/__init__.py": "from .renderers import render_packet\n",
            "src/consumer.py": "from pkg import render_packet\n\ndef run():\n    return render_packet()\n",
            "bench/fixture.py": "def render_packet():\n    return 'fixture'\n",
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            files = []
            for rel, source_text in sources.items():
                path = root / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(source_text, encoding="utf-8")
                files.append(SourceFile(path, rel, rel.replace("/", "_").replace(".", "_"), source_text))

            result = select_extractor("tree_sitter").extract_symbols(files, max_total_symbols=100)
            calls = [
                edge
                for edge in result.edges
                if edge.type == "calls"
                and result.nodes[edge.source].label == "run"
                and result.nodes[edge.target].label == "render_packet"
            ]
            self.assertEqual(len(calls), 1)
            self.assertEqual(result.nodes[calls[0].target].path, "src/pkg/renderers.py")

    def test_tree_sitter_resolves_python_self_method_calls_by_class_owner(self) -> None:
        if not tree_sitter_available():
            self.skipTest("tree_sitter is not installed")
        source_text = (
            "class Worker:\n"
            "    def run(self):\n"
            "        return self.process()\n\n"
            "    def process(self):\n"
            "        return 1\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "worker.py"
            path.write_text(source_text, encoding="utf-8")
            result = select_extractor("tree_sitter").extract_symbols(
                [SourceFile(path, "worker.py", "worker_py", source_text)],
                max_total_symbols=100,
            )

        methods = {node.label: node for node in result.nodes.values() if node.kind == "method"}
        self.assertEqual(set(methods), {"run", "process"})
        self.assertEqual(result.nodes[methods["run"].parent].label, "Worker")
        calls = [
            edge for edge in result.edges
            if edge.type == "calls"
            and edge.source == methods["run"].id
            and edge.target == methods["process"].id
        ]
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].provenance, "tree_sitter_type_resolved")
        self.assertEqual(result.resolved_member_calls, 1)

    def test_tree_sitter_does_not_link_qualified_method_calls_to_free_functions(self) -> None:
        if not tree_sitter_available():
            self.skipTest("tree_sitter is not installed")
        # Regression: found via a real-world scan where `order.splice(...)`
        # (a receiver.method(...) call -- here Vec::splice, a stdlib method)
        # resolved to an unrelated private free function `fn splice(...)`
        # elsewhere in the same crate, purely because "splice" was the only
        # definition with that name in the repo. Resolving a qualified call
        # needs the receiver's type, which this heuristic extractor doesn't
        # have -- same bug class as the cross-language case above, but
        # same-language/same-crate, so the language-family guard alone
        # doesn't catch it (`_add_tree_sitter_calls` in frontends.py).
        rs_text_a = (
            "fn validate_schedule(order: &mut Vec<i32>) {\n"
            "    let pos = 0;\n"
            "    order.splice(pos..=pos, [1, 2, 3]);\n"
            "}\n"
        )
        rs_text_b = "fn splice(x: i32) -> i32 {\n    x + 1\n}\n"
        with tempfile.TemporaryDirectory() as tmp:
            a = Path(tmp) / "schedule_legality.rs"
            a.write_text(rs_text_a, encoding="utf-8")
            b = Path(tmp) / "evolution.rs"
            b.write_text(rs_text_b, encoding="utf-8")
            srcs = [
                SourceFile(a, "schedule_legality.rs", "schedule_legality_rs", rs_text_a),
                SourceFile(b, "evolution.rs", "evolution_rs", rs_text_b),
            ]
            result = select_extractor("tree_sitter").extract_symbols(srcs, max_total_symbols=100)
            calls = {
                (result.nodes[e.source].label, result.nodes[e.target].label) for e in result.edges if e.type == "calls"
            }
            self.assertNotIn(
                ("validate_schedule", "splice"),
                calls,
                f"found qualified-call-to-unrelated-free-function edge: {calls}",
            )

        # But a bare (unqualified) call to a globally-unique free function
        # must still resolve -- the fix must not break the common case.
        rs_text_c = "fn caller() -> i32 {\n    helper()\n}\n"
        rs_text_d = "fn helper() -> i32 {\n    1\n}\n"
        with tempfile.TemporaryDirectory() as tmp:
            c = Path(tmp) / "c.rs"
            c.write_text(rs_text_c, encoding="utf-8")
            d = Path(tmp) / "d.rs"
            d.write_text(rs_text_d, encoding="utf-8")
            srcs = [
                SourceFile(c, "c.rs", "c_rs", rs_text_c),
                SourceFile(d, "d.rs", "d_rs", rs_text_d),
            ]
            result = select_extractor("tree_sitter").extract_symbols(srcs, max_total_symbols=100)
            calls = {
                (result.nodes[e.source].label, result.nodes[e.target].label) for e in result.edges if e.type == "calls"
            }
            self.assertIn(("caller", "helper"), calls, f"bare unqualified call should still resolve: {calls}")

    def test_tree_sitter_resolves_rust_receiver_method_from_parameter_type(self) -> None:
        if not tree_sitter_available():
            self.skipTest("tree_sitter is not installed")
        sources = {
            "src/lib.rs": (
                "pub struct LocusEngine;\n"
                "impl LocusEngine {\n"
                "    pub fn validate_candidates_detailed(&self, candidates: Vec<i32>) -> Vec<i32> { candidates }\n"
                "}\n"
            ),
            "src/yield_benchmark.rs": (
                "use crate::LocusEngine;\n"
                "pub fn run_formula_yield_benchmark(engine: &LocusEngine, candidates: Vec<i32>) {\n"
                "    let _outcomes = engine.validate_candidates_detailed(candidates);\n"
                "}\n"
            ),
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            files = []
            for rel, text in sources.items():
                path = root / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")
                files.append(SourceFile(path, rel, rel.replace("/", "_").replace(".", "_"), text))
            result = select_extractor("tree_sitter").extract_symbols(files, max_total_symbols=100)

        matching = [
            edge
            for edge in result.edges
            if edge.type == "calls"
            and result.nodes[edge.source].label == "run_formula_yield_benchmark"
            and result.nodes[edge.target].label == "validate_candidates_detailed"
        ]
        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0].provenance, "tree_sitter_type_resolved")
        self.assertEqual(result.resolved_member_calls, 1)
        method = result.nodes[matching[0].target]
        self.assertTrue(method.parent)
        self.assertEqual(result.nodes[method.parent].label, "LocusEngine")

    def test_tree_sitter_keeps_same_named_rust_methods_in_one_file_distinct(self) -> None:
        if not tree_sitter_available():
            self.skipTest("tree_sitter is not installed")
        text = (
            "pub struct YieldBaseline;\n"
            "impl YieldBaseline {\n"
            "    pub fn evaluate(&self, report: &u32) -> bool { *report > 0 }\n"
            "}\n"
            "pub struct SourceYieldBaseline;\n"
            "impl SourceYieldBaseline {\n"
            "    pub fn evaluate(&self, report: &u64) -> bool { *report > 0 }\n"
            "}\n"
            "pub fn check(a: &YieldBaseline, b: &SourceYieldBaseline) {\n"
            "    let _ = a.evaluate(&1);\n"
            "    let _ = b.evaluate(&1);\n"
            "}\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "yield_benchmark.rs"
            path.write_text(text, encoding="utf-8")
            result = select_extractor("tree_sitter").extract_symbols(
                [SourceFile(path, "src/yield_benchmark.rs", "src_yield_benchmark_rs", text)],
                max_total_symbols=100,
            )

        methods = [node for node in result.nodes.values() if node.kind == "method" and node.label == "evaluate"]
        self.assertEqual(len(methods), 2)
        self.assertEqual(len({node.id for node in methods}), 2)
        self.assertEqual({node.line for node in methods}, {3, 7})
        self.assertEqual(
            {result.nodes[node.parent].label for node in methods},
            {"YieldBaseline", "SourceYieldBaseline"},
        )
        self.assertTrue(any("SourceYieldBaseline::evaluate" in node.summary for node in methods))
        call_targets = {
            edge.target
            for edge in result.edges
            if edge.type == "calls" and result.nodes[edge.source].label == "check"
        }
        self.assertEqual(call_targets, {node.id for node in methods})

    def test_incremental_scan_preserves_same_named_rust_methods(self) -> None:
        if not tree_sitter_available():
            self.skipTest("tree_sitter is not installed")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "src" / "yield_benchmark.rs"
            source.parent.mkdir(parents=True)
            source.write_text(
                "pub struct YieldBaseline;\n"
                "impl YieldBaseline { pub fn evaluate(&self, report: &u32) -> bool { *report > 0 } }\n",
                encoding="utf-8",
            )
            graph_path = root / ".graphgraph" / "graph.json"
            manifest_path = root / ".graphgraph" / "manifest.json"
            graph = scan_directory(
                root,
                depth="symbols",
                frontend="tree_sitter",
                previous_graph_path=None,
                manifest_path=manifest_path,
            )
            save_graph(graph, graph_path)

            source.write_text(
                "pub struct YieldBaseline;\n"
                "impl YieldBaseline { pub fn evaluate(&self, report: &u32) -> bool { *report > 0 } }\n"
                "pub struct SourceYieldBaseline;\n"
                "impl SourceYieldBaseline { pub fn evaluate(&self, report: &u64) -> bool { *report > 0 } }\n",
                encoding="utf-8",
            )
            updated = update_paths(
                root,
                ["src/yield_benchmark.rs"],
                depth="symbols",
                frontend="tree_sitter",
                previous_graph_path=graph_path,
                manifest_path=manifest_path,
            )

        methods = [node for node in updated.nodes.values() if node.kind == "method" and node.label == "evaluate"]
        self.assertEqual(len(methods), 2)
        self.assertEqual(
            {updated.nodes[node.parent].label for node in methods},
            {"YieldBaseline", "SourceYieldBaseline"},
        )

    def test_tree_sitter_resolves_qualified_rust_unit_struct_receivers(self) -> None:
        if not tree_sitter_available():
            self.skipTest("tree_sitter is not installed")
        sources = {
            "src/identity.rs": (
                "pub struct IdentityDiscoveryAdvisor;\n"
                "impl IdentityDiscoveryAdvisor { pub fn examine(&self, objects: &[i32]) {} }\n"
            ),
            "src/simpler.rs": (
                "pub struct SimplerFormAdvisor;\n"
                "impl SimplerFormAdvisor { pub fn examine(&self, objects: &[i32]) {} }\n"
            ),
            "src/runner.rs": (
                "pub fn run(objects: &[i32]) {\n"
                "    crate::advisors::IdentityDiscoveryAdvisor.examine(objects);\n"
                "    crate::advisors::SimplerFormAdvisor.examine(objects);\n"
                "}\n"
            ),
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            files = []
            for rel, text in sources.items():
                path = root / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")
                files.append(SourceFile(path, rel, rel.replace("/", "_").replace(".", "_"), text))
            result = select_extractor("tree_sitter").extract_symbols(files, max_total_symbols=100)

        calls = [
            edge
            for edge in result.edges
            if edge.type == "calls" and result.nodes[edge.source].label == "run"
        ]
        owners = {
            result.nodes[result.nodes[edge.target].parent].label
            for edge in calls
            if result.nodes[edge.target].parent
        }
        self.assertEqual(owners, {"IdentityDiscoveryAdvisor", "SimplerFormAdvisor"})
        self.assertTrue(all(edge.provenance == "tree_sitter_type_resolved" for edge in calls))
        self.assertEqual(result.resolved_member_calls, 2)

    def test_tree_sitter_keeps_untyped_rust_member_calls_out_of_topology(self) -> None:
        if not tree_sitter_available():
            self.skipTest("tree_sitter is not installed")
        sources = {
            "src/a.rs": "pub struct A; impl A { pub fn validate(&self) {} }\n",
            "src/b.rs": "pub struct B; impl B { pub fn validate(&self) {} }\n",
            "src/run.rs": "pub fn run(engine: impl Sized) { engine.validate(); }\n",
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            files = []
            for rel, text in sources.items():
                path = root / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")
                files.append(SourceFile(path, rel, rel.replace("/", "_").replace(".", "_"), text))
            result = select_extractor("tree_sitter").extract_symbols(files, max_total_symbols=100)

        candidates = [
            edge
            for edge in result.edges
            if edge.source in result.nodes
            and result.nodes[edge.source].label == "run"
            and edge.type == "calls_candidate"
        ]
        self.assertEqual(candidates, [])
        self.assertEqual(result.ambiguous_member_calls, 0)
        self.assertEqual(result.unknown_receiver_member_calls, 1)
        run_id = next(node.id for node in result.nodes.values() if node.label == "run")
        self.assertFalse(any(edge.type == "calls" and edge.source == run_id for edge in result.edges))

    def test_tree_sitter_resolves_python_member_calls_from_explicit_type_evidence(self) -> None:
        if not tree_sitter_available():
            self.skipTest("tree_sitter is not installed")
        text = (
            "class Graph:\n"
            "    def outgoing(self):\n"
            "        return []\n"
            "\n"
            "class Runtime:\n"
            "    def __init__(self):\n"
            "        self.graph = Graph()\n"
            "\n"
            "    def compile(self):\n"
            "        return self.graph.outgoing()\n"
            "\n"
            "def from_annotation(graph: \"Graph | None\"):\n"
            "    return graph.outgoing()\n"
            "\n"
            "def from_constructor():\n"
            "    graph = Graph()\n"
            "    return graph.outgoing()\n"
            "\n"
            "def from_class_receiver():\n"
            "    return Graph.outgoing(Graph())\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "runtime.py"
            path.write_text(text, encoding="utf-8")
            result = select_extractor("tree_sitter").extract_symbols(
                [SourceFile(path, "runtime.py", "runtime_py", text)],
                max_total_symbols=100,
            )

        outgoing = next(node for node in result.nodes.values() if node.label == "outgoing")
        callers = {
            result.nodes[edge.source].label
            for edge in result.edges
            if edge.type == "calls" and edge.target == outgoing.id
        }
        self.assertEqual(callers, {"compile", "from_annotation", "from_constructor", "from_class_receiver"})
        self.assertEqual(result.resolved_member_calls, 4)
        self.assertTrue(
            all(
                edge.provenance == "tree_sitter_type_resolved"
                for edge in result.edges
                if edge.type == "calls" and edge.target == outgoing.id
            )
        )

    def test_tree_sitter_classifies_builtin_and_unknown_python_receivers_without_candidate_edges(self) -> None:
        if not tree_sitter_available():
            self.skipTest("tree_sitter is not installed")
        text = (
            "class Bucket:\n"
            "    def append(self, value):\n"
            "        pass\n"
            "\n"
            "def builtin_receiver():\n"
            "    values = []\n"
            "    values.append(1)\n"
            "\n"
            "def unknown_receiver(values):\n"
            "    values.append(1)\n"
            "\n"
            "def make_bucket():\n"
            "    return Bucket()\n"
            "\n"
            "def factory_receiver():\n"
            "    bucket = make_bucket()\n"
            "    bucket.append(1)\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bucket.py"
            path.write_text(text, encoding="utf-8")
            result = select_extractor("tree_sitter").extract_symbols(
                [SourceFile(path, "bucket.py", "bucket_py", text)],
                max_total_symbols=100,
            )

        self.assertFalse(any(edge.type == "calls_candidate" for edge in result.edges))
        self.assertFalse(
            any(
                edge.type == "calls"
                and result.nodes.get(edge.target)
                and result.nodes[edge.target].label == "append"
                for edge in result.edges
            )
        )
        self.assertEqual(result.unknown_receiver_member_calls, 2)
        self.assertEqual(result.unresolved_member_calls, 1)

    def test_tree_sitter_resolves_rust_self_field_receiver_type(self) -> None:
        if not tree_sitter_available():
            self.skipTest("tree_sitter is not installed")
        text = (
            "pub struct Store;\n"
            "impl Store { pub fn commit(&self) {} }\n"
            "pub struct Engine { store: Store }\n"
            "impl Engine { pub fn run(&self) { self.store.commit(); } }\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "engine.rs"
            path.write_text(text, encoding="utf-8")
            result = select_extractor("tree_sitter").extract_symbols(
                [SourceFile(path, "engine.rs", "engine_rs", text)],
                max_total_symbols=100,
            )

        call = next(
            edge
            for edge in result.edges
            if edge.type == "calls"
            and result.nodes[edge.source].label == "run"
            and result.nodes[edge.target].label == "commit"
        )
        self.assertEqual(call.provenance, "tree_sitter_type_resolved")
        self.assertIn("self.store:Store", call.evidence)
        self.assertEqual(result.resolved_member_calls, 1)

    def test_tree_sitter_links_typed_rust_test_field_assertion_as_direct_evidence(self) -> None:
        if not tree_sitter_available():
            self.skipTest("tree_sitter is not installed")
        text = (
            "pub struct YieldStageTimingsMs {\n"
            "    pub candidate_generation: f64,\n"
            "    pub extraction_only: Option<f64>,\n"
            "}\n"
            "pub struct YieldBenchmarkReport { pub timings_ms: YieldStageTimingsMs }\n"
            "pub fn run_formula_yield_benchmark() -> YieldBenchmarkReport { todo!() }\n"
            "#[test]\n"
            "fn validates_report() {\n"
            "    let report = run_formula_yield_benchmark();\n"
            "    assert!(report.timings_ms.candidate_generation > 0.0);\n"
            "    assert!(report.timings_ms.extraction_only.is_some());\n"
            "}\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tests" / "schema.rs"
            path.parent.mkdir()
            path.write_text(text, encoding="utf-8")
            result = select_extractor("tree_sitter").extract_symbols(
                [SourceFile(path, "tests/schema.rs", "tests_schema_rs", text)],
                max_total_symbols=100,
            )

        references = [
            edge
            for edge in result.edges
            if edge.type == "references"
            and result.nodes[edge.source].label == "validates_report"
        ]
        test_node = next(node for node in result.nodes.values() if node.label == "validates_report")
        self.assertEqual(test_node.facts, ("role:test", "rust_attribute:test"))
        self.assertEqual(
            {result.nodes[edge.target].label for edge in references},
            {"timings_ms", "candidate_generation", "extraction_only"},
        )
        self.assertTrue(
            all(edge.provenance == "tree_sitter_type_resolved_field_assertion" for edge in references)
        )
        self.assertTrue(all(edge.confidence == 0.94 for edge in references))

    def test_tree_sitter_projects_rust_operators_into_semantic_ir_facts(self) -> None:
        if not tree_sitter_available():
            self.skipTest("tree_sitter is not installed")
        text = (
            "use std::collections::BTreeSet;\n"
            "pub fn plan_writes(paths: &[String]) -> Vec<String> {\n"
            "    let mut seen = BTreeSet::new();\n"
            "    paths.iter().filter(|path| seen.insert((*path).clone())).cloned().collect()\n"
            "}\n"
            "pub fn pinned_count(actual: usize, expected: usize) -> bool {\n"
            "    actual != expected\n"
            "}\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "planner.rs"
            path.write_text(text, encoding="utf-8")
            result = select_extractor("tree_sitter").extract_symbols(
                [SourceFile(path, "src/planner.rs", "src_planner_rs", text)],
                max_total_symbols=100,
            )

        plan = next(node for node in result.nodes.values() if node.label == "plan_writes")
        pinned = next(node for node in result.nodes.values() if node.label == "pinned_count")
        self.assertIn("collection_contract:unique", plan.facts)
        self.assertIn("semantic_operation:deduplication", plan.facts)
        self.assertIn("semantic_operator:equality", pinned.facts)

    def test_incremental_scan_preserves_global_member_quality_and_reports_update_delta(self) -> None:
        if not tree_sitter_available():
            self.skipTest("tree_sitter is not installed")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "engine.rs"
            source.write_text(
                "pub struct Store;\n"
                "impl Store { pub fn commit(&self) {} }\n"
                "pub struct Engine { store: Store }\n"
                "impl Engine { pub fn run(&self) { self.store.commit(); } }\n",
                encoding="utf-8",
            )
            graph_path = root / "graph.gg"
            manifest_path = root / "manifest.json"
            graph = scan_directory(
                root,
                depth="symbols",
                frontend="tree_sitter",
                manifest_path=manifest_path,
            )
            save_graph(graph, graph_path)
            self.assertEqual(graph.metadata["member_calls_global_resolved"], "1")

            source.write_text(
                "pub struct Store;\n"
                "impl Store { pub fn commit(&self) {} }\n"
                "pub struct Engine { store: Store }\n"
                "impl Engine { pub fn run(&self) {} }\n",
                encoding="utf-8",
            )
            updated = update_paths(
                root,
                ["engine.rs"],
                depth="symbols",
                frontend="tree_sitter",
                previous_graph_path=graph_path,
                manifest_path=manifest_path,
            )

        self.assertEqual(updated.metadata["member_calls_global_resolved"], "1")
        self.assertEqual(updated.metadata["member_calls_last_update_resolved"], "0")
        self.assertEqual(updated.metadata["member_calls_global_scope"], "full_scan_snapshot")
        self.assertEqual(updated.metadata["member_calls_last_update_scope"], "changed_files")

    def test_tree_sitter_links_function_passed_as_callback_argument(self) -> None:
        if not tree_sitter_available():
            self.skipTest("tree_sitter is not installed")
        # Regression: found via real usage on a large C codebase. A function
        # invoked exclusively via function-pointer/callback registration
        # (SetMainCallback2(CB2_InitBattle), never called directly as
        # CB2_InitBattle(...)) had zero caller edges -- static call-graph
        # detection only recognizes name(...) call sites, so a name that's
        # merely *passed* as a bare argument was invisible, making an
        # actively-used function read as isolated/dead. Verified via a
        # direct tree-sitter parse (not assumed) that C's call_expression
        # exposes its argument list via child_by_field_name("arguments").
        c_text = (
            "void CB2_InitBattle(void) {}\n"
            "void MainLoop(void) {\n"
            "    SetMainCallback2(CB2_InitBattle);\n"
            "}\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "battle_main.c"
            f.write_text(c_text, encoding="utf-8")
            src = SourceFile(f, "battle_main.c", "battle_main_c", c_text)
            result = select_extractor("tree_sitter").extract_symbols([src], max_total_symbols=100)
            refs = {
                (result.nodes[e.source].label, result.nodes[e.target].label)
                for e in result.edges
                if e.type == "references"
            }
            self.assertIn(
                ("MainLoop", "CB2_InitBattle"),
                refs,
                f"callback-registration argument should produce a references edge: {refs}",
            )
            # Must not be misclassified as an actual "calls" edge -- passing
            # a name as an argument doesn't prove it's ever invoked.
            calls = {
                (result.nodes[e.source].label, result.nodes[e.target].label) for e in result.edges if e.type == "calls"
            }
            self.assertNotIn(("MainLoop", "CB2_InitBattle"), calls)

    def test_tree_sitter_links_python_keyword_argument_callback(self) -> None:
        if not tree_sitter_available():
            self.skipTest("tree_sitter is not installed")
        # Same bug class as the C callback-registration case above, but for
        # Python's extremely common `func=callback` idiom (argparse's
        # `set_defaults(func=cmd_scan)`, Click, dataclasses, ...). Verified
        # directly that tree-sitter wraps this in a keyword_argument node
        # (name="func", value="cmd_scan"), not a bare identifier -- a naive
        # `arg.type in _NAME_NODE_TYPES` check misses it entirely unless the
        # keyword_argument's `value` field is explicitly unwrapped.
        py_text = (
            "def cmd_scan(args):\n"
            "    pass\n"
            "\n"
            "def build_parser():\n"
            "    scan = sub.add_parser('scan')\n"
            "    scan.set_defaults(func=cmd_scan)\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "parser.py"
            f.write_text(py_text, encoding="utf-8")
            src = SourceFile(f, "parser.py", "parser_py", py_text)
            result = select_extractor("tree_sitter").extract_symbols([src], max_total_symbols=100)
            refs = {
                (result.nodes[e.source].label, result.nodes[e.target].label)
                for e in result.edges
                if e.type == "references"
            }
            self.assertIn(
                ("build_parser", "cmd_scan"),
                refs,
                f"func=callback keyword argument should produce a references edge: {refs}",
            )

    def test_tree_sitter_resolves_path_qualified_associated_function_calls(self) -> None:
        if not tree_sitter_available():
            self.skipTest("tree_sitter is not installed")
        # Regression: found via real-world usage -- a struct's own
        # associated function, called as `QuadPoly::from_uni(...)`, never
        # showed a `calls` edge pointing at it, making an actively-used
        # struct falsely read as isolated/dead by negative_query/
        # reverse_lookup. Unlike `receiver.method(...)` (needs the
        # receiver's type), `Type::function(...)` names its target
        # explicitly and lexically -- it should resolve like a bare call,
        # not be treated as unresolvable-qualified.
        rs_text = (
            "struct QuadPoly { a: i32 }\n"
            "impl QuadPoly {\n"
            "    fn from_uni(x: i32) -> QuadPoly { QuadPoly { a: x } }\n"
            "}\n"
            "fn integrate_rational_rothstein_trager() {\n"
            "    let q = QuadPoly::from_uni(5);\n"
            "}\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "integrate.rs"
            f.write_text(rs_text, encoding="utf-8")
            result = select_extractor("tree_sitter").extract_symbols(
                [SourceFile(f, "integrate.rs", "integrate_rs", rs_text)],
                max_total_symbols=100,
            )
            calls = {
                (result.nodes[e.source].label, result.nodes[e.target].label) for e in result.edges if e.type == "calls"
            }
            self.assertIn(
                ("integrate_rational_rothstein_trager", "from_uni"),
                calls,
                f"Type::function(...) associated call should resolve: {calls}",
            )

    def test_tree_sitter_recovers_rust_calls_nested_in_macro_token_trees(self) -> None:
        if not tree_sitter_available():
            self.skipTest("tree_sitter is not installed")
        rust = (
            "fn finite_vc_dimension() -> Result<(), ()> { Ok(()) }\n"
            "fn shatters() -> Result<bool, ()> { Ok(true) }\n"
            "#[cfg(test)] mod tests {\n"
            "    use super::*;\n"
            "    #[test]\n"
            "    fn malformed_contract() {\n"
            "        assert!(matches!(finite_vc_dimension(), Ok(())));\n"
            "    }\n"
            "    #[test]\n"
            "    fn subset_contract() {\n"
            "        assert!(shatters().unwrap());\n"
            "    }\n"
            "}\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "learning_theory.rs"
            path.write_text(rust, encoding="utf-8")
            result = select_extractor("tree_sitter").extract_symbols(
                [SourceFile(path, "src/learning_theory.rs", "learning_theory_rs", rust)],
                max_total_symbols=100,
            )

        calls = {
            (
                result.nodes[edge.source].label,
                result.nodes[edge.target].label,
                edge.provenance,
            )
            for edge in result.edges
            if edge.type == "calls"
        }
        self.assertIn(
            (
                "malformed_contract",
                "finite_vc_dimension",
                "tree_sitter_macro_token_tree",
            ),
            calls,
        )
        self.assertIn(
            ("subset_contract", "shatters", "tree_sitter_macro_token_tree"),
            calls,
        )
        self.assertFalse(any(target == "unwrap" for _source, target, _provenance in calls))

    def test_tree_sitter_extractor_captures_additional_languages(self) -> None:
        if not tree_sitter_available():
            self.skipTest("tree_sitter is not installed")
        cases = {
            "svc.rb": ("class RecipeResolver\n  def resolve(id)\n    1\n  end\nend\n", "RecipeResolver", "resolve"),
            "svc.php": (
                "<?php\nclass RecipeResolver { public function resolve($id){return 1;} }\n",
                "RecipeResolver",
                "resolve",
            ),
            "Svc.kt": (
                "class RecipeResolver { fun resolve(id: String): Int { return 1 } }\n",
                "RecipeResolver",
                "resolve",
            ),
            "Svc.scala": ("class RecipeResolver { def resolve(id: String): Int = 1 }\n", "RecipeResolver", "resolve"),
            "Svc.swift": (
                "class RecipeResolver { func resolve(_ id: String) -> Int { return 1 } }\n",
                "RecipeResolver",
                "resolve",
            ),
        }
        for fname, (text, type_name, member) in cases.items():
            with tempfile.TemporaryDirectory() as tmp:
                f = Path(tmp) / fname
                f.write_text(text, encoding="utf-8")
                result = select_extractor("tree_sitter").extract_symbols(
                    [SourceFile(f, fname, fname.replace(".", "_"), text)],
                    max_total_symbols=50,
                )
                labels = {node.label for node in result.nodes.values()}
                self.assertIn(type_name, labels, f"{fname}: missing type node")
                self.assertIn(member, labels, f"{fname}: missing member node")

    def test_imported_symbol_name_extraction(self) -> None:
        rust = "use crate::rules::{compile_rules_slice, RuleRecord};\nuse crate::foo::Bar as Baz;\n"
        py = "from server.auth import AuthService, TokenStore as Store\n"
        ts = "import { createApp, Router as R } from './app';\n"
        self.assertEqual(_imported_symbol_names(".rs", rust), {"compile_rules_slice", "RuleRecord", "Bar"})
        self.assertEqual(_imported_symbol_names(".py", py), {"AuthService", "TokenStore"})
        self.assertEqual(_imported_symbol_names(".ts", ts), {"createApp", "Router"})

    def test_full_scan_manifest_keeps_doc_concept_edge_targets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text(
                "# GraphGraph Workspace Rules\n\nUse `graphgraph/query_context` for Project Status.\n",
                encoding="utf-8",
            )
            graph_path = root / ".graphgraph" / "graph.json"
            manifest_path = root / ".graphgraph" / "manifest.json"

            graph = scan_directory(
                root,
                depth="symbols",
                docs=True,
                previous_graph_path=None,
                manifest_path=manifest_path,
            )
            save_graph(graph, graph_path)

            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            readme_nodes = manifest["files"]["README.md"]["nodes"]
            self.assertTrue(any(node_id.startswith("concept_") for node_id in readme_nodes))

            graph2 = scan_directory(
                root,
                depth="symbols",
                docs=True,
                previous_graph_path=graph_path,
                manifest_path=manifest_path,
            )
            result = validate_graph_json(graph_to_json(graph2))
            self.assertTrue(result.ok, result.errors)

    def test_update_paths_matches_full_rescan_including_cross_file_calls(self) -> None:
        def build_baseline(root: Path, graph_path: Path, manifest_path: Path) -> Graph:
            (root / "a.py").write_text("def foo():\n    return bar()\n\ndef bar():\n    return 1\n", encoding="utf-8")
            (root / "b.py").write_text("def baz():\n    return 2\n", encoding="utf-8")
            graph = scan_directory(root, depth="symbols", previous_graph_path=None, manifest_path=manifest_path)
            save_graph(graph, graph_path)
            return graph

        with tempfile.TemporaryDirectory() as tmp_full:
            root = Path(tmp_full)
            graph_path = root / ".graphgraph" / "graph.json"
            manifest_path = root / ".graphgraph" / "manifest.json"
            build_baseline(root, graph_path, manifest_path)

            # a.py now calls into b.py instead of its own bar().
            (root / "a.py").write_text("def foo():\n    return baz()\n\ndef bar():\n    return 1\n", encoding="utf-8")
            full = scan_directory(root, depth="symbols", previous_graph_path=graph_path, manifest_path=manifest_path)
            full_nodes = sorted((n.label, n.path) for n in full.nodes.values())
            full_edges = sorted((e.source, e.target, e.type) for e in full.edges)

        with tempfile.TemporaryDirectory() as tmp_targeted:
            root = Path(tmp_targeted)
            graph_path = root / ".graphgraph" / "graph.json"
            manifest_path = root / ".graphgraph" / "manifest.json"
            build_baseline(root, graph_path, manifest_path)

            (root / "a.py").write_text("def foo():\n    return baz()\n\ndef bar():\n    return 1\n", encoding="utf-8")
            targeted = update_paths(
                root, ["a.py"], depth="symbols", previous_graph_path=graph_path, manifest_path=manifest_path
            )
            targeted_nodes = sorted((n.label, n.path) for n in targeted.nodes.values())
            targeted_edges = sorted((e.source, e.target, e.type) for e in targeted.edges)

        self.assertEqual(full_nodes, targeted_nodes)
        self.assertEqual(full_edges, targeted_edges)
        # The cross-file call must actually be present, not just equal-and-empty.
        self.assertIn(("a_py__foo", "b_py__baz", "calls"), targeted_edges)

    def test_update_paths_preserves_concept_edges_for_untouched_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # b.py's function name matches a registered interpretation-layer
            # concept alias, producing an "implements_algorithm" edge.
            (root / "b.py").write_text("def dynamic_programming():\n    return 1\n", encoding="utf-8")
            (root / "a.py").write_text("def foo():\n    return 1\n", encoding="utf-8")
            graph_path = root / ".graphgraph" / "graph.json"
            manifest_path = root / ".graphgraph" / "manifest.json"

            graph = scan_directory(root, depth="symbols", previous_graph_path=None, manifest_path=manifest_path)
            save_graph(graph, graph_path)
            concept_edges_before = {
                (e.source, e.target, e.type) for e in graph.edges if e.type == "implements_algorithm"
            }
            self.assertTrue(concept_edges_before, "fixture should produce at least one concept edge")
            self.assertEqual(graph.metadata["source_concepts_mode"], "closed_registry_exact_alias")
            self.assertGreater(int(graph.metadata["source_concepts_eligible"]), 0)
            self.assertGreater(int(graph.metadata["source_concepts_linked_nodes"]), 0)
            self.assertIn("source_concepts_rejected_no_registry_alias", graph.metadata)

            # Touch only a.py -- b.py is untouched and must keep its concept
            # edge via manifest restoration, not fresh linking.
            (root / "a.py").write_text("def foo():\n    return 2\n", encoding="utf-8")
            targeted = update_paths(
                root, ["a.py"], depth="symbols", previous_graph_path=graph_path, manifest_path=manifest_path
            )
            concept_edges_after = {
                (e.source, e.target, e.type) for e in targeted.edges if e.type == "implements_algorithm"
            }
            self.assertEqual(concept_edges_before, concept_edges_after)
            self.assertEqual(
                targeted.metadata["source_concepts_linked_nodes"],
                graph.metadata["source_concepts_linked_nodes"],
            )
            self.assertEqual(
                targeted.metadata["source_concepts_eligible"],
                graph.metadata["source_concepts_eligible"],
            )
            self.assertEqual(
                targeted.metadata["source_concepts_scope"],
                "full_graph_snapshot",
            )
            self.assertEqual(
                targeted.metadata["source_concepts_last_update_scope"],
                "changed_files",
            )
            self.assertEqual(
                targeted.metadata["source_concepts_last_update_linked_nodes"],
                "0",
            )

    def test_update_paths_requires_prior_scan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises(ValueError):
                update_paths(
                    root,
                    ["a.py"],
                    previous_graph_path=root / ".graphgraph" / "graph.json",
                    manifest_path=root / ".graphgraph" / "manifest.json",
                )

    def test_update_paths_rejects_stale_manifest_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.py").write_text("def foo():\n    return 1\n", encoding="utf-8")
            graph_path = root / ".graphgraph" / "graph.json"
            manifest_path = root / ".graphgraph" / "manifest.json"
            graph = scan_directory(root, depth="symbols", manifest_path=manifest_path)
            save_graph(graph, graph_path)
            raw = json.loads(manifest_path.read_text(encoding="utf-8"))
            raw.pop("version")
            manifest_path.write_text(json.dumps(raw), encoding="utf-8")

            with self.assertRaises(ValueError):
                update_paths(
                    root,
                    ["a.py"],
                    previous_graph_path=graph_path,
                    manifest_path=manifest_path,
                )

    def test_full_scan_rebuilds_files_from_incompatible_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "roadmap.md").write_text(
                "# Roadmap\n\n* `[ ]` **Proof search:** Not implemented.\n",
                encoding="utf-8",
            )
            graph_path = root / ".graphgraph" / "graph.json"
            manifest_path = root / ".graphgraph" / "manifest.json"
            graph = scan_directory(
                root,
                depth="symbols",
                docs=True,
                manifest_path=manifest_path,
            )
            save_graph(graph, graph_path)
            raw = json.loads(manifest_path.read_text(encoding="utf-8"))
            raw["version"] = 0
            manifest_path.write_text(json.dumps(raw), encoding="utf-8")
            events: list[tuple[str, str]] = []

            rebuilt = scan_directory(
                root,
                depth="symbols",
                docs=True,
                previous_graph_path=graph_path,
                manifest_path=manifest_path,
                progress=lambda phase, detail: events.append((phase, detail)),
            )

            self.assertTrue(any(
                phase == "hash" and "dirty=1 restored=0" in detail
                for phase, detail in events
            ))
            self.assertTrue(any(
                node.kind == "paragraph" and "Proof search" in node.label
                for node in rebuilt.nodes.values()
            ))
            self.assertEqual(
                json.loads(manifest_path.read_text(encoding="utf-8"))["version"],
                MANIFEST_VERSION,
            )

    def test_update_paths_treats_missing_target_as_removal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.py").write_text("def foo():\n    return 1\n", encoding="utf-8")
            graph_path = root / ".graphgraph" / "graph.json"
            manifest_path = root / ".graphgraph" / "manifest.json"

            graph = scan_directory(root, depth="symbols", previous_graph_path=None, manifest_path=manifest_path)
            save_graph(graph, graph_path)
            self.assertTrue(any(n.path == "a.py" for n in graph.nodes.values()))

            (root / "a.py").unlink()
            result = update_paths(
                root, ["a.py"], depth="symbols", previous_graph_path=graph_path, manifest_path=manifest_path
            )
            self.assertFalse(any(n.path == "a.py" for n in result.nodes.values()))
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertNotIn("a.py", manifest["files"])

    def test_remove_paths_drops_file_nodes_and_manifest_entry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.py").write_text("def foo():\n    return bar()\n\ndef bar():\n    return 1\n", encoding="utf-8")
            (root / "b.py").write_text("def baz():\n    return 2\n", encoding="utf-8")
            graph_path = root / ".graphgraph" / "graph.json"
            manifest_path = root / ".graphgraph" / "manifest.json"

            graph = scan_directory(root, depth="symbols", previous_graph_path=None, manifest_path=manifest_path)
            save_graph(graph, graph_path)

            result = remove_paths(
                root, ["b.py"], depth="symbols", previous_graph_path=graph_path, manifest_path=manifest_path
            )
            self.assertFalse(any(n.path == "b.py" for n in result.nodes.values()))
            self.assertTrue(any(n.path == "a.py" for n in result.nodes.values()))
            # a.py's own internal structure survives untouched.
            self.assertIn(("a_py__foo", "a_py__bar", "calls"), {(e.source, e.target, e.type) for e in result.edges})
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertNotIn("b.py", manifest["files"])
            self.assertIn("a.py", manifest["files"])

    def test_remove_paths_does_not_restore_referenced_file_endpoint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.py").write_text("from b import target\n", encoding="utf-8")
            (root / "b.py").write_text("def target():\n    return 1\n", encoding="utf-8")
            graph_path = root / ".graphgraph" / "graph.json"
            manifest_path = root / ".graphgraph" / "manifest.json"
            graph = scan_directory(root, depth="symbols", manifest_path=manifest_path)
            save_graph(graph, graph_path)

            result = remove_paths(
                root, ["b.py"], depth="symbols", previous_graph_path=graph_path, manifest_path=manifest_path
            )

            self.assertFalse(any(node.path == "b.py" for node in result.nodes.values()))
            self.assertTrue(any(node.path == "a.py" for node in result.nodes.values()))

    def test_scanner_detects_imports(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "app.py").write_text("from db import connect\nfrom utils import helper\n", encoding="utf-8")
            (root / "db.py").write_text("def connect(): pass\n", encoding="utf-8")
            (root / "utils.py").write_text("def helper(): pass\n", encoding="utf-8")
            graph = scan_directory(root)
            self.assertEqual(len(graph.nodes), 3)
            edge_pairs = {(e.source, e.target) for e in graph.edges}
            app_id = next(nid for nid, n in graph.nodes.items() if n.label == "app.py")
            db_id = next(nid for nid, n in graph.nodes.items() if n.label == "db.py")
            utils_id = next(nid for nid, n in graph.nodes.items() if n.label == "utils.py")
            self.assertIn((app_id, db_id), edge_pairs)
            self.assertIn((app_id, utils_id), edge_pairs)

    def test_scanner_resolves_indexed_java_csharp_and_lean_imports(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "java").mkdir()
            (root / "java" / "Main.java").write_text("import pkg.Target;\nclass Main {}\n", encoding="utf-8")
            (root / "java" / "Target.java").write_text("class Target {}\n", encoding="utf-8")
            (root / "csharp").mkdir()
            (root / "csharp" / "Client.cs").write_text("using Company.Widget;\nclass Client {}\n", encoding="utf-8")
            (root / "csharp" / "Widget.cs").write_text("class Widget {}\n", encoding="utf-8")
            lean = root / "workspace" / "Lib"
            lean.mkdir(parents=True)
            (root / "Main.lean").write_text("import Lib.Util\n", encoding="utf-8")
            (lean / "Util.lean").write_text("def helper := 1\n", encoding="utf-8")

            graph = scan_directory(root)
            edge_paths = {
                (graph.nodes[edge.source].path, graph.nodes[edge.target].path, edge.type)
                for edge in graph.edges
                if edge.source in graph.nodes and edge.target in graph.nodes
            }

            self.assertIn(("java/Main.java", "java/Target.java", "imports"), edge_paths)
            self.assertIn(("csharp/Client.cs", "csharp/Widget.cs", "imports"), edge_paths)
            self.assertIn(("Main.lean", "workspace/Lib/Util.lean", "imports"), edge_paths)

    def test_scanner_detects_python_multiline_parenthesized_imports(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "app.py").write_text(
                "from db import (\n    connect,\n    disconnect as close\n)\n", encoding="utf-8"
            )
            (root / "db.py").write_text("def connect(): pass\ndef disconnect(): pass\n", encoding="utf-8")
            graph = scan_directory(root)
            self.assertEqual(len(graph.nodes), 2)
            edge_pairs = {(e.source, e.target) for e in graph.edges}
            app_id = next(nid for nid, n in graph.nodes.items() if n.label == "app.py")
            db_id = next(nid for nid, n in graph.nodes.items() if n.label == "db.py")
            self.assertIn((app_id, db_id), edge_pairs)

    def test_scanner_detects_python_relative_imports_and_hierarchy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pkg = root / "pkg"
            sub = pkg / "sub"
            sub.mkdir(parents=True)
            (pkg / "__init__.py").write_text("", encoding="utf-8")
            (sub / "__init__.py").write_text("", encoding="utf-8")
            (pkg / "core.py").write_text("def connect(): pass\n", encoding="utf-8")
            (pkg / "utils.py").write_text("def helper(): pass\n", encoding="utf-8")
            (sub / "worker.py").write_text(
                "from ..core import connect\nfrom . import local\nimport pkg.utils as utils\n",
                encoding="utf-8",
            )
            (sub / "local.py").write_text("def local(): pass\n", encoding="utf-8")
            graph = scan_directory(root)
            edge_pairs = {(e.source, e.target, e.type) for e in graph.edges}
            worker_id = next(nid for nid, n in graph.nodes.items() if n.path == "pkg/sub/worker.py")
            core_id = next(nid for nid, n in graph.nodes.items() if n.path == "pkg/core.py")
            local_id = next(nid for nid, n in graph.nodes.items() if n.path == "pkg/sub/local.py")
            utils_id = next(nid for nid, n in graph.nodes.items() if n.path == "pkg/utils.py")

            self.assertIn((worker_id, core_id, "imports"), edge_pairs)
            self.assertIn((worker_id, local_id, "imports"), edge_pairs)
            self.assertIn((worker_id, utils_id, "imports"), edge_pairs)
            self.assertTrue(any(e.type == "contains" and e.target == worker_id for e in graph.edges))

    def test_scanner_skips_pycache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "__pycache__").mkdir()
            (root / "__pycache__" / "app.cpython-312.pyc").write_bytes(b"")
            (root / "app.py").write_text("pass\n", encoding="utf-8")
            graph = scan_directory(root)
            for node in graph.nodes.values():
                self.assertNotIn("__pycache__", node.path)
            self.assertEqual(len(graph.nodes), 1)

    def test_scanner_max_nodes_respected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for i in range(10):
                (root / f"mod_{i}.py").write_text("pass\n", encoding="utf-8")
            graph = scan_directory(root, max_nodes=5)
            self.assertLessEqual(len(graph.nodes), 5)

    def test_collect_files_reports_truncation(self) -> None:
        # Regression: collect_files silently dropped every file past
        # max_nodes with no way for the caller to know the scan was
        # incomplete rather than just small. Confirmed on a real large C
        # codebase: a directly-called function 469 call sites deep never
        # got a node because its file fell past the cap, and nothing
        # indicated the graph was incomplete.
        from graphgraph.scanner.files import collect_files

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for i in range(10):
                (root / f"mod_{i}.py").write_text("pass\n", encoding="utf-8")
            result = collect_files(root, 5)
            self.assertEqual(len(result.files), 5)
            self.assertTrue(result.truncated)
            self.assertEqual(result.total_matched, 10)

            result_untruncated = collect_files(root, 100)
            self.assertFalse(result_untruncated.truncated)
            self.assertEqual(result_untruncated.total_matched, 10)

    def test_scan_directory_surfaces_file_truncation_in_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for i in range(10):
                (root / f"mod_{i}.py").write_text("pass\n", encoding="utf-8")
            graph = scan_directory(root, max_nodes=5)
            self.assertEqual(graph.metadata.get("files_truncated"), "true")
            self.assertEqual(graph.metadata.get("files_total_matched"), "10")

            graph_full = scan_directory(root, max_nodes=100)
            self.assertNotIn("files_truncated", graph_full.metadata)

    def test_regex_extractor_reports_symbol_truncation(self) -> None:
        # Same silent-truncation bug class, at the symbol-extraction layer:
        # TreeSitterExtractor/RegexExtractor both used to `break` out the
        # instant max_total_symbols was hit with no signal to the caller,
        # so every file processed afterward got zero symbols.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            files = []
            for i in range(3):
                path = root / f"mod_{i}.py"
                path.write_text("\n".join(f"def fn_{i}_{j}(): pass" for j in range(10)) + "\n", encoding="utf-8")
                files.append(SourceFile(path, f"mod_{i}.py", f"mod_{i}_py", path.read_text(encoding="utf-8")))

            result = RegexExtractor().extract_symbols(files, max_total_symbols=5)
            self.assertTrue(result.truncated)
            self.assertLessEqual(len(result.nodes), 5)

            result_full = RegexExtractor().extract_symbols(files, max_total_symbols=1000)
            self.assertFalse(result_full.truncated)
            self.assertEqual(len(result_full.nodes), 30)

    def test_scan_directory_surfaces_symbol_truncation_in_metadata(self) -> None:
        # Integration-level confirmation through the real scan_directory
        # path. The derived symbol cap has a max(500, ...) floor, so this
        # needs enough real defs to exceed 500 even at a small max_nodes.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for i in range(20):
                (root / f"mod_{i}.py").write_text(
                    "\n".join(f"def fn_{i}_{j}(): pass" for j in range(30)) + "\n", encoding="utf-8"
                )
            graph = scan_directory(root, max_nodes=20, depth="symbols", frontend="regex")
            self.assertEqual(graph.metadata.get("symbols_truncated"), "true")
            self.assertIn("symbols_cap", graph.metadata)

    def test_scanner_skips_tmp_directories_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src").mkdir()
            (root / "tmp").mkdir()
            (root / "evidence").mkdir()
            (root / "artifacts").mkdir()
            (root / "graphify-out").mkdir()
            (root / ".code-review-graph").mkdir()
            (root / "src" / "app.py").write_text("def run(): pass\n", encoding="utf-8")
            (root / "tmp" / "vendored.lean").write_text("def noisy := 1\n", encoding="utf-8")
            (root / "evidence" / "status.md").write_text("# Old generated answer\n", encoding="utf-8")
            (root / "artifacts" / "report.py").write_text("def generated(): pass\n", encoding="utf-8")
            (root / "graphify-out" / "graph.json").write_text('{"nodes":[],"edges":[]}\n', encoding="utf-8")
            (root / ".code-review-graph" / "graph.json").write_text('{"nodes":[],"edges":[]}\n', encoding="utf-8")

            graph = scan_directory(root, depth="symbols")
            paths = {node.path for node in graph.nodes.values()}
            self.assertIn("src/app.py", paths)
            self.assertNotIn("tmp/vendored.lean", paths)
            self.assertNotIn("evidence/status.md", paths)
            self.assertNotIn("artifacts/report.py", paths)
            self.assertNotIn("graphify-out/graph.json", paths)
            self.assertNotIn(".code-review-graph/graph.json", paths)

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

    def test_history_bugfix_and_maintenance_classification(self) -> None:
        from graphgraph.scanner.history import _is_bugfix_commit

        # Clear bug fix -> included.
        self.assertTrue(_is_bugfix_commit("fix: cast scanner facts list to tuple to match Node dataclass typing"))
        # Maintenance-only -> excluded (no bugfix keyword at all).
        self.assertFalse(_is_bugfix_commit("chore: remove temporary web search lookup capabilities"))
        # Contains a bugfix keyword AND a maintenance keyword -> excluded by the AND-NOT rule.
        self.assertFalse(_is_bugfix_commit("style: fix ruff lint errors in scanner module"))
        # Neutral feature commit -> excluded (no bugfix keyword).
        self.assertFalse(_is_bugfix_commit("feat: add packet renderer for hybrid format"))

    def test_history_parse_commit_log_output(self) -> None:
        from graphgraph.scanner.history import _parse_commit_log_output

        raw = (
            "COMMIT abc1234567890\x1ffix: handle empty file list\n"
            "2\t1\tsrc/graphgraph/scanner/core.py\n"
            "0\t3\tsrc/graphgraph/scanner/files.py\n"
            "\n"
            "COMMIT def4567890abc\x1fchore: bump dependency versions\n"
            "1\t1\tpyproject.toml\n"
        )
        records = _parse_commit_log_output(raw)
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0].sha, "abc1234567890")
        self.assertEqual(records[0].subject, "fix: handle empty file list")
        self.assertEqual(
            records[0].files,
            ("src/graphgraph/scanner/core.py", "src/graphgraph/scanner/files.py"),
        )
        self.assertEqual(records[1].files, ("pyproject.toml",))

    def test_history_parse_commit_log_output_handles_renames_and_spaces(self) -> None:
        # Regression: numstat lines are tab-separated (added\tremoved\tpath), but
        # the parser used str.split() (whitespace-generic), which silently
        # mis-parses two common real cases:
        #  1. A path containing a space (e.g. "docs/getting started.md") gets
        #     split into multiple tokens, so parts[2] is just "docs/getting"
        #     -- never matches any real file.
        #  2. Git's rename numstat syntax -- "old => new" or an abbreviated
        #     "common/{old => new}/tail" -- also splits on the whitespace
        #     around "=>", so parts[2] becomes a garbled fragment like
        #     "src/{old_name.py" instead of the file's current path, silently
        #     dropping the fixes-edge for every renamed file.
        from graphgraph.scanner.history import _parse_commit_log_output

        raw = (
            "COMMIT abc1234567890\x1ffix: rename and reword docs\n"
            "1\t0\tsrc/{old_name.py => new_name.py}\n"
            "2\t2\tsrc/old_dir/thing.py => other_dir/thing.py\n"
            "1\t1\tdocs/getting started.md\n"
        )
        records = _parse_commit_log_output(raw)
        self.assertEqual(len(records), 1)
        self.assertEqual(
            records[0].files,
            (
                "src/new_name.py",
                "other_dir/thing.py",
                "docs/getting started.md",
            ),
        )

    def test_history_skips_wide_commits_above_file_cap(self) -> None:
        # Found via real-data validation against this repo's own history: a large
        # refactor commit that happened to mention "fix" touched 84 files and would
        # otherwise become an artificially high-degree hub node.
        from graphgraph.scanner.history import extract_commit_history

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".git").mkdir()

            def fake_run(*args, **kwargs):
                class _Result:
                    returncode = 0
                    stdout = (
                        "COMMIT wide0000001\x1frefactor codebase, fix imports along the way\n"
                        + "".join(f"1\t0\tfile{i}.py\n" for i in range(25))
                        + "\nCOMMIT narrow000001\x1ffix: off-by-one in loop\n"
                        "1\t0\tfile0.py\n"
                    )

                return _Result()

            file_map = {f"file{i}.py": f"file_{i}" for i in range(25)}
            with patch("graphgraph.scanner.history.subprocess.run", side_effect=fake_run):
                nodes, edges = extract_commit_history(root, file_map, max_files_per_commit=20)

            self.assertNotIn("commit_wide0000", nodes)
            self.assertIn("commit_narrow00", nodes)
            self.assertEqual(len(edges), 1)

    @unittest.skipUnless(shutil.which("git"), "git binary not available on PATH")
    def test_get_git_metadata_handles_quoted_paths(self) -> None:
        # Regression: _get_git_metadata parsed `git status --porcelain` output
        # assuming paths are never quoted, but git's core.quotepath default
        # wraps a path in double quotes with C-style/octal escapes whenever it
        # contains a space or non-ASCII byte (e.g. "caf\303\251.py" for
        # "café.py"). The naive line[3:].strip() parse kept the literal quote
        # characters and escape sequences in the path, so such files never
        # matched the real on-disk relative path and were silently dropped
        # from git-priority scanning. Fixed by using `-z` (NUL-separated,
        # never-quoted output) instead of parsing quoted text.
        from graphgraph.scanner.core import _get_git_metadata

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            def run_git(*args: str) -> None:
                subprocess.run(["git", *args], cwd=root, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

            run_git("init", "-q")
            run_git("config", "user.email", "test@example.com")
            run_git("config", "user.name", "Test User")
            (root / "app.py").write_text("x = 1\n", encoding="utf-8")
            run_git("add", ".")
            run_git("commit", "-q", "-m", "initial")

            # Untracked file with a space in the name -- git quotes this
            # unless the name is already "safe", and even a space alone
            # doesn't always trigger quoting, so combine it with a non-ASCII
            # character to force core.quotepath's default quoting path.
            (root / "notes café.md").write_text("hi\n", encoding="utf-8")

            dirty_files, _churn = _get_git_metadata(root)
            self.assertIn("notes café.md", dirty_files, dirty_files)

    def test_get_git_metadata_handles_staged_rename(self) -> None:
        # Regression guard for the -z parsing rewrite: a staged rename/copy
        # entry is followed by an *extra* NUL-terminated token (the original
        # path) that must be consumed and skipped, not treated as its own
        # dirty-file entry -- otherwise the old path would leak into
        # dirty_files as a bogus, nonexistent file.
        from graphgraph.scanner.core import _get_git_metadata

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            def run_git(*args: str) -> None:
                subprocess.run(["git", *args], cwd=root, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

            run_git("init", "-q")
            run_git("config", "user.email", "test@example.com")
            run_git("config", "user.name", "Test User")
            (root / "old_name.py").write_text("x = 1\n" * 5, encoding="utf-8")
            run_git("add", ".")
            run_git("commit", "-q", "-m", "initial")
            run_git("mv", "old_name.py", "new_name.py")

            dirty_files, _churn = _get_git_metadata(root)
            self.assertIn("new_name.py", dirty_files, dirty_files)
            self.assertNotIn("old_name.py", dirty_files, dirty_files)

    def test_history_real_git_repo_end_to_end(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            def run_git(*args: str) -> None:
                subprocess.run(["git", *args], cwd=root, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

            run_git("init", "-q")
            run_git("config", "user.email", "test@example.com")
            run_git("config", "user.name", "Test User")

            (root / "app.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
            (root / "README.md").write_text("# demo\n", encoding="utf-8")
            run_git("add", ".")
            run_git("commit", "-q", "-m", "feat: initial commit")

            (root / "app.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
            run_git("add", ".")
            run_git("commit", "-q", "-m", "fix: correct add() returning subtraction result")

            (root / "app.py").write_text(
                "def add(a, b):\n    return a - b\n\n\ndef sub(a, b):\n    return a - b\n",
                encoding="utf-8",
            )
            run_git("add", ".")
            run_git("commit", "-q", "-m", "style: reformat with black")

            (root / "README.md").write_text("# demo\n\nUsage docs.\n", encoding="utf-8")
            run_git("add", ".")
            run_git("commit", "-q", "-m", "docs: add usage section")

            graph = scan_directory(root, depth="files", history=True)

            commit_nodes = {n.id: n for n in graph.nodes.values() if n.kind == "commit"}
            self.assertEqual(len(commit_nodes), 1, commit_nodes)
            commit_node = next(iter(commit_nodes.values()))
            self.assertIn("correct add()", commit_node.summary)

            fixes_edges = [e for e in graph.edges if e.type == "fixes"]
            self.assertEqual(len(fixes_edges), 1)
            app_file_node = next(n for n in graph.nodes.values() if n.path == "app.py")
            self.assertEqual(fixes_edges[0].source, commit_node.id)
            self.assertEqual(fixes_edges[0].target, app_file_node.id)

    def test_scanner_c_includes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "main.c").write_text('#include "utils.h"\nint main(){}\n', encoding="utf-8")
            (root / "utils.h").write_text("void helper();\n", encoding="utf-8")
            graph = scan_directory(root)
            self.assertEqual(len(graph.nodes), 2)
            self.assertEqual(len(graph.edges), 1)
            self.assertEqual(graph.edges[0].type, "imports")

    def test_scanner_rust_mod(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "main.rs").write_text("mod utils;\nfn main(){}\n", encoding="utf-8")
            (root / "utils.rs").write_text("pub fn helper(){}\n", encoding="utf-8")
            graph = scan_directory(root)
            self.assertEqual(len(graph.nodes), 2)
            self.assertEqual(len(graph.edges), 1)

    def test_scanner_go_relative_import(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "main.go").write_text('import "./pkg"\nfunc main(){}\n', encoding="utf-8")
            pkg = root / "pkg"
            pkg.mkdir()
            (pkg / "pkg.go").write_text("package pkg\n", encoding="utf-8")
            graph = scan_directory(root)
            # main.go and pkg/pkg.go should be nodes
            self.assertGreaterEqual(len(graph.nodes), 2)

    def test_scanner_generic_mentions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.txt").write_text("See the config module for settings.\n", encoding="utf-8")
            (root / "config.py").write_text("# config\n", encoding="utf-8")
            graph = scan_directory(root, generic_mentions=True)
            edge_types = {e.type for e in graph.edges}
            self.assertIn("references", edge_types)

    def test_scanner_html_href(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "index.html").write_text('<a href="./about.html">About</a>\n', encoding="utf-8")
            (root / "about.html").write_text("<h1>About</h1>\n", encoding="utf-8")
            graph = scan_directory(root)
            self.assertEqual(len(graph.nodes), 2)
            self.assertTrue(any(e.type == "links" for e in graph.edges))

    def test_scanner_depth_symbols_python(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "app.py").write_text(
                "class Server:\n    def handle(self):\n        pass\n\ndef run():\n    pass\n",
                encoding="utf-8",
            )
            graph = scan_directory(root, depth="symbols", frontend="regex")
            self.assertEqual(graph.metadata["scan_depth"], "symbols")
            self.assertIn(graph.metadata["frontend"], {"regex", "tree_sitter"})
            kinds = {n.kind for n in graph.nodes.values()}
            self.assertIn("class", kinds)
            self.assertIn("function", kinds)
            contains_edges = [e for e in graph.edges if e.type == "contains"]
            self.assertGreaterEqual(len(contains_edges), 2)

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

    def test_scanner_depth_symbols_kotlin_scala_swift_via_scan_directory(self) -> None:
        # Regression: .kt/.scala/.swift are advertised in the README as
        # supported symbol-scan languages, and TreeSitterExtractor fully
        # supports them (test_tree_sitter_extractor_captures_additional_languages
        # proves the extractor itself works). These extensions were once absent
        # from the scanner's source-file gate, so they were silently skipped
        # before select_extractor() could see them -- a gap invisible to
        # extractor-level unit tests.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # Realistic multi-line formatting (the regex fallback is
            # line-anchored, unlike TreeSitterExtractor's AST-based parsing;
            # this matches how real Kotlin/Scala/Swift source is formatted).
            (root / "Svc.kt").write_text(
                "class RecipeResolver {\n    fun resolve(id: String): Int {\n        return 1\n    }\n}\n",
                encoding="utf-8",
            )
            (root / "Svc.scala").write_text(
                "class RecipeResolver {\n  def resolve(id: String): Int = 1\n}\n",
                encoding="utf-8",
            )
            (root / "Svc.swift").write_text(
                "class RecipeResolver {\n    func resolve(_ id: String) -> Int {\n        return 1\n    }\n}\n",
                encoding="utf-8",
            )
            graph = scan_directory(root, depth="symbols", frontend="regex")
            labels = {n.label for n in graph.nodes.values()}
            self.assertIn("RecipeResolver", labels, "Kotlin/Scala/Swift class should be extracted, not just file-level")
            self.assertIn("resolve", labels)

    def test_scanner_depth_symbols_rust(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "lib.rs").write_text(
                "pub struct Config { pub name: String }\npub fn load() -> Config { todo!() }\n",
                encoding="utf-8",
            )
            graph = scan_directory(root, depth="symbols")
            kinds = {n.kind for n in graph.nodes.values()}
            self.assertIn("struct", kinds)
            self.assertIn("function", kinds)

    def test_scanner_depth_symbols_cross_file_references(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "server.py").write_text(
                "def handle_request(config):\n    return config\n",
                encoding="utf-8",
            )
            (root / "main.py").write_text(
                "from server import handle_request\nhandle_request(None)\n",
                encoding="utf-8",
            )
            graph = scan_directory(root, depth="symbols", frontend="regex")
            ref_edges = [e for e in graph.edges if e.type == "references"]
            self.assertGreaterEqual(len(ref_edges), 1)

    def test_scanner_depth_symbols_js(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "api.js").write_text(
                "class Router {}\nexport function createApp() { return new Router(); }\n",
                encoding="utf-8",
            )
            graph = scan_directory(root, depth="symbols")
            kinds = {n.kind for n in graph.nodes.values()}
            self.assertIn("class", kinds)
            self.assertIn("function", kinds)

    def test_extract_symbols_python(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            f = root / "mod.py"
            f.write_text("class Foo:\n    def bar(self): baz()\n\ndef baz(): pass\n", encoding="utf-8")
            tuples = [(f, "mod.py", "mod_py", f.read_text(encoding="utf-8"))]
            nodes, edges, _truncated = extract_symbols(tuples)
            labels = {n.label for n in nodes.values()}
            self.assertIn("Foo", labels)
            self.assertIn("baz", labels)
            contains = [e for e in edges if e.type == "contains"]
            self.assertGreaterEqual(len(contains), 2)
            calls = [e for e in edges if e.type == "calls"]
            self.assertGreaterEqual(len(calls), 1)

    def test_extract_symbols_rust(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            f = root / "lib.rs"
            f.write_text(
                "pub trait Metric {}\n"
                "pub struct Point { x: i32 }\n"
                "impl Metric for Point {}\n"
                "pub fn norm() -> f64 { 0.0 }\n"
                "pub fn distance(a: Point) -> f64 { norm() }\n",
                encoding="utf-8",
            )
            tuples = [(f, "lib.rs", "lib_rs", f.read_text(encoding="utf-8"))]
            nodes, edges, _truncated = extract_symbols(tuples)
            labels = {n.label for n in nodes.values()}
            self.assertIn("Point", labels)
            self.assertIn("distance", labels)
            self.assertTrue(any(e.type == "calls" for e in edges))
            self.assertTrue(any(e.type == "implements" for e in edges))

    def test_regex_extractor_handles_ruby_and_php_without_tree_sitter(self) -> None:
        # Regression: .rb/.php are declared in PARSEABLE_SUFFIXES/SOURCE_SUFFIXES
        # (files.py) as supported source languages, but the regex-fallback
        # _EXTRACTORS dict (used whenever tree-sitter isn't installed) had no
        # entries for them, so Ruby/PHP files silently degraded to file-level
        # nodes with zero symbol-level extraction -- a coverage gap for a
        # declared-supported language, not just a missing nice-to-have.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rb = root / "service.rb"
            rb.write_text(
                "module Billing\n"
                "  class Invoice\n"
                "    def total\n"
                "      compute_total\n"
                "    end\n"
                "\n"
                "    def self.build\n"
                "      new\n"
                "    end\n"
                "  end\n"
                "end\n",
                encoding="utf-8",
            )
            php = root / "controller.php"
            php.write_text(
                "<?php\n"
                "class InvoiceController {\n"
                "    public function show($id) {\n"
                "        return find_invoice($id);\n"
                "    }\n"
                "}\n",
                encoding="utf-8",
            )
            files = [
                SourceFile(rb, "service.rb", "service_rb", rb.read_text(encoding="utf-8")),
                SourceFile(php, "controller.php", "controller_php", php.read_text(encoding="utf-8")),
            ]
            result = RegexExtractor().extract_symbols(files, max_total_symbols=100)
            labels_by_kind = {n.label: n.kind for n in result.nodes.values()}
            self.assertEqual(labels_by_kind.get("Invoice"), "class")
            self.assertEqual(labels_by_kind.get("Billing"), "module")
            self.assertEqual(labels_by_kind.get("total"), "function")
            self.assertEqual(labels_by_kind.get("InvoiceController"), "class")
            self.assertEqual(labels_by_kind.get("show"), "function")

    def test_extract_symbols_does_not_link_calls_across_languages(self) -> None:
        # Regression: a Rust call site invoking a std-library-style method
        # (e.g. `.as_deref()`) must not resolve to an unrelated Python function
        # of the same name elsewhere in the repo -- found via a real cross-repo
        # scan where `crates/.../algorithm_shape.rs::examine` calls into
        # `Option::as_deref()` and a vendored numpy test fixture happened to
        # define an unrelated `def as_deref(expr):` at module scope, producing
        # a nonsensical Rust-calls-Python edge purely from name collision.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rs = root / "shape.rs"
            rs.write_text(
                "pub fn examine(x: Option<String>) -> Option<&str> { x.as_deref() }\n",
                encoding="utf-8",
            )
            py = root / "vendor" / "symbolic.py"
            py.parent.mkdir(parents=True, exist_ok=True)
            py.write_text("def as_deref(expr):\n    return expr\n", encoding="utf-8")
            tuples = [
                (rs, "shape.rs", "shape_rs", rs.read_text(encoding="utf-8")),
                (py, "vendor/symbolic.py", "vendor_symbolic_py", py.read_text(encoding="utf-8")),
            ]
            nodes, edges, _truncated = extract_symbols(tuples)
            self.assertIn("examine", {n.label for n in nodes.values()})
            self.assertIn("as_deref", {n.label for n in nodes.values()})
            cross_lang = [
                e for e in edges if e.type in ("calls", "references") and e.target == "vendor_symbolic_py__as_deref"
            ]
            self.assertEqual([], cross_lang, f"found Rust<->Python cross-language edges: {cross_lang}")

    def test_regex_extractor_does_not_resolve_arrow_qualified_calls_as_bare(self) -> None:
        # Regression: the RegexExtractor's callsite pattern only excluded a
        # preceding "." (receiver.method()) from bare-call resolution, not a
        # preceding "->" (receiver->method()). C/C++ pointer-member calls like
        # `ops->process(5)` are just as receiver-type-dependent as `.`-calls,
        # but fell through the "." -only negative lookbehind and got treated
        # like a bare call to any unrelated free function named "process"
        # elsewhere in the repo -- the same false-positive-resolution bug
        # class as the receiver.method() fix, just for the arrow operator.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            foo_c = root / "foo.c"
            foo_c.write_text(
                "struct Ops { int (*process)(int); };\nint foo(struct Ops *ops) {\n    return ops->process(5);\n}\n",
                encoding="utf-8",
            )
            reader_c = root / "reader.c"
            reader_c.write_text("int process(int fd) {\n    return fd + 1;\n}\n", encoding="utf-8")
            files = [
                SourceFile(foo_c, "foo.c", "foo_c", foo_c.read_text(encoding="utf-8")),
                SourceFile(reader_c, "reader.c", "reader_c", reader_c.read_text(encoding="utf-8")),
            ]
            result = RegexExtractor().extract_symbols(files, max_total_symbols=100)
            calls = {
                (result.nodes[e.source].label, result.nodes[e.target].label) for e in result.edges if e.type == "calls"
            }
            self.assertNotIn(
                ("foo", "process"),
                calls,
                f"found arrow-qualified-call-to-unrelated-free-function edge: {calls}",
            )

    def test_regex_js_extractor_does_not_misclassify_plain_constants_as_functions(self) -> None:
        # Regression: _JS_ARROW matched *any* `const/let/var x = ...` with an
        # optional trailing "(" (zero-width), so plain data constants like
        # `const apiUrl = "...";` or `const config = {...};` were recorded as
        # "function" symbols regardless of their actual value. Real arrow
        # functions and function expressions must still be detected.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            f = root / "config.js"
            f.write_text(
                'export const apiUrl = "https://example.com";\n'
                "export const config = { retries: 3 };\n"
                "export const helper = (x) => x + 1;\n"
                "const process = function(x) { return x; };\n",
                encoding="utf-8",
            )
            tuples = [(f, "config.js", "config_js", f.read_text(encoding="utf-8"))]
            nodes, _edges, _truncated = extract_symbols(tuples)
            labels_by_kind: dict[str, str] = {n.label: n.kind for n in nodes.values()}
            self.assertNotIn("apiUrl", labels_by_kind, "plain string constant misclassified as a symbol")
            self.assertNotIn("config", labels_by_kind, "plain object constant misclassified as a symbol")
            self.assertEqual(labels_by_kind.get("helper"), "function", "arrow function should still be detected")
            self.assertEqual(labels_by_kind.get("process"), "function", "function expression should still be detected")

    def test_incremental_scanner_basic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            # Setup files
            a_file = root / "a.py"
            b_file = root / "b.py"
            a_file.write_text("import b", encoding="utf-8")
            b_file.write_text("# clean file", encoding="utf-8")

            gg_dir = root / ".graphgraph"
            gg_dir.mkdir(parents=True, exist_ok=True)
            graph_path = gg_dir / "graph.json"
            manifest_path = gg_dir / "manifest.json"

            # Step 1: Initial full scan
            graph = scan_directory(root, depth="files", previous_graph_path=graph_path, manifest_path=manifest_path)
            save_graph(graph, graph_path)

            self.assertEqual(len(graph.nodes), 2)
            self.assertEqual(len(graph.edges), 1)

            # Verify manifest was created and populated
            self.assertTrue(manifest_path.exists())
            manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertIn("a.py", manifest_data["files"])
            self.assertIn("b.py", manifest_data["files"])
            b_orig_hash = manifest_data["files"]["b.py"]["hash"]

            # Step 2: Modify a.py, add c.py (b.py remains unchanged)
            a_file.write_text("import b\nimport c", encoding="utf-8")
            c_file = root / "c.py"
            c_file.write_text("# new file", encoding="utf-8")

            # Scan incrementally
            graph2 = scan_directory(root, depth="files", previous_graph_path=graph_path, manifest_path=manifest_path)
            save_graph(graph2, graph_path)

            # Verify all nodes/edges are updated/reconstructed
            self.assertEqual(len(graph2.nodes), 3)
            self.assertEqual(len(graph2.edges), 2)

            # Check manifest update
            manifest_data2 = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertIn("c.py", manifest_data2["files"])
            self.assertEqual(manifest_data2["files"]["b.py"]["hash"], b_orig_hash)

            # Verify b's nodes and edges were preserved from first run
            node_labels = {n.label for n in graph2.nodes.values()}
            self.assertIn("a.py", node_labels)
            self.assertIn("b.py", node_labels)
            self.assertIn("c.py", node_labels)

    def test_incremental_scan_drops_stale_cross_file_symbol_targets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            a_file = root / "a.py"
            b_file = root / "b.py"
            a_file.write_text(
                "from b import foo\n\ndef use_foo():\n    return foo()\n",
                encoding="utf-8",
            )
            b_file.write_text(
                "def foo():\n    return 1\n",
                encoding="utf-8",
            )

            gg_dir = root / ".graphgraph"
            gg_dir.mkdir(parents=True, exist_ok=True)
            graph_path = gg_dir / "graph.json"
            manifest_path = gg_dir / "manifest.json"

            graph = scan_directory(
                root,
                depth="symbols",
                frontend="regex",
                docs=False,
                previous_graph_path=None,
                manifest_path=manifest_path,
            )
            save_graph(graph, graph_path)
            old_target_ids = {nid for nid, node in graph.nodes.items() if node.path == "b.py" and node.label == "foo"}
            self.assertEqual(len(old_target_ids), 1)
            old_target_id = next(iter(old_target_ids))
            self.assertTrue(any(edge.target == old_target_id for edge in graph.edges))

            b_file.write_text(
                "def bar():\n    return 2\n",
                encoding="utf-8",
            )

            graph2 = scan_directory(
                root,
                depth="symbols",
                frontend="regex",
                docs=False,
                previous_graph_path=graph_path,
                manifest_path=manifest_path,
            )

            self.assertNotIn(old_target_id, graph2.nodes)
            self.assertFalse(any(edge.source == old_target_id or edge.target == old_target_id for edge in graph2.edges))
            self.assertTrue(any(node.path == "b.py" and node.label == "bar" for node in graph2.nodes.values()))
            result = validate_graph_json(graph_to_json(graph2))
            self.assertTrue(result.ok, result.errors)

    def test_incremental_scan_links_dirty_file_to_restored_symbol_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            a_file = root / "a.py"
            b_file = root / "b.py"
            a_file.write_text(
                "def use_foo():\n    return 0\n",
                encoding="utf-8",
            )
            b_file.write_text(
                "def foo():\n    return 1\n",
                encoding="utf-8",
            )

            gg_dir = root / ".graphgraph"
            gg_dir.mkdir(parents=True, exist_ok=True)
            graph_path = gg_dir / "graph.json"
            manifest_path = gg_dir / "manifest.json"

            graph = scan_directory(
                root,
                depth="symbols",
                frontend="regex",
                docs=False,
                previous_graph_path=None,
                manifest_path=manifest_path,
            )
            save_graph(graph, graph_path)
            target_id = next(nid for nid, node in graph.nodes.items() if node.path == "b.py" and node.label == "foo")

            a_file.write_text(
                "from b import foo\n\ndef use_foo():\n    return foo()\n",
                encoding="utf-8",
            )

            graph2 = scan_directory(
                root,
                depth="symbols",
                frontend="regex",
                docs=False,
                previous_graph_path=graph_path,
                manifest_path=manifest_path,
            )

            self.assertIn(target_id, graph2.nodes)
            self.assertTrue(any(edge.target == target_id and edge.type == "calls" for edge in graph2.edges))
            self.assertTrue(any(edge.target == target_id and edge.type == "references" for edge in graph2.edges))
            result = validate_graph_json(graph_to_json(graph2))
            self.assertTrue(result.ok, result.errors)

    def test_scan_directory_no_communities_param(self) -> None:
        """scan_directory must not accept a communities keyword argument."""
        import inspect

        from graphgraph.scanner import scan_directory

        sig = inspect.signature(scan_directory)
        self.assertNotIn("communities", sig.parameters)

    def test_imported_symbol_sources(self) -> None:
        from graphgraph.scanner.frontends import _imported_symbol_sources

        # Test python imports
        py_text = "from my_module import foo, bar as b\nfrom other.helper import transform"
        py_sources = _imported_symbol_sources(".py", py_text)
        self.assertEqual(py_sources.get("foo"), "my_module")
        self.assertEqual(py_sources.get("bar"), "my_module")
        self.assertEqual(py_sources.get("transform"), "helper")

        # Test js/ts imports
        js_text = "import { transform, load as l } from './my_helper';\nimport { other } from '../another';"
        js_sources = _imported_symbol_sources(".ts", js_text)
        self.assertEqual(js_sources.get("transform"), "my_helper")
        self.assertEqual(js_sources.get("load"), "my_helper")
        self.assertEqual(js_sources.get("other"), "another")

    def test_tree_sitter_resolves_rust_module_qualified_call_among_duplicate_names(self) -> None:
        if not tree_sitter_available():
            self.skipTest("tree_sitter is not installed")
        sources = {
            "crates/locus-frontends/src/formula.rs": "pub fn parse(input: &str) -> i32 { 1 }\n",
            "crates/other/src/parser.rs": "pub fn parse(input: &str) -> i32 { 2 }\n",
            "crates/locus-pipeline/src/lib.rs": (
                "pub fn parse_to_ir(input: &str) -> i32 {\n"
                "    locus_frontends::formula::parse(input)\n"
                "}\n"
            ),
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            files = []
            for rel, text in sources.items():
                path = root / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")
                files.append(SourceFile(path, rel, rel.replace("/", "_"), text))

            result = select_extractor("tree_sitter").extract_symbols(files, max_total_symbols=100)

        parse_to_ir = next(
            node.id for node in result.nodes.values()
            if node.label == "parse_to_ir"
        )
        formula_parse = next(
            node.id for node in result.nodes.values()
            if node.label == "parse" and node.path.endswith("locus-frontends/src/formula.rs")
        )
        self.assertTrue(
            any(
                edge.source == parse_to_ir
                and edge.target == formula_parse
                and edge.type == "calls"
                for edge in result.edges
            )
        )

    def test_tree_sitter_links_rust_test_expr_type_use_to_enum(self) -> None:
        if not tree_sitter_available():
            self.skipTest("tree_sitter is not installed")
        sources = {
            "crates/locus-engine/src/expression.rs": (
                "pub enum Expr { Constant(i32), Add(Box<Expr>, Box<Expr>) }\n"
            ),
            "crates/locus-engine/tests/expression_test.rs": (
                "#[test]\n"
                "fn simplifies_expr() {\n"
                "    let expr = Expr::Constant(1);\n"
                "    assert!(matches!(expr, Expr::Constant(1)));\n"
                "}\n"
            ),
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            files = []
            for rel, text in sources.items():
                path = root / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")
                files.append(SourceFile(path, rel, rel.replace("/", "_"), text))

            result = select_extractor("tree_sitter").extract_symbols(files, max_total_symbols=100)

        test_id = next(node.id for node in result.nodes.values() if node.label == "simplifies_expr")
        expr_id = next(node.id for node in result.nodes.values() if node.label == "Expr")
        self.assertTrue(
            any(
                edge.source == test_id
                and edge.target == expr_id
                and edge.type == "references"
                for edge in result.edges
            )
        )
