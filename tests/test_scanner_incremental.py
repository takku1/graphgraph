from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from graphgraph import (
    Graph,
    remove_paths,
    scan_directory,
    update_paths,
)
from graphgraph.io import (
    graph_to_json,
    save_graph,
)
from graphgraph.packets.validation import validate_graph_json
from graphgraph.runtime.manifest import MANIFEST_VERSION
from graphgraph.scanner.frontends import (
    tree_sitter_available,
)


class IncrementalScannerTest(unittest.TestCase):
    """scanner/core.py incremental paths and runtime/manifest.py."""

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
            self.assertEqual(
                graph.metadata["source_concepts_mode"],
                "closed_registry_typed_fact_or_exact_alias_v2",
            )
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
