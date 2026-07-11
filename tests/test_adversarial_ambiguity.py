"""Regression coverage for adversarial anchor disambiguation (roadmap P0 #3).

Locks in the behaviour probed by
benchmarks/context_graph/adversarial_ambiguity_benchmark.py: duplicate symbols,
generated-vs-handwritten sources, re-export chains (including a cycle),
overloaded methods, and mixed documentation/code anchors must each resolve to
the query-correct node, not whatever graph shape or ordering happens to yield.
"""

from __future__ import annotations

import unittest

from graphgraph.retrieval.search import search_nodes


class AdversarialAmbiguityTest(unittest.TestCase):
    def _cases(self):
        from benchmarks.context_graph.adversarial_ambiguity_benchmark import build_cases

        return build_cases()

    def test_every_adversarial_case_resolves_to_expected_anchor(self) -> None:
        failures = []
        for case in self._cases():
            matches = search_nodes(
                case.graph, case.query, limit=5,
                doc_intensity=case.doc_intensity, personalize=True,
            )
            top = matches[0].node.id if matches else "(none)"
            if top != case.expected:
                failures.append(f"{case.name}: expected {case.expected}, got {top}")
        self.assertEqual(failures, [], "\n".join(failures))

    def test_collision_and_reexport_wins_are_decisive_not_ties(self) -> None:
        # A correct top-1 that only wins by a rounding margin is fragile. Require
        # a real separation so these stay robust as scoring evolves.
        wanted = {"many_file_collision_with_scope", "cyclic_reexport_chain", "overload_by_signature"}
        checked = 0
        for case in self._cases():
            if case.name not in wanted:
                continue
            checked += 1
            matches = search_nodes(case.graph, case.query, limit=3, personalize=True)
            self.assertGreaterEqual(len(matches), 2, case.name)
            self.assertEqual(matches[0].node.id, case.expected, case.name)
            margin = matches[0].score - matches[1].score
            self.assertGreater(margin, 2.0, f"{case.name} margin too thin: {margin:.2f}")
        self.assertEqual(checked, len(wanted))


if __name__ == "__main__":
    unittest.main()
