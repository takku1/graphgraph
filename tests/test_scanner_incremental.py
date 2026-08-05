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
from graphgraph.runtime.manifest import MANIFEST_VERSION, extractor_fingerprint
from graphgraph.scanner.frontends import (
    tree_sitter_available,
)
from graphgraph.storage.backends import save_graph_binary


class ManifestDeferralTest(unittest.TestCase):
    """The scanner must defer the manifest write so the lifecycle can order it
    after the graph commit (a failed graph write must not leave the manifest
    describing uncommitted nodes)."""

    def test_manifest_sink_defers_the_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "mod.py").write_text("def alpha():\n    return 1\n", encoding="utf-8")
            manifest_path = root / "graph.gg.manifest.json"

            sink: list = []
            scan_directory(
                root,
                depth="symbols",
                manifest_path=manifest_path,
                manifest_sink=sink,
            )
            # Deferred: nothing on disk yet, but the built manifest is captured.
            self.assertFalse(manifest_path.exists())
            self.assertEqual(len(sink), 1)
            manifest, captured_path = sink[0]
            self.assertEqual(captured_path, manifest_path)

            # The lifecycle would commit it only after the graph is saved.
            manifest.save(captured_path)
            self.assertTrue(manifest_path.exists())

    def test_default_still_writes_inline_for_non_lifecycle_callers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "mod.py").write_text("def beta():\n    return 2\n", encoding="utf-8")
            manifest_path = root / "graph.gg.manifest.json"
            scan_directory(root, depth="symbols", manifest_path=manifest_path)
            self.assertTrue(manifest_path.exists())


