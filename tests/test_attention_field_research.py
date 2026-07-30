from __future__ import annotations

import itertools
import random
import unittest

from graphgraph import Edge, Graph, Node
from graphgraph.research.attention_field import (
    CoverPlan,
    Hierarchy,
    compile_greedy_cover,
    compile_optimal_cover,
    compile_optimal_formula_cover,
    coverage_receipt,
    effective_influence_receipt,
    evaluate_cover,
    evaluate_top_k,
    exact_influence_field,
)


def balanced_hierarchy() -> Hierarchy:
    return Hierarchy(
        {
            "root": ("left", "right"),
            "left": ("left_near", "left_far"),
            "right": ("right_near", "right_far"),
            "left_near": ("a", "b"),
            "left_far": ("c", "d"),
            "right_near": ("e", "f"),
            "right_far": ("g", "h"),
        },
        ("root",),
    )


def project_graph() -> Graph:
    labels = "abcdefgh"
    graph = Graph(nodes={label: Node(label, label, "function", f"src/{label}.py") for label in labels})
    graph.edges.extend(
        [
            Edge("a", "b", "calls"),
            Edge("b", "c", "calls"),
            Edge("c", "d", "calls"),
            Edge("d", "a", "calls"),
            Edge("d", "e", "calls", confidence=0.8),
            Edge("e", "f", "calls"),
            Edge("f", "g", "calls"),
            Edge("g", "h", "calls"),
            Edge("h", "e", "calls"),
        ]
    )
    return graph


def unbalanced_hierarchy() -> Hierarchy:
    return Hierarchy(
        {
            "root": ("wide", "narrow"),
            "wide": ("a", "b", "c", "d"),
            "narrow": ("e", "f"),
        },
        ("root",),
    )


def enumerate_covers(hierarchy: Hierarchy, cell: str) -> tuple[tuple[str, ...], ...]:
    """Independent brute-force antichain generator for testing the tree DP."""
    children = hierarchy.children.get(cell)
    if children is None:
        return ((cell,),)
    refined = tuple(
        tuple(item for child_cover in combination for item in child_cover)
        for combination in itertools.product(*(enumerate_covers(hierarchy, child) for child in children))
    )
    return ((cell,), *refined)


