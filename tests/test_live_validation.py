from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from graphgraph import Edge, Graph, Node
from graphgraph.acceptance.live_validation import compare_active_graph, run_tests
from graphgraph.io import save_graph


class LiveValidationTest(unittest.TestCase):
    def test_successful_cargo_command_selecting_zero_tests_fails_verification(self) -> None:
        output = (
            "running 0 tests\n\n"
            "test result: ok. 0 passed; 0 failed; 0 ignored; 0 measured; 36 filtered out\n"
        )
        with tempfile.TemporaryDirectory() as tmp, patch(
            "graphgraph.acceptance.live_validation.subprocess.run",
            return_value=subprocess.CompletedProcess(["cargo", "test"], 0, output),
        ):
            receipt = run_tests(
                Path(tmp),
                command_text="cargo test -p locus-frontends source::normalize::tests --lib",
            )

        self.assertFalse(receipt["ok"])
        self.assertEqual(receipt["status"], "failed")
        self.assertEqual(receipt["tests"], 0)
        self.assertEqual(
            receipt["test_counts"],
            {"passed": 0, "failed": 0, "ignored": 0},
        )
        self.assertGreaterEqual(receipt["duration_ms"], 0)
        self.assertEqual(receipt["reason"], "test command selected zero tests")

    def test_cargo_command_selecting_one_test_passes_verification(self) -> None:
        output = (
            "running 1 test\n"
            "test source::normalize::normalize_tests::rust_logical_ops_lower_to_bitwise_at_binary_positions ... ok\n\n"
            "test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 35 filtered out\n"
        )
        with tempfile.TemporaryDirectory() as tmp, patch(
            "graphgraph.acceptance.live_validation.subprocess.run",
            return_value=subprocess.CompletedProcess(["cargo", "test"], 0, output),
        ):
            receipt = run_tests(
                Path(tmp),
                command_text=(
                    "cargo test -p locus-frontends "
                    "rust_logical_ops_lower_to_bitwise_at_binary_positions --lib"
                ),
            )

        self.assertTrue(receipt["ok"])
        self.assertEqual(receipt["status"], "passed")
        self.assertEqual(receipt["tests"], 1)
        self.assertEqual(
            receipt["test_counts"],
            {"passed": 1, "failed": 0, "ignored": 0},
        )
        self.assertEqual(receipt["returncode"], 0)
        self.assertGreaterEqual(receipt["duration_ms"], 0)

    def test_active_graph_comparison_reports_categorized_identity_delta(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            active_path = repo / ".graphgraph" / "graph.gg"
            live_path = repo / ".graphgraph" / "skill-validation" / "live.graph.json"
            active_path.parent.mkdir(parents=True)
            live_path.parent.mkdir(parents=True)
            active = Graph(
                nodes={
                    "CODE": Node("CODE", "run", "function", "src/run.py"),
                    "OLD_DOC": Node("OLD_DOC", "Old", "paragraph", "docs/old.md"),
                },
                edges=[Edge("OLD_DOC", "CODE", "explains")],
            )
            live = Graph(
                nodes={
                    "CODE": Node("CODE", "run", "function", "src/run.py"),
                    "NEW_DOC": Node("NEW_DOC", "New", "paragraph", "docs/new.md"),
                },
                edges=[Edge("CODE", "NEW_DOC", "references")],
            )
            save_graph(active, active_path)

            comparison = compare_active_graph(repo, live, live_path)

        self.assertEqual(comparison["status"], "compared")
        self.assertFalse(comparison["comparable"])
        self.assertEqual(comparison["delta"]["added_nodes"], 1)
        self.assertEqual(comparison["delta"]["removed_nodes"], 1)
        self.assertEqual(
            comparison["delta"]["added_nodes_by_category"],
            {"documentation": 1},
        )
        self.assertEqual(
            comparison["delta"]["removed_nodes_by_category"],
            {"documentation": 1},
        )
        self.assertEqual(
            comparison["delta"]["added_edges_by_relation"],
            {"references": 1},
        )
        self.assertEqual(
            comparison["delta"]["removed_edges_by_relation"],
            {"explains": 1},
        )
