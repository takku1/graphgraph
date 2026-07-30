from __future__ import annotations

import unittest

from graphgraph.graph.core import Edge, Graph, Node
from graphgraph.graph.coupling import EDGE_COUPLINGS, coupled_graph


def _graph() -> Graph:
    nodes = {n: Node(n, n.lower(), "function", f"src/{n}.py") for n in ("A", "B", "C")}
    return Graph(nodes=nodes, edges=[Edge("A", "B", "calls", 0.9), Edge("B", "C", "calls")])


class CoupledGraphTest(unittest.TestCase):
    def test_directed_returns_the_input_untouched(self) -> None:
        graph = _graph()
        self.assertIs(coupled_graph(graph, "directed"), graph)

    def test_symmetric_adds_one_reverse_per_active_edge(self) -> None:
        graph = _graph()
        result = coupled_graph(graph, "symmetric")
        self.assertEqual(len(result.edges), 2 * len(graph.edges))
        pairs = {(edge.source, edge.target) for edge in result.edges}
        self.assertEqual(pairs, {("A", "B"), ("B", "A"), ("B", "C"), ("C", "B")})

    def test_reverse_flips_without_keeping_the_original(self) -> None:
        result = coupled_graph(_graph(), "reverse")
        pairs = {(edge.source, edge.target) for edge in result.edges}
        self.assertEqual(pairs, {("B", "A"), ("C", "B")})

    def test_edge_payloads_are_preserved(self) -> None:
        result = coupled_graph(_graph(), "symmetric")
        flipped = next(e for e in result.edges if (e.source, e.target) == ("B", "A"))
        self.assertEqual(flipped.type, "calls")
        self.assertAlmostEqual(flipped.weight, 0.9)

    def test_inactive_edges_are_excluded(self) -> None:
        graph = _graph()
        graph.edges.append(Edge("A", "C", "calls", active=False))
        result = coupled_graph(graph, "symmetric")
        pairs = {(edge.source, edge.target) for edge in result.edges}
        self.assertNotIn(("A", "C"), pairs)
        self.assertNotIn(("C", "A"), pairs)

    def test_input_graph_is_never_mutated(self) -> None:
        graph = _graph()
        before = (len(graph.edges), graph.mutation_revision)
        for coupling in EDGE_COUPLINGS:
            coupled_graph(graph, coupling)
        self.assertEqual((len(graph.edges), graph.mutation_revision), before)

    def test_unknown_coupling_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            coupled_graph(_graph(), "sideways")


class CoupledGraphCacheTest(unittest.TestCase):
    def test_repeated_calls_reuse_one_graph(self) -> None:
        graph = _graph()
        self.assertIs(coupled_graph(graph, "symmetric"), coupled_graph(graph, "symmetric"))

    def test_distinct_couplings_do_not_share_a_cache_entry(self) -> None:
        graph = _graph()
        symmetric = coupled_graph(graph, "symmetric")
        reverse = coupled_graph(graph, "reverse")
        self.assertIsNot(symmetric, reverse)
        self.assertEqual(len(reverse.edges), len(graph.edges))

    def test_node_mutation_invalidates_the_cache(self) -> None:
        graph = _graph()
        before = coupled_graph(graph, "symmetric")
        graph.nodes["D"] = Node("D", "d", "function", "src/D.py")
        after = coupled_graph(graph, "symmetric")
        self.assertIsNot(before, after)
        self.assertIn("D", after.nodes)

    def test_edge_mutation_invalidates_the_cache(self) -> None:
        graph = _graph()
        before = coupled_graph(graph, "symmetric")
        graph.edges.append(Edge("C", "A", "calls"))
        after = coupled_graph(graph, "symmetric")
        self.assertIsNot(before, after)
        self.assertEqual(len(after.edges), 2 * len(graph.edges))


class SearchCouplingTest(unittest.TestCase):
    """`search_nodes` gained a coupling knob whose default must be inert.

    The candidate it exists to measure was rejected on production evidence
    (`EXP-GPA-COUPLING-PROD`), so the knob survives only as an instrument. Its
    default has to stay a pass-through, and only the PageRank term may see it --
    lexical scoring and the degree boost must keep reading the real edges.
    """

    def _graph(self) -> Graph:
        nodes = {
            "A": Node("A", "parse_flags", "function", "src/flags.py"),
            "B": Node("B", "render_output", "function", "src/out.py"),
            "C": Node("C", "write_line", "function", "src/io.py"),
        }
        return Graph(nodes=nodes, edges=[Edge("A", "B", "calls"), Edge("B", "C", "calls")])

    def test_default_is_the_directed_pass_through(self) -> None:
        from graphgraph.retrieval.search import search_nodes

        graph = self._graph()
        default = [m.node.id for m in search_nodes(graph, "parse flags", personalize=True)]
        explicit = [
            m.node.id
            for m in search_nodes(graph, "parse flags", personalize=True, coupling="directed")
        ]
        self.assertEqual(default, explicit)

    def test_unknown_coupling_is_rejected(self) -> None:
        from graphgraph.retrieval.search import search_nodes

        with self.assertRaises(ValueError):
            search_nodes(self._graph(), "parse flags", coupling="sideways")

    def test_coupling_does_not_disturb_the_degree_boost(self) -> None:
        # The degree boost reads graph.degree(). If the coupled graph leaked
        # past the PageRank term, symmetrizing would double every degree and
        # change scores even with personalization switched off.
        from graphgraph.retrieval.search import search_nodes

        graph = self._graph()
        off = [
            (m.node.id, round(m.score, 9))
            for m in search_nodes(graph, "render output", personalize=False)
        ]
        for coupling in EDGE_COUPLINGS:
            with self.subTest(coupling=coupling):
                same = [
                    (m.node.id, round(m.score, 9))
                    for m in search_nodes(
                        graph, "render output", personalize=False, coupling=coupling
                    )
                ]
                self.assertEqual(off, same)


if __name__ == "__main__":
    unittest.main()
