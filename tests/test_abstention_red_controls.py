"""T-A03 / OW-AC-04: abstention & confidence red controls.

Locks in the gate from the wayfinder map: an unanswerable query must abstain
at confidence <=0.2 and a packet of <=50 real tokens. It also locks in the
2026-08-04 taxonomy split the map calls out explicitly -- a query whose
required facets are covered only by documentation (no code implements it)
must report ``incomplete``, not ``unanswerable``, even though both abstain.
Neither branch had a dedicated regression test before this file: the
"incomplete"/mention_fulfilled path in retrieve_context was reachable only
through ad hoc exercise, not asserted on directly.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from graphgraph.graph.core import Graph, Node
from graphgraph.io import save_graph
from graphgraph.packets import estimate_tokens
from graphgraph.retrieval import retrieve_context
from graphgraph.services import render_query_context


def _requiredness_graph() -> Graph:
    """A graph large enough for the IDF-based facet-requiredness gate to fire.

    ``_facet_is_required`` scores a term's specificity as inverse document
    frequency over the *whole* graph. On a 2-node graph, a term that appears
    in exactly one node already looks "common" (df=1 of 2), so it never
    clears the requiredness floor and the preflight veto never engages. A
    double-digit node count is the minimum for a term confined to one node to
    register as genuinely rare.
    """
    nodes = {
        "IMPL": Node("IMPL", "PaymentProcessor", "class", "src/app.py", summary="Processes payments."),
        "DOC": Node(
            "DOC",
            "Rate limiting",
            "section",
            "docs/guide.md",
            summary="The rate limiting quota enforcement subsystem throttles requests per client.",
        ),
    }
    for i in range(10):
        nodes[f"FILLER{i}"] = Node(
            f"FILLER{i}", f"helper_{i}", "function", "src/helpers.py", summary=f"Helper utility number {i}."
        )
    return Graph(nodes=nodes)


class AbstentionRedControlTest(unittest.TestCase):
    def test_unanswerable_query_abstains_at_low_confidence_and_low_token_cost(self) -> None:
        # OW-AC-04 gate, verbatim: "unanswerable => confidence <=0.2 and
        # <=50 real tokens". Nothing in the graph -- code or docs -- covers
        # this facet.
        graph = _requiredness_graph()
        result = retrieve_context(graph, "quantum teleportation relay array", "direct_lookup", 2)
        answerability = result.metadata["answerability"]
        self.assertEqual(answerability["status"], "unanswerable")
        self.assertTrue(answerability["abstained"])
        self.assertLessEqual(answerability["confidence"], 0.2)
        self.assertEqual(result.nodes, set())

        with tempfile.TemporaryDirectory() as tmp:
            graph_path = Path(tmp) / "graph.gg"
            save_graph(graph, graph_path)
            packet = render_query_context(
                query="quantum teleportation relay array",
                query_class="direct_lookup",
                graph_path=graph_path,
            )
        self.assertLessEqual(estimate_tokens(packet), 50)

    def test_doc_only_coverage_reports_incomplete_not_unanswerable(self) -> None:
        # The 2026-08-04 taxonomy change this ticket calls out: a facet the
        # corpus documents but no code implements is a weaker answer than
        # "answerable", but a stronger one than "this does not exist" -- it
        # must abstain as `incomplete`, distinctly from a true `unanswerable`
        # miss, and still stay under the unanswerable confidence ceiling.
        graph = _requiredness_graph()
        result = retrieve_context(
            graph, "rate limiting quota enforcement subsystem", "direct_lookup", 2
        )
        answerability = result.metadata["answerability"]
        self.assertEqual(answerability["status"], "incomplete")
        self.assertTrue(answerability["abstained"])
        self.assertLessEqual(answerability["confidence"], 0.2)
        self.assertEqual(result.nodes, set())


if __name__ == "__main__":
    unittest.main()
