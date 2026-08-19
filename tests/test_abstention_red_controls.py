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
from graphgraph.services.compiler_driver import CompilerDriver, DriverRequest


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
        self.assertFalse(answerability.get("minimum_evidence"))
        self.assertFalse(answerability.get("neighborhood_complete"))

        with tempfile.TemporaryDirectory() as tmp:
            graph_path = Path(tmp) / "graph.gg"
            save_graph(graph, graph_path)
            packet, _status = CompilerDriver().compile(DriverRequest(
                query="quantum teleportation relay array",
                query_class="direct_lookup",
                graph_path=graph_path,
            ))
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

    def test_scattered_facet_terms_do_not_abstain_as_if_absent(self) -> None:
        # T-B07. The feasibility preflight used to prove absence by asking
        # whether any single node matched every term of a facet at once. A
        # paraphrased question never satisfies that even when the answer is
        # present, because the words are spread across nodes -- so the packet
        # came back empty for a question the graph could answer.
        #
        # Here every term of "queued payment settlement record" exists in the
        # graph -- "queued" only in WorkQueue, the rest only in
        # PaymentProcessor -- so no one node carries them all. That is not
        # evidence of absence and must not abstain.
        graph = Graph(
            nodes={
                "IMPL": Node(
                    "IMPL", "PaymentProcessor", "class", "src/app.py",
                    summary="Handles payment settlement for each record.",
                ),
                "QUEUE": Node(
                    "QUEUE", "WorkQueue", "class", "src/queue.py",
                    summary="Holds queued work items awaiting processing.",
                ),
            },
        )
        for i in range(10):
            graph.nodes[f"F{i}"] = Node(f"F{i}", f"helper_{i}", "function", "src/helpers.py",
                                        summary=f"Utility number {i}.")
        result = retrieve_context(graph, "queued payment settlement record", "direct_lookup", 2)
        self.assertFalse(result.metadata["answerability"]["abstained"])
        self.assertTrue(result.nodes, "a scattered-term query must still return evidence")

    def test_a_term_absent_from_the_whole_corpus_still_abstains(self) -> None:
        # The other half of the same rule, and the reason the loosening is
        # safe: a term occurring nowhere in the corpus is a real proof of
        # absence. This is the shape of every red control in
        # eval/retrieval-v1 ("Kubernetes gRPC service-mesh retry
        # coordinator"), and it must keep failing closed.
        graph = _requiredness_graph()
        result = retrieve_context(
            graph, "kubernetes grpc servicemesh retry coordinator", "direct_lookup", 2
        )
        self.assertTrue(result.metadata["answerability"]["abstained"])
        self.assertEqual(result.nodes, set())

    def test_ungrounded_paraphrase_collision_abstains_and_stays_cheap(self) -> None:
        # Tokens collide with generic hubs (context/packet/field) but no node
        # carries a distinctive summary. That is a dirty miss: previously it
        # shipped an ~1800-token "answerable" packet.
        graph = _requiredness_graph()
        # A plateau of generic hubs: production dirty misses have low
        # top-mass, not a single 30-point collision.
        for index in range(6):
            graph.nodes[f"HUB{index}"] = Node(
                f"HUB{index}",
                f"context_packet_{index}",
                "function",
                f"src/packet_{index}.py",
                summary="L1 pack a context packet for the machine client.",
            )
        query = (
            "How is a one-hop caller list encoded for a machine "
            "without a context packet?"
        )
        result = retrieve_context(graph, query, "subsystem_summary", 2)
        answerability = result.metadata["answerability"]
        self.assertEqual(answerability["status"], "unanswerable")
        self.assertTrue(answerability["abstained"])
        self.assertLessEqual(answerability["confidence"], 0.2)
        self.assertEqual(result.nodes, set())
        self.assertEqual(result.starts, ())

        with tempfile.TemporaryDirectory() as tmp:
            graph_path = Path(tmp) / "graph.gg"
            save_graph(graph, graph_path)
            packet, _status = CompilerDriver().compile(DriverRequest(
                query=query,
                query_class="subsystem_summary",
                graph_path=graph_path,
            ))
        self.assertLessEqual(estimate_tokens(packet), 50)

    def test_distinctive_summary_paraphrase_does_not_abstain(self) -> None:
        # The OW-AC-03 increment: two distinctive summary terms, one of them
        # a hyphenated compound, is grounded evidence. Emptying that packet
        # would undo the local conceptual hit.
        graph = _requiredness_graph()
        graph.nodes["TARGET"] = Node(
            "TARGET",
            "emit_capability",
            "function",
            "src/cap.py",
            summary=(
                "L10 tells a machine client which instruction-set "
                "contract is implemented"
            ),
        )
        query = (
            "Where does a cold one-shot process tell a machine client "
            "which instruction-set contract it implements?"
        )
        result = retrieve_context(graph, query, "subsystem_summary", 2)
        answerability = result.metadata["answerability"]
        self.assertEqual(answerability["status"], "answerable")
        self.assertFalse(answerability["abstained"])
        self.assertIn("TARGET", result.nodes)

    def test_scoped_doc_summary_keeps_the_document_hit(self) -> None:
        # Explicit document scope is an operator-directed read, not a dirty
        # lexical collision. Ungrounded-packet emptying must not drop the
        # only paragraph in that scope.
        path = "docs/roadmap/gaps.md"
        graph = Graph(
            nodes={
                "ABSENT": Node(
                    "ABSENT",
                    "Symbolic PAC learning",
                    "paragraph",
                    path,
                    facts=("* `[ ]` **Symbolic PAC learning:** Not implemented.",),
                ),
            }
        )
        result = retrieve_context(
            graph,
            "Identify one capability currently marked absent.",
            "doc_summary",
            2,
            scopes=(path,),
        )
        self.assertIn("ABSENT", result.starts)
        self.assertNotEqual(result.metadata["answerability"]["status"], "unanswerable")

    def test_distinctive_flow_path_terms_keep_production_code(self) -> None:
        # A long how-does-X-flow question names frontends/engine/expression.
        # Identity grounding diluted by query length must not empty the
        # production path those words actually sit on.
        graph = Graph(
            nodes={
                "PARSE": Node(
                    "PARSE",
                    "parse_expr",
                    "function",
                    "frontends/parse.py",
                    summary="frontend parsing into the engine expr",
                ),
                "LIFT": Node(
                    "LIFT",
                    "lift",
                    "function",
                    "engine/expr.py",
                    summary="engine expression representation",
                ),
            }
        )
        result = retrieve_context(
            graph,
            "How does expression parsing flow from frontends into the engine expression representation?",
            "subsystem_summary",
            2,
        )
        self.assertTrue(result.nodes, result.metadata)
        self.assertNotEqual(result.metadata["answerability"]["status"], "unanswerable")


class GroundingScoreTest(unittest.TestCase):
    """OW-AC-04 uses a continuous grounding score, not a reason checklist."""

    def test_term_specificity_is_monotonic_in_length_and_saturates_on_hyphens(self) -> None:
        from graphgraph.retrieval.grounding import term_specificity

        self.assertEqual(term_specificity("instruction-set"), 1.0)
        self.assertLess(term_specificity("packet"), term_specificity("settlement"))
        self.assertLess(term_specificity("field"), term_specificity("packet"))
        self.assertGreater(term_specificity("settlement"), 0.8)
        from graphgraph.retrieval.grounding import peaked_specificity

        self.assertLess(peaked_specificity("packet"), 0.1)
        self.assertGreater(peaked_specificity("instruction-set"), 0.9)

    def test_noisy_or_lets_one_strong_channel_dominate(self) -> None:
        from graphgraph.retrieval.grounding import noisy_or

        self.assertAlmostEqual(noisy_or((1.0, 0.1, 0.1)), 1.0)
        self.assertLess(noisy_or((0.2, 0.2)), 0.4)
        self.assertGreater(noisy_or((0.5, 0.5)), 0.5)


if __name__ == "__main__":
    unittest.main()
