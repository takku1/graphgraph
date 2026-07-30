from __future__ import annotations

import inspect
import itertools
import unittest

from graphgraph import Graph, Node
from graphgraph.packets import estimate_tokens
from graphgraph.research import (
    CoverPlan,
    build_path_hierarchy,
    compile_greedy_formula_cover,
    compile_optimal_formula_cover,
    evaluate_cover,
    evaluate_expected_resolution,
    render_cover_plan,
    render_exact_nodes,
    select_flat_nodes_at_token_budget,
)


def fixture_graph() -> Graph:
    return Graph(
        nodes={
            "a": Node("a", "alpha", "function", "src/left.py"),
            "b": Node("b", "beta", "function", "src/left.py"),
            "c": Node("c", "gamma", "class", "src/right.py"),
            "d": Node("d", "delta", "test", "tests/test_right.py"),
            "policy": Node("policy", "policy", "policy", ""),
        }
    )


def enumerate_covers(hierarchy, cell: str) -> tuple[tuple[str, ...], ...]:
    children = hierarchy.children.get(cell)
    if children is None:
        return ((cell,),)
    refined = tuple(
        tuple(item for child_cover in combination for item in child_cover)
        for combination in itertools.product(*(enumerate_covers(hierarchy, child) for child in children))
    )
    return ((cell,), *refined)


class StaticCoverResearchTest(unittest.TestCase):
    def test_path_hierarchy_is_total_for_shared_windows_and_unpathed_nodes(self) -> None:
        graph = fixture_graph()
        graph.nodes["a"] = Node("a", "alpha", "function", "src\\left.py")

        index = build_path_hierarchy(graph)

        self.assertEqual(index.hierarchy.leaves, frozenset(graph.nodes))
        self.assertIn("__gg_research_cell__:src/left.py", index.hierarchy.nodes)
        self.assertIn("__gg_research_cell__:unpathed", index.hierarchy.nodes)

    def test_path_hierarchy_has_bounded_refinement_arity(self) -> None:
        graph = Graph(
            nodes={
                f"n{index}": Node(
                    f"n{index}",
                    f"node-{index}",
                    "function",
                    f"top-{index}/file.py",
                )
                for index in range(41)
            }
        )

        hierarchy = build_path_hierarchy(graph, max_branching=4).hierarchy

        self.assertTrue(all(len(children) <= 4 for children in hierarchy.children.values()))

    def test_formula_tree_dp_matches_independent_enumeration(self) -> None:
        index = build_path_hierarchy(fixture_graph())
        hierarchy = index.hierarchy
        field = {"a": 0.44, "b": 0.06, "c": 0.25, "d": 0.2, "policy": 0.05}
        weight = 0.2
        covers = enumerate_covers(hierarchy, hierarchy.roots[0])

        for budget in range(1, 7):
            optimal = compile_optimal_formula_cover(
                hierarchy,
                field,
                budget,
                exactness_weight=weight,
            )
            result = evaluate_cover(hierarchy, field, optimal)
            measured = result["l2_error"] + weight * result["aggregate_mass"]
            brute_force = min(
                (candidate_result["l2_error"] + weight * candidate_result["aggregate_mass"])
                for cover in covers
                if len(cover) <= budget
                for candidate_result in [evaluate_cover(hierarchy, field, CoverPlan(cover))]
            )
            self.assertAlmostEqual(measured, brute_force, places=15)

    def test_scalable_greedy_is_measured_against_not_assumed_equal_to_optimum(self) -> None:
        hierarchy = build_path_hierarchy(fixture_graph()).hierarchy
        field = {"a": 0.44, "b": 0.06, "c": 0.25, "d": 0.2, "policy": 0.05}
        weight = 0.2

        for budget in range(1, 7):
            optimal = evaluate_cover(
                hierarchy,
                field,
                compile_optimal_formula_cover(
                    hierarchy,
                    field,
                    budget,
                    exactness_weight=weight,
                ),
            )
            greedy = evaluate_cover(
                hierarchy,
                field,
                compile_greedy_formula_cover(
                    hierarchy,
                    field,
                    budget,
                    exactness_weight=weight,
                ),
            )
            optimal_objective = optimal["l2_error"] + weight * optimal["aggregate_mass"]
            greedy_objective = greedy["l2_error"] + weight * greedy["aggregate_mass"]
            self.assertGreaterEqual(greedy_objective + 1e-15, optimal_objective)

    def test_equal_token_baseline_and_resolution_metrics_are_evaluator_only(self) -> None:
        graph = fixture_graph()
        index = build_path_hierarchy(graph)
        field = {"a": 0.44, "b": 0.06, "c": 0.25, "d": 0.2, "policy": 0.05}
        plan = compile_greedy_formula_cover(
            index.hierarchy,
            field,
            5,
            exactness_weight=0.2,
        )

        packet = render_cover_plan(graph, index, field, plan)
        token_budget = estimate_tokens(packet)
        flat = select_flat_nodes_at_token_budget(graph, field, token_budget)
        receipt = evaluate_expected_resolution(index.hierarchy, plan, {"a", "d"})

        self.assertLessEqual(
            estimate_tokens(render_cover_plan(graph, index, field, plan)),
            token_budget,
        )
        self.assertLessEqual(
            estimate_tokens(render_exact_nodes(graph, field, flat)),
            token_budget,
        )
        self.assertGreaterEqual(receipt["resolution_recall"], receipt["exact_recall"])
        self.assertNotIn("expected_nodes", inspect.signature(render_cover_plan).parameters)

    def test_incremental_flat_token_accounting_matches_brute_force(self) -> None:
        graph = fixture_graph()
        field = {"a": 0.44, "b": 0.06, "c": 0.25, "d": 0.2, "policy": 0.05}
        ranked = sorted(field, key=lambda node_id: (-field[node_id], node_id))

        for budget in range(0, 100):
            brute_force: list[str] = []
            for node_id in ranked:
                candidate = (*brute_force, node_id)
                if estimate_tokens(render_exact_nodes(graph, field, candidate)) <= budget:
                    brute_force.append(node_id)
            measured = select_flat_nodes_at_token_budget(graph, field, budget)
            self.assertEqual(measured, tuple(brute_force))


if __name__ == "__main__":
    unittest.main()
