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
    RegexExtractor,
    SourceFile,
    _imported_symbol_names,
    available_frontends,
    select_extractor,
    tree_sitter_available,
)
from graphgraph.io import (
    graph_to_json,
    save_graph,
)
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

    def test_tree_sitter_extractor_captures_rust_fields_and_returns(self) -> None:
        if not tree_sitter_available():
            self.skipTest("tree_sitter is not installed")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            f = root / "lib.rs"
            text = "pub struct Point { pub x: f64, y: f64 }\npub fn make() -> Point { Point { x: 0.0, y: 0.0 } }\n"
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
            self.assertTrue(any(edge.type == "field_of" and edge.target == point_id for edge in result.edges))
            self.assertTrue(
                any(
                    edge.type == "returns" and edge.source == make_id and edge.target == point_id
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
            default = {p.relative_to(root).as_posix() for p in collect_files(root, 100)}
            self.assertNotIn("game/build/README.md", default)
            # find_pruned_dirs reports it (not silent).
            self.assertIn("build", find_pruned_dirs(root, frozenset({"build"})))
            # --include build keeps it.
            included = {p.relative_to(root).as_posix() for p in collect_files(root, 100, include=frozenset({"build"}))}
            self.assertIn("game/build/README.md", included)

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
            files = {p.relative_to(root).as_posix() for p in collect_files(root, 100)}
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
            self.assertEqual(by_label["RecipeResolver"].kind, "class")
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

    def test_scanner_depth_symbols_kotlin_scala_swift_via_scan_directory(self) -> None:
        # Regression: .kt/.scala/.swift are advertised in the README as
        # supported symbol-scan languages, and TreeSitterExtractor fully
        # supports them (test_tree_sitter_extractor_captures_additional_languages
        # proves the extractor itself works) -- but PARSEABLE_SUFFIXES
        # (files.py) never included these three extensions. Since
        # _build_graph_from_split filters dirty_files against
        # PARSEABLE_SUFFIXES *before* ever calling select_extractor(), these
        # files were silently skipped for symbol extraction end-to-end
        # through the real scan_directory pipeline, regardless of whether
        # tree-sitter was installed -- a gap invisible to extractor-level
        # unit tests that call select_extractor(...) directly.
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
            nodes, edges = extract_symbols(tuples)
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
            nodes, edges = extract_symbols(tuples)
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
            nodes, edges = extract_symbols(tuples)
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
            nodes, _edges = extract_symbols(tuples)
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
