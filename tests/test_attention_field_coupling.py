from __future__ import annotations

import unittest
from math import fsum

from graphgraph.graph.core import Edge, Graph, Node
from graphgraph.research.attention_field import (
    FIELD_COUPLINGS,
    field_support_receipt,
    influence_field,
)


def _chain(length: int) -> Graph:
    """A directed chain: the worst case for forward-only diffusion."""
    nodes = {f"N{i}": Node(f"N{i}", f"n{i}", "function", f"src/n{i}.py") for i in range(length)}
    edges = [Edge(f"N{i}", f"N{i + 1}", "calls") for i in range(length - 1)]
    return Graph(nodes=nodes, edges=edges)


def _sink_heavy(fan: int = 40) -> Graph:
    """One hub calling many leaves that call nothing.

    This is the shape the real graphs have -- 62.9% of active entities in the
    live project are directed sinks -- so it reproduces the substrate finding
    in miniature.
    """
    nodes = {"HUB": Node("HUB", "hub", "function", "src/hub.py")}
    nodes.update(
        {f"L{i}": Node(f"L{i}", f"leaf{i}", "function", f"src/leaf{i}.py") for i in range(fan)}
    )
    edges = [Edge("HUB", f"L{i}", "calls") for i in range(fan)]
    return Graph(nodes=nodes, edges=edges)


class FieldCouplingTest(unittest.TestCase):
    def test_every_coupling_conserves_mass_and_stays_non_negative(self) -> None:
        graph = _chain(8)
        for coupling in FIELD_COUPLINGS:
            with self.subTest(coupling=coupling):
                field = influence_field(graph, {"N3": 1.0}, coupling=coupling)
                self.assertAlmostEqual(fsum(field.values()), 1.0, places=9)
                self.assertTrue(all(value >= 0.0 for value in field.values()))
                self.assertEqual(set(field), set(graph.nodes))

    def test_directed_coupling_only_reaches_the_forward_cone(self) -> None:
        field = influence_field(_chain(8), {"N3": 1.0}, coupling="directed")
        reached = {node for node, mass in field.items() if mass > 0.0}
        self.assertTrue(reached <= {f"N{i}" for i in range(3, 8)})
        self.assertNotIn("N0", reached)

    def test_reverse_coupling_only_reaches_the_backward_cone(self) -> None:
        field = influence_field(_chain(8), {"N3": 1.0}, coupling="reverse")
        reached = {node for node, mass in field.items() if mass > 0.0}
        self.assertTrue(reached <= {f"N{i}" for i in range(0, 4)})
        self.assertNotIn("N7", reached)

    def test_symmetric_coupling_reaches_the_whole_connected_component(self) -> None:
        field = influence_field(_chain(8), {"N3": 1.0}, coupling="symmetric")
        self.assertTrue(all(mass > 0.0 for mass in field.values()))

    def test_symmetric_coupling_is_a_no_op_on_an_already_symmetric_graph(self) -> None:
        # Metamorphic relation: symmetrizing a symmetric graph must not move
        # the field, only rescale identically-shaped transitions.
        nodes = {n: Node(n, n.lower(), "function", f"src/{n}.py") for n in ("A", "B", "C")}
        pairs = (("A", "B"), ("B", "C"), ("C", "A"))
        edges = [Edge(s, t, "calls") for s, t in pairs] + [Edge(t, s, "calls") for s, t in pairs]
        graph = Graph(nodes=nodes, edges=edges)
        directed = influence_field(graph, {"A": 1.0}, coupling="directed")
        symmetric = influence_field(graph, {"A": 1.0}, coupling="symmetric")
        for node in nodes:
            self.assertAlmostEqual(directed[node], symmetric[node], places=9)

    def test_coupling_does_not_mutate_the_input_graph(self) -> None:
        graph = _chain(6)
        before_edges = len(graph.edges)
        before_revision = graph.mutation_revision
        for coupling in FIELD_COUPLINGS:
            influence_field(graph, {"N0": 1.0}, coupling=coupling)
        self.assertEqual(len(graph.edges), before_edges)
        self.assertEqual(graph.mutation_revision, before_revision)

    def test_unknown_coupling_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            influence_field(_chain(4), {"N0": 1.0}, coupling="diagonal")

    def test_sink_heavy_graph_is_degenerate_only_under_directed_coupling(self) -> None:
        # EXP-GPA-COUPLING in miniature. Directed diffusion from a leaf cannot
        # leave that leaf, so the far field is empty; symmetric diffusion
        # reaches the hub and every sibling.
        graph = _sink_heavy(40)
        directed = field_support_receipt(influence_field(graph, {"L0": 1.0}, coupling="directed"))
        symmetric = field_support_receipt(influence_field(graph, {"L0": 1.0}, coupling="symmetric"))
        self.assertEqual(directed["support"], 1)
        self.assertLess(directed["support_fraction"], 0.10)
        self.assertGreater(symmetric["support_fraction"], 0.90)
        self.assertGreater(symmetric["effective_entities"], directed["effective_entities"])


class FieldSupportReceiptTest(unittest.TestCase):
    def test_uniform_field_is_maximally_spread(self) -> None:
        receipt = field_support_receipt({f"N{i}": 1.0 for i in range(16)}, top_k=4)
        self.assertEqual(receipt["support"], 16)
        self.assertEqual(receipt["support_fraction"], 1.0)
        self.assertAlmostEqual(receipt["entropy_bits"], 4.0, places=9)
        self.assertAlmostEqual(receipt["effective_entities"], 16.0, places=6)
        self.assertAlmostEqual(receipt["mass_in_top_k"], 0.25, places=9)

    def test_delta_field_collapses_to_one_effective_entity(self) -> None:
        field = {"A": 1.0, **{f"N{i}": 0.0 for i in range(99)}}
        receipt = field_support_receipt(field)
        self.assertEqual(receipt["support"], 1)
        self.assertEqual(receipt["support_fraction"], 0.01)
        self.assertAlmostEqual(receipt["entropy_bits"], 0.0, places=9)
        self.assertAlmostEqual(receipt["effective_entities"], 1.0, places=9)
        self.assertAlmostEqual(receipt["mass_outside_top_k"], 0.0, places=9)

    def test_receipt_rejects_degenerate_input(self) -> None:
        with self.assertRaises(ValueError):
            field_support_receipt({})
        with self.assertRaises(ValueError):
            field_support_receipt({"A": 0.0, "B": 0.0})


if __name__ == "__main__":
    unittest.main()
