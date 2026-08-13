from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from graphgraph import (
    scan_directory,
)
from graphgraph.concepts.terms import canonical_concept_label, concept_id, term_key


class ScannerTest(unittest.TestCase):
    """scanner/core.py and scanner/files.py: collection, skipping, budgets, orchestration."""

    def test_terms_normalize_concepts_consistently(self) -> None:
        self.assertEqual(term_key("Token Store"), "token store")
        self.assertEqual(term_key("token-store"), "token store")
        self.assertEqual(term_key("TokenStore"), "token store")
        self.assertEqual(term_key("2×2 mixed Nash"), "2x2 mixed nash")
        self.assertEqual(concept_id("Token Store"), "concept_token_store")
        self.assertEqual(canonical_concept_label("token store"), "Token Store")

    def test_every_definition_gets_a_node_even_when_names_collide(self) -> None:
        """Gate: graph symbol nodes == AST definition count.

        Node ids qualify a method by its owning type, which separates `A.run`
        from `B.run` but not a `@property def x` from its `@x.setter def x`,
        nor a `helper` nested in two different functions. The node builder
        keeps the first id it sees, so those definitions were dropped
        entirely: no node, no `calls` edges, never in a blast radius, and a
        `callers == 0` dead-code query wrong for every property. Measured on a
        real Flask checkout at 7.9% of production definitions -- including all
        seven of its property setters.
        """
        import ast

        source = (
            "class Config:\n"
            "    @property\n"
            "    def debug(self):\n"
            "        return self._debug\n"
            "\n"
            "    @debug.setter\n"
            "    def debug(self, value):\n"
            "        self._debug = value\n"
            "\n"
            "def outer_one():\n"
            "    def helper():\n"
            "        return 1\n"
            "    return helper()\n"
            "\n"
            "def outer_two():\n"
            "    def helper():\n"
            "        return 2\n"
            "    return helper()\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "mod.py").write_text(source, encoding="utf-8")
            graph = scan_directory(root, depth="symbols")

            expected = sum(
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                for node in ast.walk(ast.parse(source))
            )
            symbols = [n for n in graph.nodes.values() if n.kind in {"function", "method", "class"}]
            self.assertEqual(
                len(symbols),
                expected,
                f"{expected - len(symbols)} definition(s) have no node: "
                f"{sorted(n.id for n in symbols)}",
            )

            # The surviving ids must stay distinct, and the *first* definition
            # of each name must keep its bare id so existing graphs, caches,
            # and packet node references are not churned by this fix.
            self.assertEqual(len(symbols), len({n.id for n in symbols}))
            ids = {n.id for n in symbols}
            self.assertTrue(any(i.endswith("__Config__debug") for i in ids), ids)
            self.assertTrue(any(i.endswith("__helper") for i in ids), ids)
            self.assertEqual(sum(1 for i in ids if "@L" in i), 2, ids)

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

    def test_collect_files_skips_generated_dot_scratch_by_default(self) -> None:
        from graphgraph.scanner.files import collect_files

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scratch = root / ".scratch" / "eval-run"
            scratch.mkdir(parents=True)
            (scratch / "graph.gg").write_text("generated", encoding="utf-8")
            (scratch / "receipt.json").write_text("{}", encoding="utf-8")
            (root / "app.py").write_text("", encoding="utf-8")

            result = collect_files(root, 100)
            files = {path.relative_to(root).as_posix() for path in result.files}

            self.assertEqual(files, {"app.py"})
            self.assertEqual(result.default_pruned_dirs, (".scratch",))

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

    def test_scan_directory_no_communities_param(self) -> None:
        """scan_directory must not accept a communities keyword argument."""
        import inspect

        from graphgraph.scanner import scan_directory

        sig = inspect.signature(scan_directory)
        self.assertNotIn("communities", sig.parameters)
