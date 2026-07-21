from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from graphgraph import (
    scan_directory,
)
from graphgraph.scanner.ast import extract_symbols
from graphgraph.scanner.frontends import (
    RegexExtractor,
    SourceFile,
    TreeSitterExtractor,
    available_frontends,
    select_extractor,
    tree_sitter_available,
)


class FrontendsScannerTest(unittest.TestCase):
    """scanner/frontends/: grammars, parsers, and language extraction."""

    def test_frontend_capabilities(self) -> None:
        caps = available_frontends()
        names = {cap.name for cap in caps}
        self.assertIn("regex", names)
        self.assertIn("tree_sitter", names)
        self.assertTrue(next(cap for cap in caps if cap.name == "regex").available)

    def test_frontend_capabilities_report_per_language_readiness(self) -> None:
        with patch(
            "graphgraph.scanner.frontends.languages._language_available",
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
            "graphgraph.scanner.frontends.languages._parser_for_language",
            return_value=None,
        ):
            self.assertFalse(tree_sitter_available())

    def test_transient_grammar_failure_is_retried_instead_of_cached(self) -> None:
        # grammar loading (and its find_spec/import_module lookups) lives in the
        # languages layer, so patch there rather than on the package facade.
        from graphgraph.scanner.frontends import languages as frontends

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

            with patch("graphgraph.scanner.frontends.extractors._parser_for_suffix", return_value=TimedOutParser()):
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
        with patch("graphgraph.scanner.frontends.extractors._parser_for_suffix", return_value=BrokenParser()):
            with self.assertRaisesRegex(RuntimeError, "broken.rs"):
                TreeSitterExtractor().extract_symbols([source], max_total_symbols=20)

    def test_explicit_tree_sitter_fails_when_supported_grammar_is_unavailable(self) -> None:
        source = SourceFile(Path("sample.ts"), "sample.ts", "sample_ts", "export function run() {}\n")
        with (
            patch("graphgraph.scanner.frontends.extractors._parser_for_suffix", return_value=None),
            patch(
                "graphgraph.scanner.frontends.extractors.parser_unavailable_reason",
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
            patch("graphgraph.scanner.frontends.extractors._parser_for_suffix", return_value=None),
            patch(
                "graphgraph.scanner.frontends.extractors.parser_unavailable_reason",
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

    def test_scanner_rust_mod(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "main.rs").write_text("mod utils;\nfn main(){}\n", encoding="utf-8")
            (root / "utils.rs").write_text("pub fn helper(){}\n", encoding="utf-8")
            graph = scan_directory(root)
            self.assertEqual(len(graph.nodes), 2)
            self.assertEqual(len(graph.edges), 1)

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

    def test_tree_sitter_types_closure_and_loop_receivers_from_element_types(self) -> None:
        # Receiver typing previously stopped at the container: `Vec<Expr>`
        # yielded "Vec", so a closure or loop variable bound to one of its
        # elements had no type and its method calls fell out of topology --
        # the dominant unresolved shape in an idiomatic Rust workspace.
        if not tree_sitter_available():
            self.skipTest("tree_sitter is not installed")
        sources = {
            "src/expr.rs": "pub struct Expr; impl Expr { pub fn count_ops(&self) -> usize { 0 } }\n",
            "src/run.rs": (
                "use crate::expr::Expr;\n"
                "pub fn total(items: Vec<Expr>) -> usize {\n"
                "    let mut n = 0;\n"
                "    for item in items.iter() { n += item.count_ops(); }\n"
                "    n\n"
                "}\n"
                "pub fn mapped(rows: &[Expr]) -> Vec<usize> {\n"
                "    rows.iter().map(|r| r.count_ops()).collect()\n"
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

        target = next(
            node.id for node in result.nodes.values()
            if node.label == "count_ops" and node.kind == "method"
        )
        callers = {
            result.nodes[edge.source].label
            for edge in result.edges
            if edge.type == "calls" and edge.target == target and edge.source in result.nodes
        }
        # Both the for-loop binding and the closure parameter must resolve.
        self.assertIn("total", callers)
        self.assertIn("mapped", callers)

    def test_rust_element_type_refuses_generic_and_non_type_parameters(self) -> None:
        # The inference must stay conservative: a generic parameter is not a
        # concrete receiver, and claiming one would attach calls to a type
        # that does not exist.
        from graphgraph.scanner.frontends.rust import _rust_element_type

        self.assertEqual(_rust_element_type("Vec<Expr>"), "Expr")
        self.assertEqual(_rust_element_type("&[Finding]"), "Finding")
        self.assertEqual(_rust_element_type("HashMap<String, Advisor>"), "Advisor")
        self.assertEqual(_rust_element_type("Vec<Arc<Expr>>"), "Expr")
        for rejected in ("T", "Vec<T>", "HashMap<K, V>", "(A, B)", "u32", "Vec<(A, B)>"):
            self.assertEqual(_rust_element_type(rejected), "", rejected)

    def test_tree_sitter_types_inline_call_receivers_from_return_types(self) -> None:
        # `expr_or_empty(ir).count_ops()` -- the receiver is whatever the inner
        # call returns. Receivers that were not bare identifiers were blanked
        # outright, so a method reached only through a call result had no
        # caller edge and read as dead.
        if not tree_sitter_available():
            self.skipTest("tree_sitter is not installed")
        sources = {
            "src/expr.rs": "pub struct Expr; impl Expr { pub fn count_ops(&self) -> usize { 0 } }\n",
            "src/build.rs": (
                "use crate::expr::Expr;\n"
                "fn expr_or_empty(flag: bool) -> Expr { Expr }\n"
                "pub fn op_count(flag: bool) -> usize {\n"
                "    expr_or_empty(flag).count_ops()\n"
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

        target = next(
            node.id for node in result.nodes.values()
            if node.label == "count_ops" and node.kind == "method"
        )
        callers = {
            result.nodes[edge.source].label
            for edge in result.edges
            if edge.type == "calls" and edge.target == target and edge.source in result.nodes
        }
        self.assertIn("op_count", callers)

    def test_ambiguous_return_type_is_not_receiver_evidence(self) -> None:
        # Two functions of the same name returning different types cannot type
        # a receiver; guessing one would attach the call to the wrong owner.
        if not tree_sitter_available():
            self.skipTest("tree_sitter is not installed")
        sources = {
            "src/types.rs": (
                "pub struct Alpha; impl Alpha { pub fn run(&self) {} }\n"
                "pub struct Beta; impl Beta { pub fn run(&self) {} }\n"
            ),
            "src/a.rs": "use crate::types::Alpha;\nfn make(v: bool) -> Alpha { Alpha }\n",
            "src/b.rs": "use crate::types::Beta;\nfn make(v: bool) -> Beta { Beta }\n",
            "src/use.rs": "pub fn go(v: bool) { make(v).run(); }\n",
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

        go_id = next(node.id for node in result.nodes.values() if node.label == "go")
        run_targets = {
            edge.target for edge in result.edges
            if edge.type == "calls"
            and edge.source == go_id
            and result.nodes.get(edge.target)
            and result.nodes[edge.target].label == "run"
        }
        self.assertEqual(run_targets, set(), "ambiguous return type must not produce a calls edge")

    def test_declared_type_wins_over_inferred_return_type(self) -> None:
        # Return-type inference must not overwrite a declared annotation or
        # parameter type. It did, and the damage was invisible in the
        # resolved/unknown ratio -- displaced sites leave that denominator
        # entirely -- while costing real calls edges.
        if not tree_sitter_available():
            self.skipTest("tree_sitter is not installed")
        sources = {
            "src/types.rs": (
                "pub struct Declared; impl Declared { pub fn act(&self) {} }\n"
                "pub struct Returned; impl Returned { pub fn act(&self) {} }\n"
            ),
            "src/make.rs": "use crate::types::Returned;\nfn build(v: bool) -> Returned { Returned }\n",
            "src/use.rs": (
                "use crate::types::Declared;\n"
                "pub fn go(v: bool) {\n"
                "    let build: Declared = Declared;\n"
                "    build.act();\n"
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

        go_id = next(node.id for node in result.nodes.values() if node.label == "go")
        owners = {
            result.nodes[edge.target].id.split("__")[-2]
            for edge in result.edges
            if edge.type == "calls"
            and edge.source == go_id
            and result.nodes.get(edge.target)
            and result.nodes[edge.target].label == "act"
        }
        self.assertEqual(owners, {"Declared"}, f"declared type must win, got {owners}")
