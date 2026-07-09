from __future__ import annotations

import unittest

from graphgraph import (
    Edge,
    Graph,
    Node,
)


def sample_graph() -> Graph:
    return Graph(
        nodes={
            "N1": Node("N1", "AuthService", "service", "server/auth.py"),
            "N2": Node("N2", "TokenStore", "data", "server/tokens.py"),
            "N3": Node("N3", "AuditLog", "data", "server/audit.py"),
        },
        edges=[
            Edge("N1", "N2", "reads", 0.9),
            Edge("N2", "N3", "writes", 0.8),
        ],
    )


class TreeKnapsackTest(unittest.TestCase):
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

        # Test 1: Budget weight = 2 (approx 80 tokens). Fits A (w=1) + B (w=1). C (w=2) cannot fit with A.
        selected = tree_knapsack_context_partition(g, ("A",), {"A", "B", "C"}, values, 80)
        self.assertIn("A", selected)
        self.assertIn("B", selected)
        self.assertNotIn("C", selected)

        # Test 2: Budget weight = 3 (approx 120 tokens). Fits A (w=1) + C (w=2) because 10+8=18 > A+B=15.
        selected = tree_knapsack_context_partition(g, ("A",), {"A", "B", "C"}, values, 120)
        self.assertIn("A", selected)
        self.assertIn("C", selected)
        self.assertNotIn("B", selected)

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
