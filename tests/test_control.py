from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from benchmarks.context_graph.control_receipt_benchmark import evaluate_candidates
from graphgraph.packets import estimate_tokens
from graphgraph.services.control import (
    ControlReceipt,
    choose_next_action,
    parse_control_ir,
    render_control_ir,
)
from graphgraph.services.native import render_native_context


class ControlReceiptTest(unittest.TestCase):
    def test_semantic_control_ir_round_trips_without_a_codebook(self) -> None:
        receipt = ControlReceipt(
            operation="reverse_lookup",
            state="answerable",
            next_action="answer",
            anchor="exact_fast_path",
            hops=1,
            direction="in",
            node_budget=12,
            nodes=7,
            edges=5,
            packet="gg",
            packet_tokens=214,
            gates=(
                ("fresh", True),
                ("route", True),
                ("anchor", True),
                ("evidence", True),
                ("semantic", True),
                ("packet", True),
            ),
        )

        encoded = render_control_ir(receipt)

        self.assertEqual(parse_control_ir(encoded), receipt)
        self.assertEqual(encoded, render_control_ir(parse_control_ir(encoded)))
        self.assertIn("op=reverse_lookup", encoded)
        self.assertIn("gates=fresh:+", encoded)

    def test_next_action_is_a_deterministic_gate_tree(self) -> None:
        passing = {
            "fresh": True,
            "route": True,
            "anchor": True,
            "evidence": True,
            "semantic": True,
            "packet": True,
        }
        cases = (
            ("answerable", passing, "answer"),
            ("answerable", {**passing, "fresh": False}, "refresh"),
            ("answerable", {**passing, "packet": False}, "repair"),
            ("answerable", {**passing, "semantic": False}, "repair"),
            ("answerable", {**passing, "route": False}, "retry_narrow"),
            ("incomplete", {**passing, "evidence": False}, "retry_narrow"),
            ("unanswerable", {**passing, "anchor": False}, "abstain"),
        )
        for state, gates, expected in cases:
            with self.subTest(state=state, expected=expected):
                self.assertEqual(choose_next_action(state, gates), expected)

    def test_native_json_exposes_control_and_packet_cost_without_tokenizer_glue(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "app.py").write_text(
                "def normalize_rust():\n    return True\n",
                encoding="utf-8",
            )
            rendered, _status = render_native_context(
                query="where is normalize_rust",
                directory=root,
                graph_path=root / ".graphgraph" / "graph.json",
                query_class="direct_lookup",
                json_output=True,
                max_nodes=20,
            )

        payload = json.loads(rendered)
        control = parse_control_ir(payload["control"])
        packet = payload["packet"]
        metrics = payload["metrics"]["packet"]

        self.assertEqual(control.operation, "direct_lookup")
        self.assertEqual(control.next_action, "answer")
        self.assertEqual(control.packet_tokens, estimate_tokens(packet))
        self.assertEqual(metrics["proxy_tokens"], control.packet_tokens)
        self.assertEqual(metrics["characters"], len(packet))

    def test_compact_json_keeps_control_and_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "app.py").write_text(
                "def normalize_rust():\n    return True\n",
                encoding="utf-8",
            )
            rendered, _status = render_native_context(
                query="where is normalize_rust",
                directory=root,
                graph_path=root / ".graphgraph" / "graph.json",
                query_class="direct_lookup",
                json_output=True,
                json_details=False,
                max_nodes=20,
            )

        payload = json.loads(rendered)
        self.assertNotIn("packet", payload)
        self.assertEqual(parse_control_ir(payload["control"]).next_action, "answer")
        self.assertGreater(payload["metrics"]["packet"]["proxy_tokens"], 0)

    def test_native_json_reports_persistent_response_cache_hit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "app.py").write_text(
                "def normalize_rust():\n    return True\n",
                encoding="utf-8",
            )
            arguments = {
                "query": "where is normalize_rust",
                "directory": root,
                "graph_path": root / ".graphgraph" / "graph.json",
                "query_class": "direct_lookup",
                "json_output": True,
                "max_nodes": 20,
            }

            first, _status = render_native_context(**arguments)
            second, _status = render_native_context(**arguments)

        self.assertEqual(json.loads(first)["workflow"]["cache"]["state"], "miss")
        self.assertEqual(json.loads(second)["workflow"]["cache"]["state"], "hit")

    def test_session_signature_excludes_the_tools_own_artifacts(self) -> None:
        # The self-invalidating-cache bug: in a repo that does not gitignore
        # .graphgraph/, `git ls-files --others` lists kv_cache.json as an
        # untracked worktree file. It was folded into the cache key with its
        # mtime, so writing the cache changed the key keyed on it and the next
        # query always missed -- a 0% hit rate visible only on scanned external
        # repos. The signature must ignore the tool's own outputs while still
        # reacting to real source edits.
        from unittest.mock import patch

        from graphgraph.retrieval import git_utils
        from graphgraph.services import context as ctxmod

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "real.py").write_text("x = 1\n", encoding="utf-8")
            (root / ".graphgraph").mkdir()
            (root / ".graphgraph" / "kv_cache.json").write_text("{}", encoding="utf-8")
            (root / "graph.gg").write_text("gg\n", encoding="utf-8")
            (root / "semantic.json").write_text("{}", encoding="utf-8")

            worktree = (
                (
                    "real.py",
                    ".graphgraph/kv_cache.json",
                    "graph.gg",
                    "semantic.json",
                ),
                (),
            )
            with patch.object(git_utils, "get_git_worktree_paths", return_value=worktree):
                sig = ctxmod._session_signature(root)

        tracked = {entry[0] for entry in sig}
        self.assertIn("real.py", tracked)
        self.assertNotIn(".graphgraph/kv_cache.json", tracked)
        self.assertNotIn("graph.gg", tracked)
        self.assertNotIn("semantic.json", tracked)

    def test_is_tool_artifact_classification(self) -> None:
        from graphgraph.services.context import _is_tool_artifact

        for artifact in (
            ".graphgraph/kv_cache.json",
            ".graphgraph/graph.gg",
            "kv_cache.json",
            "semantic.json",
            "activation_state.json",
            "graph.gg",
            "graph.gg.manifest.json",
            "sub/dir/.graphgraph/anything.json",
        ):
            self.assertTrue(_is_tool_artifact(artifact), artifact)
        for real in ("src/app.py", "README.md", "semantic_test.py", "graph_builder.py"):
            self.assertFalse(_is_tool_artifact(real), real)

    def test_query_cache_hits_when_graphgraph_dir_is_not_gitignored(self) -> None:
        # The end-to-end guard, through render_query_context (the `graphgraph
        # query` path where the self-invalidating-cache bug actually lived), in
        # a real git repo whose .gitignore does NOT cover .graphgraph/ -- the
        # reviewer's external-repo scenario. The scan writes .graphgraph/ into
        # the worktree; `git ls-files --others` then lists kv_cache.json, and
        # before the fix its per-run mtime busted the key every time.
        import subprocess

        from graphgraph.services.context import render_query_context
        from graphgraph.services.native import scan_validated_graph

        def git(*args, cwd):
            subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "app.py").write_text(
                "def normalize_rust():\n    return True\n", encoding="utf-8"
            )
            try:
                git("init", cwd=root)
                git("config", "user.email", "t@t", cwd=root)
                git("config", "user.name", "t", cwd=root)
                git("add", "-A", cwd=root)
                git("commit", "-m", "init", cwd=root)
            except (subprocess.CalledProcessError, FileNotFoundError):
                self.skipTest("git unavailable")

            graph_path = root / ".graphgraph" / "graph.gg"
            scan_validated_graph(directory=root, output_path=graph_path, docs=False)

            kwargs = dict(
                query="where is normalize_rust",
                query_class="direct_lookup",
                graph_path=graph_path,
                cache_namespace="cli_query",
                show_anchors=True,
                json_anchors=True,
            )
            # git_utils caches worktree state per-process; clear it so the
            # second call re-derives the signature exactly as a fresh process
            # would, which is where the bug manifested.
            from graphgraph.retrieval import git_utils

            git_utils._git_path_cache.clear()
            first = render_query_context(**kwargs)
            git_utils._git_path_cache.clear()
            second = render_query_context(**kwargs)

        self.assertEqual(json.loads(first)["workflow"]["cache"]["state"], "miss")
        self.assertEqual(json.loads(second)["workflow"]["cache"]["state"], "hit")

    def test_benchmark_promotes_smallest_lossless_self_contained_candidate(self) -> None:
        report = evaluate_candidates()
        candidates = {row["candidate"]: row for row in report["candidates"]}

        self.assertEqual(report["winner"], "semantic_ir")
        self.assertTrue(candidates["semantic_ir"]["lossless"])
        self.assertTrue(candidates["semantic_ir"]["self_contained"])
        self.assertLess(
            candidates["semantic_ir"]["mean_proxy_tokens"],
            candidates["flat_json"]["mean_proxy_tokens"],
        )
        self.assertFalse(candidates["opcode_ir"]["self_contained"])


if __name__ == "__main__":
    unittest.main()