class AttentionFieldResearchTest(unittest.TestCase):
    def test_exact_oracle_is_normalized_and_global_nonzero_is_vacuous(self) -> None:
        field = exact_influence_field(project_graph(), {"a": 1.0})

        self.assertAlmostEqual(sum(field.values()), 1.0, places=10)
        self.assertTrue(all(mass > 0.0 for mass in field.values()))
        self.assertLess(field["h"], field["a"])

    def test_cover_receipt_rejects_overlap_and_missing_leaves(self) -> None:
        hierarchy = balanced_hierarchy()

        overlap = coverage_receipt(hierarchy, CoverPlan(("root", "a")))
        missing = coverage_receipt(hierarchy, CoverPlan(("left",)))

        self.assertFalse(overlap["valid"])
        self.assertIn("a", overlap["duplicate"])
        self.assertFalse(missing["valid"])
        self.assertEqual(set(missing["missing"]), {"e", "f", "g", "h"})

    def test_optimal_cover_is_complete_mass_conserving_and_l2_monotone(self) -> None:
        hierarchy = balanced_hierarchy()
        field = exact_influence_field(project_graph(), {"a": 1.0})
        errors = []

        for budget in range(1, 9):
            plan = compile_optimal_cover(hierarchy, field, budget)
            result = evaluate_cover(hierarchy, field, plan)
            self.assertTrue(result["coverage"]["valid"])
            self.assertEqual(result["coverage"]["coverage"], 1.0)
            self.assertAlmostEqual(result["mass_error"], 0.0, places=12)
            errors.append(result["l2_error"])

        self.assertTrue(all(right <= left + 1e-15 for left, right in zip(errors, errors[1:])))
        self.assertAlmostEqual(errors[-1], 0.0, places=15)

    def test_greedy_is_bounded_by_exhaustive_mathematical_ceiling(self) -> None:
        hierarchy = balanced_hierarchy()
        field = exact_influence_field(project_graph(), {"a": 1.0})

        for budget in range(1, 9):
            optimal = evaluate_cover(hierarchy, field, compile_optimal_cover(hierarchy, field, budget))
            greedy = evaluate_cover(hierarchy, field, compile_greedy_cover(hierarchy, field, budget))
            self.assertGreaterEqual(greedy["l2_error"] + 1e-15, optimal["l2_error"])
            self.assertEqual(greedy["coverage"]["coverage"], 1.0)

    def test_tree_dynamic_program_matches_independent_brute_force(self) -> None:
        hierarchy = balanced_hierarchy()
        all_covers = enumerate_covers(hierarchy, "root")
        generator = random.Random(20260728)

        for _case in range(20):
            field = {leaf: generator.random() for leaf in hierarchy.leaves}
            for budget in range(1, len(hierarchy.leaves) + 1):
                plan = compile_optimal_cover(hierarchy, field, budget)
                measured = evaluate_cover(hierarchy, field, plan)["l2_error"]
                brute_force = min(
                    evaluate_cover(hierarchy, field, CoverPlan(cover))["l2_error"]
                    for cover in all_covers
                    if len(cover) <= budget
                )
                self.assertAlmostEqual(measured, brute_force, places=15)

    def test_one_step_greedy_has_a_deterministic_knapsack_counterexample(self) -> None:
        hierarchy = unbalanced_hierarchy()
        field = {
            "a": 0.1576244644117335,
            "b": 0.2572940158328786,
            "c": 0.20904766318798926,
            "d": 0.00009180314777116714,
            "e": 0.07350767030705409,
            "f": 0.30243438311257337,
        }

        optimal_plan = compile_optimal_cover(hierarchy, field, 5)
        greedy_plan = compile_greedy_cover(hierarchy, field, 5)
        optimal = evaluate_cover(hierarchy, field, optimal_plan)
        greedy = evaluate_cover(hierarchy, field, greedy_plan)

        self.assertEqual(optimal_plan.cover, ("a", "b", "c", "d", "narrow"))
        self.assertEqual(greedy_plan.cover, ("e", "f", "wide"))
        self.assertGreater(greedy["l2_error"], optimal["l2_error"] * 1.4)

    def test_l2_optimal_refinement_does_not_imply_monotone_l1(self) -> None:
        hierarchy = unbalanced_hierarchy()
        field = {
            "a": 0.021628600730411483,
            "b": 0.0011157563921729348,
            "c": 0.5329719140000019,
            "d": 0.11655287068542892,
            "e": 0.32545659389402826,
            "f": 0.0022742642979565754,
        }

        coarse = evaluate_cover(hierarchy, field, compile_optimal_cover(hierarchy, field, 1))
        refined = evaluate_cover(hierarchy, field, compile_optimal_cover(hierarchy, field, 2))

        self.assertLess(refined["l2_error"], coarse["l2_error"])
        self.assertGreater(refined["l1_error"], coarse["l1_error"])

    def test_mass_penalty_cancels_but_log_resolution_rewards_internal_refinement(self) -> None:
        hierarchy = Hierarchy(
            {
                "root": ("left", "right"),
                "left": ("a", "b"),
                "right": ("c", "d"),
            },
            ("root",),
        )
        uniform = {leaf: 0.25 for leaf in "abcd"}

        mass_only = compile_optimal_formula_cover(
            hierarchy,
            uniform,
            2,
            exactness_weight=10.0,
        )
        log_resolution = compile_optimal_formula_cover(
            hierarchy,
            uniform,
            2,
            exactness_weight=0.0,
            resolution_weight=1.0,
        )

        self.assertEqual(mass_only.cover, ("root",))
        self.assertEqual(log_resolution.cover, ("left", "right"))

    def test_global_coverage_is_not_a_utility_result(self) -> None:
        hierarchy = balanced_hierarchy()
        field = exact_influence_field(project_graph(), {"a": 1.0})

        coarsest = evaluate_cover(hierarchy, field, CoverPlan(("root",)))

        self.assertEqual(coarsest["coverage"]["coverage"], 1.0)
        self.assertGreater(coarsest["l1_error"], 0.0)
        self.assertLess(coarsest["resolution_weighted_coverage"], 1.0)

    def test_top_k_has_good_exact_mass_but_is_not_global_and_loses_mass(self) -> None:
        field = exact_influence_field(project_graph(), {"a": 1.0})

        baseline = evaluate_top_k(field, 2)

        self.assertEqual(baseline["coverage"], 0.25)
        self.assertGreater(baseline["mass_error"], 0.0)
        self.assertAlmostEqual(baseline["l1_error"], baseline["mass_error"], places=12)

    def test_effective_influence_uses_declared_threshold_not_nonzero_mass(self) -> None:
        hierarchy = balanced_hierarchy()
        field = exact_influence_field(project_graph(), {"a": 1.0})
        plan = compile_optimal_cover(hierarchy, field, 4)

        receipt = effective_influence_receipt(hierarchy, field, plan, minimum_mass=0.1)

        self.assertLess(receipt["effective_entities"], len(field))
        self.assertAlmostEqual(
            receipt["effective_mass"],
            receipt["effective_exact_mass"] + receipt["effective_aggregate_mass"],
            places=12,
        )

    def test_resolution_weighted_coverage_counts_sparse_residual_as_exact(self) -> None:
        hierarchy = Hierarchy({"root": ("a", "b", "c")}, ("root",))
        field = {"a": 0.7, "b": 0.2, "c": 0.1}
        plan = CoverPlan(("a", "c"), residual=frozenset({"b"}))

        result = evaluate_cover(hierarchy, field, plan)

        self.assertEqual(result["resolution_weighted_coverage"], 1.0)
        self.assertEqual(result["exact_attention_mass_capture"], 1.0)


if __name__ == "__main__":
    unittest.main()