class IncrementalScannerTest(unittest.TestCase):
    """scanner/core.py incremental paths and runtime/manifest.py."""

    def test_single_file_update_preserves_other_files_external_calls(self) -> None:
        # Editing one JS file used to delete the external-dependency calls of
        # every *other* file. External nodes carry a synthetic locator
        # ("npm:http") rather than a repository path, so the update's
        # retain-if-owning-file-is-active test failed for all of them, and only
        # externals re-extracted from the touched file survived. On express that
        # collapsed 47 external nodes to 3 and about 65% of `calls` edges --
        # silently, on the tool's flagship edit-loop command.
        #
        # The gate is calls-edge parity between a full scan and a one-file
        # update over the same source.
        if not tree_sitter_available():
            self.skipTest("tree_sitter is not installed")
        util_lines = [
            "const path = require('path');",
            "function formatName(x) { return path.basename(String(x)); }",
            "module.exports = { formatName };",
        ]
        # `http` is required only here, by the file the update does NOT touch.
        router_lines = [
            "const http = require('http');",
            "const { formatName } = require('./util');",
            "function serve(u) { return http.createServer(function () { formatName(u); }); }",
            "module.exports = { serve };",
        ]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "util.js").write_text("\n".join(util_lines) + "\n", encoding="utf-8")
            (root / "router.js").write_text("\n".join(router_lines) + "\n", encoding="utf-8")
            graph_path = root / "graph.gg"
            manifest_path = root / "manifest.json"
            baseline = scan_directory(
                root,
                depth="symbols",
                frontend="tree_sitter",
                manifest_path=manifest_path,
                previous_graph_path=graph_path,
            )
            save_graph_binary(baseline, graph_path)

            def calls_edges(graph):
                return {
                    (edge.source, edge.target)
                    for edge in graph.edges
                    if edge.type == "calls"
                }

            before = calls_edges(baseline)
            self.assertTrue(
                any("http" in target for _, target in before),
                "fixture must produce an external http call for this gate to mean anything",
            )

            (root / "util.js").write_text(
                "\n".join(util_lines + ["// probe comment"]) + "\n",
                encoding="utf-8",
            )
            updated = update_paths(
                root,
                ["util.js"],
                depth="symbols",
                frontend="tree_sitter",
                manifest_path=manifest_path,
                previous_graph_path=graph_path,
            )
            self.assertEqual(
                before - calls_edges(updated),
                set(),
                "a one-file update dropped calls edges belonging to untouched files",
            )

    def test_identical_exact_path_update_is_graph_identity_noop(self) -> None:
        if not tree_sitter_available():
            self.skipTest("tree_sitter is not installed")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "main.rs"
            source.write_text(
                "fn special() {}\nfn run() { special(); }\n",
                encoding="utf-8",
            )
            graph_path = root / "graph.gg"
            manifest_path = root / "manifest.json"
            baseline = scan_directory(
                root,
                depth="symbols",
                frontend="tree_sitter",
                manifest_path=manifest_path,
            )
            save_graph(baseline, graph_path)

            updated = update_paths(
                root,
                ["main.rs"],
                depth="symbols",
                frontend="tree_sitter",
                previous_graph_path=graph_path,
                manifest_path=manifest_path,
            )

        self.assertEqual(updated.nodes, baseline.nodes)
        self.assertEqual(updated.edges, baseline.edges)
        self.assertEqual(updated.metadata, baseline.metadata)

    def test_validated_identical_update_reports_no_write(self) -> None:
        from graphgraph.services.native import (
            scan_validated_graph,
            update_paths_validated_graph,
        )
        from graphgraph.storage.delta import delta_sidecar_path

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "worker.py").write_text(
                "def worker():\n    return 1\n",
                encoding="utf-8",
            )
            graph_path = root / ".graphgraph" / "graph.gg"
            baseline = scan_validated_graph(
                directory=root,
                output_path=graph_path,
                depth="symbols",
                docs=False,
            )

            status = update_paths_validated_graph(
                directory=root,
                output_path=graph_path,
                paths=["worker.py"],
                depth="symbols",
                docs=False,
            )

            self.assertFalse(status.built)
            self.assertIsNotNone(status.validation)
            self.assertTrue(status.validation.ok)
            self.assertEqual(status.changed_paths, ())
            self.assertEqual(status.deleted_paths, ())
            self.assertEqual(status.graph.nodes, baseline.graph.nodes)
            self.assertEqual(status.graph.edges, baseline.graph.edges)
            self.assertFalse(delta_sidecar_path(graph_path).exists())

    def test_changed_rust_file_matches_clean_rebuild_with_derived_field_collision(self) -> None:
        if not tree_sitter_available():
            self.skipTest("tree_sitter is not installed")

        def build_baseline(root: Path, graph_path: Path, manifest_path: Path) -> None:
            (root / "main.rs").write_text(
                "fn special(value: u8) {}\n"
                "fn run(value: u8) { special(value); }\n",
                encoding="utf-8",
            )
            (root / "model.rs").write_text(
                "struct Options { special: u8 }\n",
                encoding="utf-8",
            )
            graph = scan_directory(
                root,
                depth="symbols",
                frontend="tree_sitter",
                manifest_path=manifest_path,
            )
            save_graph(graph, graph_path)

        def edit_main(root: Path) -> None:
            (root / "main.rs").write_text(
                "fn probe() {}\n"
                "fn special(value: u8) {}\n"
                "fn run(value: u8) { special(value); }\n",
                encoding="utf-8",
            )

        with tempfile.TemporaryDirectory() as tmp_full:
            root = Path(tmp_full)
            graph_path = root / "graph.gg"
            manifest_path = root / "manifest.json"
            build_baseline(root, graph_path, manifest_path)
            edit_main(root)
            clean = scan_directory(
                root,
                depth="symbols",
                frontend="tree_sitter",
                previous_graph_path=None,
                manifest_path=None,
            )
            clean_edges = sorted(clean.edges, key=repr)

        with tempfile.TemporaryDirectory() as tmp_incremental:
            root = Path(tmp_incremental)
            graph_path = root / "graph.gg"
            manifest_path = root / "manifest.json"
            build_baseline(root, graph_path, manifest_path)
            edit_main(root)
            incremental = update_paths(
                root,
                ["main.rs"],
                depth="symbols",
                frontend="tree_sitter",
                previous_graph_path=graph_path,
                manifest_path=manifest_path,
            )
            incremental_edges = sorted(incremental.edges, key=repr)

        self.assertEqual(incremental_edges, clean_edges)
        self.assertTrue(
            any(
                edge.source == "main_rs__run"
                and edge.target == "main_rs__special"
                and edge.type == "calls"
                for edge in incremental_edges
            )
        )

    def test_update_refuses_to_destroy_an_out_of_tree_graph(self) -> None:
        # SEV-1 regression: when the graph lives outside the scanned repo,
        # `update` found no manifest beside it, fell back to a full rescan of
        # the *directory argument* (which defaults to cwd, not the scanned
        # repo), and wrote the resulting empty graph over a valid one --
        # while reporting structural PASS, a successful "Repair", and exit 0.
        # Structural validity cannot catch this: an empty graph is
        # structurally perfect, so size-of-what-is-replaced is the only signal.
        from graphgraph.io import GraphShrinkRefused, load_any
        from graphgraph.services.native import (
            scan_validated_graph,
            update_paths_validated_graph,
        )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            repo.mkdir()
            # Large enough to clear the guard's small-graph threshold, below
            # which a shrink ratio carries no signal: a 3-node fixture halving
            # is routine, a real repo emptying is not.
            for index in range(12):
                (repo / f"mod{index}.py").write_text(
                    f"class Store{index}:\n"
                    f"    def persist(self):\n        return {index}\n"
                    f"    def load(self):\n        return {index}\n",
                    encoding="utf-8",
                )
            elsewhere = root / "elsewhere"
            elsewhere.mkdir()
            graph_path = elsewhere / "graph.gg"

            built = scan_validated_graph(
                directory=repo, output_path=graph_path, depth="symbols", docs=False
            )
            self.assertGreater(len(built.graph.nodes), 0)
            prior_nodes = len(built.graph.nodes)

            # The destructive call: rebuild root is `elsewhere`, which holds no
            # source at all, so the fallback rescan yields a near-empty graph.
            with self.assertRaises(GraphShrinkRefused):
                update_paths_validated_graph(
                    directory=elsewhere,
                    output_path=graph_path,
                    paths=[str(repo / "mod0.py")],
                    depth="symbols",
                    docs=False,
                )

            # The refusal must be a refusal, not a report: the graph on disk is
            # unchanged. Asserting node count rather than mere existence --
            # the original bug left a valid, correctly-formatted, empty file.
            self.assertEqual(len(load_any(graph_path).nodes), prior_nodes)

    def test_update_force_allows_an_intentional_shrink(self) -> None:
        # The guard must not become a wall: an operator who means it keeps a
        # way through, otherwise legitimate rebuilds get stuck behind it.
        from graphgraph.services.native import (
            scan_validated_graph,
            update_paths_validated_graph,
        )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            repo.mkdir()
            # Large enough to clear the guard's small-graph threshold, below
            # which a shrink ratio carries no signal: a 3-node fixture halving
            # is routine, a real repo emptying is not.
            for index in range(12):
                (repo / f"mod{index}.py").write_text(
                    f"class Store{index}:\n"
                    f"    def persist(self):\n        return {index}\n"
                    f"    def load(self):\n        return {index}\n",
                    encoding="utf-8",
                )
            elsewhere = root / "elsewhere"
            elsewhere.mkdir()
            graph_path = elsewhere / "graph.gg"

            scan_validated_graph(
                directory=repo, output_path=graph_path, depth="symbols", docs=False
            )
            status = update_paths_validated_graph(
                directory=elsewhere,
                output_path=graph_path,
                paths=[str(repo / "mod0.py")],
                depth="symbols",
                docs=False,
                force=True,
            )
            self.assertTrue(status.repaired)

    def test_validated_updates_compose_through_delta_sidecar(self) -> None:
        from graphgraph.io import load_any
        from graphgraph.services.native import (
            scan_validated_graph,
            update_paths_validated_graph,
        )
        from graphgraph.storage.delta import delta_sidecar_path

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for index in range(80):
                (root / f"mod{index}.py").write_text(
                    f"def value_{index}():\n    return {index}\n",
                    encoding="utf-8",
                )
            graph_path = root / ".graphgraph" / "graph.gg"
            scan_validated_graph(
                directory=root,
                output_path=graph_path,
                depth="symbols",
                frontend="regex",
                docs=False,
            )

            target = root / "mod0.py"
            target.write_text(
                "def value_0():\n    return 100\n\ndef added_once():\n    return value_0()\n",
                encoding="utf-8",
            )
            first = update_paths_validated_graph(
                directory=root,
                output_path=graph_path,
                paths=["mod0.py"],
                depth="symbols",
                frontend="regex",
                docs=False,
            )
            self.assertTrue(delta_sidecar_path(graph_path).exists())
            self.assertTrue(any(node.label == "added_once" for node in first.graph.nodes.values()))

            target.write_text(
                "def value_0():\n    return 200\n\ndef added_twice():\n    return value_0()\n",
                encoding="utf-8",
            )
            second = update_paths_validated_graph(
                directory=root,
                output_path=graph_path,
                paths=["mod0.py"],
                depth="symbols",
                frontend="regex",
                docs=False,
            )
            labels = {node.label for node in second.graph.nodes.values()}
            persisted_labels = {node.label for node in load_any(graph_path).nodes.values()}
            self.assertIn("added_twice", labels)
            self.assertNotIn("added_once", labels)
            self.assertEqual(labels, persisted_labels)

    def test_remove_of_in_tree_untracked_path_is_idempotent(self) -> None:
        # GATE 28: the wrong-root remove guard must not swallow legitimate
        # no-ops. Removing an in-tree path that simply is not in the graph
        # (excluded, a typo, or already deleted) was formerly idempotent
        # success; erroring on it broke batch cleanups that included one such
        # path. Only a path resolving OUTSIDE the scanned tree is the mistake.
        from graphgraph.services.native import (
            remove_paths_validated_graph,
            scan_validated_graph,
        )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "kept.py").write_text("def kept():\n    return 1\n", encoding="utf-8")
            graph_path = root / ".graphgraph" / "graph.gg"
            built = scan_validated_graph(
                directory=root, output_path=graph_path, depth="symbols", docs=False
            )
            prior = len(built.graph.nodes)

            # An in-tree path the graph never contained: no error, no change.
            status = remove_paths_validated_graph(
                directory=root,
                output_path=graph_path,
                paths=["never_scanned.py"],
                depth="symbols",
                docs=False,
            )
            self.assertEqual(len(status.graph.nodes), prior)

    def test_remove_from_wrong_root_still_errors(self) -> None:
        # The other half: a path resolving entirely outside the scanned tree is
        # the wrong-root mistake and must still surface, not silently no-op.
        from graphgraph.io import RemovalMatchedNothing
        from graphgraph.services.native import (
            remove_paths_validated_graph,
            scan_validated_graph,
        )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            repo.mkdir()
            (repo / "kept.py").write_text("def kept():\n    return 1\n", encoding="utf-8")
            elsewhere = root / "elsewhere"
            elsewhere.mkdir()
            graph_path = repo / ".graphgraph" / "graph.gg"
            scan_validated_graph(
                directory=repo, output_path=graph_path, depth="symbols", docs=False
            )
            with self.assertRaises(RemovalMatchedNothing):
                remove_paths_validated_graph(
                    directory=elsewhere,  # wrong root
                    output_path=graph_path,
                    paths=[str(repo / "kept.py")],  # outside `elsewhere`
                    depth="symbols",
                    docs=False,
                )

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
            self.assertEqual(
                json.loads(graph.metadata["member_calls_global_by_language"])[
                    "rust"
                ]["resolved"],
                1,
            )

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
        self.assertEqual(
            json.loads(updated.metadata["member_calls_global_by_language"])[
                "rust"
            ]["resolved"],
            1,
        )
        self.assertEqual(
            json.loads(updated.metadata["member_calls_last_update_by_language"]),
            {},
        )

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
            full = scan_directory(root, depth="symbols", previous_graph_path=None, manifest_path=None)
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

    def test_update_paths_rebinds_referrers_when_a_definition_file_is_renamed(self) -> None:
        # Renaming core.py -> engine.py used to silently drop stable.py's call
        # edge: stable.py was restored verbatim from the manifest, so its edge
        # still pointed at core.py's now-deleted node instead of rebinding to
        # the definition's new home. A clean rescan kept the caller, so the
        # splice diverged from a rebuild (GG10-LC-008).
        core = "def normalize_value(x):\n    return x + 1\n\ndef core_entry():\n    return normalize_value(1)\n"
        stable = "from core import normalize_value\n\n\ndef stable_entry():\n    return normalize_value(3)\n"

        def build_baseline(root: Path, graph_path: Path, manifest_path: Path) -> None:
            (root / "core.py").write_text(core, encoding="utf-8")
            (root / "stable.py").write_text(stable, encoding="utf-8")
            graph = scan_directory(
                root, depth="symbols", previous_graph_path=None, manifest_path=manifest_path
            )
            save_graph(graph, graph_path)

        def apply_rename(root: Path) -> None:
            (root / "engine.py").write_text(core, encoding="utf-8")
            (root / "core.py").unlink()

        with tempfile.TemporaryDirectory() as tmp_full:
            root = Path(tmp_full)
            graph_path = root / ".graphgraph" / "graph.json"
            manifest_path = root / ".graphgraph" / "manifest.json"
            build_baseline(root, graph_path, manifest_path)
            apply_rename(root)
            full = scan_directory(
                root, depth="symbols", previous_graph_path=graph_path, manifest_path=manifest_path
            )
            full_nodes = sorted((n.label, n.path) for n in full.nodes.values())
            full_edges = sorted((e.source, e.target, e.type) for e in full.edges)

        with tempfile.TemporaryDirectory() as tmp_targeted:
            root = Path(tmp_targeted)
            graph_path = root / ".graphgraph" / "graph.json"
            manifest_path = root / ".graphgraph" / "manifest.json"
            build_baseline(root, graph_path, manifest_path)
            apply_rename(root)
            targeted = update_paths(
                root,
                ["engine.py"],
                deleted_paths=["core.py"],
                depth="symbols",
                previous_graph_path=graph_path,
                manifest_path=manifest_path,
            )
            targeted_nodes = sorted((n.label, n.path) for n in targeted.nodes.values())
            targeted_edges = sorted((e.source, e.target, e.type) for e in targeted.edges)

        self.assertEqual(full_nodes, targeted_nodes)
        self.assertEqual(full_edges, targeted_edges)
        # The untouched referrer must survive, not just match an empty rebuild.
        self.assertIn("stable_entry", [label for label, _path in targeted_nodes])
        self.assertTrue(
            any(src.endswith("stable_entry") and typ == "calls" for src, _dst, typ in targeted_edges),
            targeted_edges,
        )

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
            raw["extractor_fingerprint"] = "obsolete-extractor"
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
            rebuilt_manifest = json.loads(
                manifest_path.read_text(encoding="utf-8")
            )
            self.assertEqual(
                rebuilt_manifest["extractor_fingerprint"],
                extractor_fingerprint(),
            )
            self.assertNotEqual(rebuilt_manifest["updated_at"], "")

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
