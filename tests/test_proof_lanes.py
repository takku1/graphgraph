from __future__ import annotations

import unittest
from pathlib import Path

from graphgraph.acceptance.proof_lanes import (
    caller_labels,
    lexical_mention_files,
    local_conceptual_receipt,
    self_eval_receipt,
)
from graphgraph.io import find_graph_path


class ProofLaneTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        try:
            cls.graph_path = find_graph_path(Path("."))
        except FileNotFoundError:
            raise unittest.SkipTest("no graph built for this repository") from None

    def test_exact_self_eval_is_perfect_and_the_red_task_is_zero(self) -> None:
        receipt = self_eval_receipt(self.graph_path)
        self.assertEqual(receipt["red_recall"], 0.0)
        self.assertEqual(receipt["green_min"], 1.0)

    def test_graph_callers_exclude_the_definition_that_lexical_search_hits(self) -> None:
        mentions = lexical_mention_files(Path("src"), "select_symbols")
        callers = caller_labels(self.graph_path, "select_symbols", include_tests=False)
        self.assertIn("cmd_select", callers)
        self.assertIn("handle_select_symbols", callers)
        self.assertTrue(any(path.endswith("retrieval/predicates.py") for path in mentions))
        from graphgraph.acceptance.proof_lanes import caller_rows

        caller_paths = [str(row.get("path") or "") for row in caller_rows(self.graph_path, "select_symbols")]
        self.assertFalse(any(path.endswith("retrieval/predicates.py") for path in caller_paths))

    def test_local_conceptual_recall_is_measured_against_the_ow_ac_03_gate(self) -> None:
        receipt = local_conceptual_receipt(self.graph_path)
        self.assertEqual(len(receipt["recalls"]), 3)
        self.assertGreaterEqual(min(receipt["recalls"]), 0.0)
        self.assertIn("held-out", receipt["claim_boundary"].lower())
        # This-repo probes can meet 0.80; that does not license the held-out panel.
