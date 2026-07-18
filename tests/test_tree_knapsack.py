from __future__ import annotations

import unittest

from graphgraph import (
    Edge,
    Graph,
    Node,
)


class TreeKnapsackTest(unittest.TestCase):
    def test_connected_greedy_respects_budget_and_parent_connectivity(self) -> None:
        from graphgraph.retrieval.tree_knapsack import connected_greedy_context_partition, packet_node_costs

        graph = Graph(
            nodes={name: Node(name, name) for name in ("A", "B", "C", "D")},
            edges=[Edge("A", "B", "calls"), Edge("B", "C", "calls"), Edge("A", "D", "calls")],
        )
        values = {"A": 1.0, "B": 0.9, "C": 10.0, "D": 0.2}
        costs = packet_node_costs(
            graph,
            set(graph.nodes),
            graph.edges,
            packet="gg",
            token_budget=60,
            max_nodes=3,
        )

        selected = connected_greedy_context_partition(
            graph,
            ("A",),
            set(graph.nodes),
            values,
            60,
            edges=graph.edges,
            max_nodes=3,
        )

        self.assertIn("A", selected)
        if "C" in selected:
            self.assertIn("B", selected)
        self.assertLessEqual(sum(costs[node_id] for node_id in selected), 60)
        self.assertLessEqual(len(selected), 3)

    def test_tree_knapsack_context_partition(self) -> None:
        from graphgraph.retrieval.tree_knapsack import tree_knapsack_context_partition

        g = Graph(
            nodes={
                "A": Node("A", "A", "class", "a.py", active=True, facts=("f1",)),
                "B": Node("B", "B", "class", "b.py", active=True, facts=("f1",)),
                "C": Node(
                    "C", "C", "class", "c.py", active=True, facts=("f1", "f2", "f3", "f4", "f5", "f6", "f7", "f8")
                ),
            },
            edges=[
                Edge("A", "B", "calls", 1.0),
                Edge("A", "C", "calls", 1.0),
            ],
        )
        values = {"A": 10.0, "B": 5.0, "C": 8.0}

        # A two-node ceiling keeps the anchor and the stronger of its two children.
        selected = tree_knapsack_context_partition(g, ("A",), {"A", "B", "C"}, values, 80, max_nodes=2)
        self.assertIn("A", selected)
        self.assertIn("C", selected)
        self.assertNotIn("B", selected)

        # A three-node ceiling can retain the whole connected neighborhood.
        selected = tree_knapsack_context_partition(g, ("A",), {"A", "B", "C"}, values, 120, max_nodes=3)
        self.assertIn("A", selected)
        self.assertIn("C", selected)
        self.assertIn("B", selected)

    def test_tree_knapsack_charges_dense_nodes_for_packet_edges(self) -> None:
        from graphgraph.retrieval.tree_knapsack import tree_knapsack_context_partition

        graph = Graph(
            nodes={"A": Node("A", "A"), "B": Node("B", "B"), "C": Node("C", "C")}
            | {f"D{i}": Node(f"D{i}", f"D{i}") for i in range(8)},
            edges=[Edge("A", "B", "calls"), Edge("A", "C", "calls")]
            + [Edge("C", f"D{i}", "calls") for i in range(8)],
        )
        candidates = set(graph.nodes)
        values = {node_id: 1.0 for node_id in candidates} | {"A": 10.0, "B": 5.0, "C": 5.0}
        selected = tree_knapsack_context_partition(
            graph,
            ("A",),
            candidates,
            values,
            80,
            edges=graph.edges,
            packet="gg",
            max_nodes=2,
        )
        self.assertIn("B", selected)
        self.assertNotIn("C", selected)

    def test_build_bfs_tree_handles_start_node_outside_candidates(self) -> None:
        # Regression: tree was pre-seeded with keys only for `candidates`, but
        # BFS starts from `starts`. A start node not itself in candidates
        # (e.g. an anchor that graph.expand() dropped for being inactive or
        # out of scope) with a neighbor that IS a candidate raised KeyError
        # on `tree[curr].append(...)`.
        from graphgraph.retrieval.tree_knapsack import build_bfs_tree

        graph = Graph(
            nodes={"S": Node("S", "S"), "C1": Node("C1", "C1")},
            edges=[Edge("S", "C1", "calls")],
        )
        tree = build_bfs_tree(graph, starts=("S",), candidates={"C1"})
        self.assertEqual(tree.get("S"), ["C1"])

    def test_tree_knapsack_selects_orphan_candidates(self) -> None:
        # Regression: the orphan-detection loop marked every disconnected
        # candidate as visited via dfs() *before* the code that was supposed
        # to record them as roots ran, so `[nid for nid in candidates if nid
        # not in visited_dfs]` was always empty. Each orphan's DP table was
        # computed but it could never be selected at the top level.
        from graphgraph.retrieval.tree_knapsack import tree_knapsack_context_partition

        graph = Graph(
            nodes={
                "S": Node("S", "S"),
                "ORPHAN": Node("ORPHAN", "orphan", "function", summary="x" * 200),
            },
            edges=[],  # ORPHAN is unreachable from S -- a disconnected component
        )
        selected = tree_knapsack_context_partition(
            graph,
            starts=("S",),
            candidates={"ORPHAN"},
            node_values={"ORPHAN": 100.0},
            max_token_budget=4000,
        )
        self.assertIn("ORPHAN", selected)

    def test_tree_knapsack_handles_long_chain_without_recursion_error(self) -> None:
        # Regression: both the dfs() post-order traversal and
        # subtree_backtrack() were plain function recursion. A long
        # dependency chain -- plausible in a real 2000-node graph -- exceeds
        # Python's default recursion limit (~1000) and crashes with
        # RecursionError. Confirmed this exact input crashes the old
        # recursive implementation; both were converted to explicit-stack
        # iteration.
        from graphgraph.retrieval.tree_knapsack import tree_knapsack_context_partition

        n = 1500
        nodes = {f"n{i}": Node(f"n{i}", f"n{i}", "function") for i in range(n)}
        edges = [Edge(f"n{i}", f"n{i + 1}", "calls") for i in range(n - 1)]
        graph = Graph(nodes=nodes, edges=edges)
        candidates = set(nodes.keys()) - {"n0"}
        values = {nid: 1.0 for nid in candidates}

        selected = tree_knapsack_context_partition(
            graph,
            starts=("n0",),
            candidates=candidates,
            node_values=values,
            max_token_budget=2000,
        )
        self.assertGreater(len(selected), 0)
