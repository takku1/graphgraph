from __future__ import annotations

import unittest
from math import fsum

from graphgraph import Edge, Graph, Node, validate_packet
from graphgraph.packets import estimate_tokens
from graphgraph.representation import (
    HYBRID_REPRESENTATION_VERSION,
    HybridRepresentationConfig,
    accept_representation,
    compile_hybrid_representation,
    representation_schema,
)
from graphgraph.representation.hybrid import (
    CELL_PREFIX,
    _build_path_hierarchy,
    _render_exact_packet,
    _select_exact_frontier,
)


def _spread_graph(count: int = 40, *, packages: int = 4, modules: int = 5) -> Graph:
    """A graph wide enough that no budget can hold every entity exactly."""
    nodes = {
        f"N{i}": Node(
            f"N{i}",
            f"handler_{i}",
            "function",
            f"src/pkg{i % packages}/mod{i % modules}.py",
            summary=f"handles request variant {i}",
        )
        for i in range(count)
    }
    edges = [Edge(f"N{i}", f"N{(i + 1) % count}", "calls") for i in range(count)]
    return Graph(nodes=nodes, edges=edges)


class HybridRepresentationTest(unittest.TestCase):
    def test_aggregate_cover_renders_synthetic_cells(self) -> None:
        # Regression: the cell label read `graph.nodes[cell]` as an eagerly
        # evaluated `.get()` default, so every cover containing a synthetic
        # cell raised KeyError('__gg_cell__:project') before a packet existed.
        graph = _spread_graph()
        result = compile_hybrid_representation(
            graph,
            {"N0": 1.0},
            config=HybridRepresentationConfig(token_budget=400),
        )
        self.assertIn("[a] global-cover", result.packet)
        self.assertTrue(result.aggregate_cells)
        self.assertNotIn(CELL_PREFIX, result.packet)

    def test_every_active_entity_is_represented_exactly_once(self) -> None:
        graph = _spread_graph(60)
        result = compile_hybrid_representation(
            graph,
            {"N0": 1.0, "N7": 0.5},
            config=HybridRepresentationConfig(token_budget=500),
        )
        receipt = result.receipt
        self.assertEqual(receipt["active_entities"], 60)
        self.assertEqual(receipt["represented_entities"], 60)
        self.assertEqual(receipt["coverage"], 1.0)
        self.assertEqual(receipt["duplicate_entities"], 0)

    def test_packet_stays_within_budget_and_validates(self) -> None:
        graph = _spread_graph(80)
        for budget in (300, 700, 1500):
            with self.subTest(budget=budget):
                result = compile_hybrid_representation(
                    graph,
                    {"N0": 1.0},
                    config=HybridRepresentationConfig(token_budget=budget),
                )
                self.assertLessEqual(estimate_tokens(result.packet), budget)
                self.assertTrue(result.receipt["within_budget"])
                validation = validate_packet(result.packet)
                self.assertTrue(validation.ok, validation.errors)

    def test_exact_and_aggregate_mass_partition_the_field(self) -> None:
        graph = _spread_graph(50)
        result = compile_hybrid_representation(
            graph,
            {"N3": 1.0},
            config=HybridRepresentationConfig(token_budget=600),
        )
        total = fsum((result.receipt["exact_mass"], result.receipt["aggregate_mass"]))
        self.assertAlmostEqual(total, 1.0, places=9)

    def test_priority_entities_are_always_exact(self) -> None:
        graph = _spread_graph(60)
        # A budget this tight cannot hold the frontier the field would pick,
        # so priority must win on reserve rather than on rank.
        result = compile_hybrid_representation(
            graph,
            {"N0": 1.0},
            priority=("N41", "N52"),
            config=HybridRepresentationConfig(token_budget=200),
        )
        self.assertIn("N41", result.exact_nodes)
        self.assertIn("N52", result.exact_nodes)

    def test_priority_ignores_entities_absent_from_the_graph(self) -> None:
        graph = _spread_graph(20)
        result = compile_hybrid_representation(
            graph,
            {"N0": 1.0},
            priority=("does-not-exist",),
            config=HybridRepresentationConfig(token_budget=500),
        )
        self.assertNotIn("does-not-exist", result.exact_nodes)

    def test_larger_budget_never_shrinks_the_exact_frontier(self) -> None:
        graph = _spread_graph(60)
        sizes = [
            len(
                compile_hybrid_representation(
                    graph,
                    {"N0": 1.0},
                    config=HybridRepresentationConfig(token_budget=budget),
                ).exact_nodes
            )
            for budget in (250, 500, 1000, 2000)
        ]
        self.assertEqual(sizes, sorted(sizes))

    def test_refinement_spends_surplus_budget_on_resolution(self) -> None:
        graph = _spread_graph(70)
        tight = compile_hybrid_representation(
            graph, {"N0": 1.0}, config=HybridRepresentationConfig(token_budget=260)
        )
        loose = compile_hybrid_representation(
            graph, {"N0": 1.0}, config=HybridRepresentationConfig(token_budget=900)
        )
        self.assertGreaterEqual(loose.receipt["refinements"], tight.receipt["refinements"])
        self.assertLessEqual(
            loose.receipt["unresolved_log_resolution"],
            tight.receipt["unresolved_log_resolution"],
        )

    def test_receipt_is_json_safe_and_versioned(self) -> None:
        import json

        graph = _spread_graph(30)
        result = compile_hybrid_representation(
            graph, {"N0": 1.0}, config=HybridRepresentationConfig(token_budget=500)
        )
        self.assertEqual(result.receipt["version"], HYBRID_REPRESENTATION_VERSION)
        self.assertEqual(result.receipt["status"], "experimental_opt_in")
        json.dumps(result.receipt)

    def test_hierarchy_cache_hits_on_an_unchanged_graph(self) -> None:
        graph = _spread_graph(30)
        first = compile_hybrid_representation(
            graph, {"N0": 1.0}, config=HybridRepresentationConfig(token_budget=500)
        )
        second = compile_hybrid_representation(
            graph, {"N1": 1.0}, config=HybridRepresentationConfig(token_budget=500)
        )
        self.assertEqual(first.receipt["hierarchy_cache"], "miss")
        self.assertEqual(second.receipt["hierarchy_cache"], "hit")

    def test_mutating_the_graph_invalidates_the_hierarchy_cache(self) -> None:
        graph = _spread_graph(30)
        compile_hybrid_representation(
            graph, {"N0": 1.0}, config=HybridRepresentationConfig(token_budget=500)
        )
        graph.nodes["EXTRA"] = Node("EXTRA", "late_arrival", "function", "src/late.py")
        result = compile_hybrid_representation(
            graph, {"N0": 1.0}, config=HybridRepresentationConfig(token_budget=500)
        )
        self.assertEqual(result.receipt["hierarchy_cache"], "miss")
        self.assertEqual(result.receipt["active_entities"], 31)

    def test_edgeless_exact_frontier_still_compiles_a_cover(self) -> None:
        # Regression: with no edges among the selected nodes the renderer ends
        # the packet at "[e]" with no trailing newline, so a "\n[e]\n" probe
        # missed the section and every such query fell back to flat.
        nodes = {
            f"N{i}": Node(f"N{i}", f"lonely_{i}", "function", f"src/pkg{i % 3}/mod{i}.py")
            for i in range(24)
        }
        graph = Graph(nodes=nodes, edges=[])
        result = compile_hybrid_representation(
            graph, {"N0": 1.0}, config=HybridRepresentationConfig(token_budget=260)
        )
        self.assertIn("[a] global-cover", result.packet)
        self.assertEqual(result.receipt["coverage"], 1.0)
        validation = validate_packet(result.packet)
        self.assertTrue(validation.ok, validation.errors)

    def test_unpathed_entities_are_still_covered(self) -> None:
        graph = Graph(
            nodes={
                "A": Node("A", "rooted", "function", "src/a.py"),
                "B": Node("B", "floating", "concept", ""),
            },
            edges=[],
        )
        result = compile_hybrid_representation(
            graph, {"A": 1.0}, config=HybridRepresentationConfig(token_budget=128)
        )
        self.assertEqual(result.receipt["coverage"], 1.0)
        self.assertEqual(result.receipt["duplicate_entities"], 0)


class HybridFrontierSelectionTest(unittest.TestCase):
    def test_floor_filter_matches_the_unfiltered_greedy(self) -> None:
        # The floor is only sound if it never discards a candidate that would
        # have fit. Compare against the O(n) render-every-candidate greedy the
        # filter replaced.
        graph = _spread_graph(120)
        active = frozenset(graph.nodes)
        raw = graph.personalized_pagerank({"N0": 1.0})
        total = fsum(max(0.0, raw.get(n, 0.0)) for n in active)
        field = {n: max(0.0, raw.get(n, 0.0)) / total for n in active}
        ranked = tuple(sorted(active, key=lambda n: (-field[n], n)))

        for budget in (150, 400, 900):
            with self.subTest(budget=budget):
                reference: set[str] = set()
                for node_id in ranked:
                    candidate = reference | {node_id}
                    rendered = _render_exact_packet(graph, candidate, "gg", ())
                    if estimate_tokens(rendered) <= budget:
                        reference = candidate
                filtered = _select_exact_frontier(graph, ranked, (), field, "gg", budget)
                self.assertEqual(filtered, reference)


class HybridHierarchyTest(unittest.TestCase):
    def test_hierarchy_covers_every_active_leaf(self) -> None:
        graph = _spread_graph(45)
        hierarchy = _build_path_hierarchy(graph, max_branching=8)
        self.assertEqual(hierarchy.cell_leaves(hierarchy.roots[0]), hierarchy.leaves)

    def test_branching_stays_bounded(self) -> None:
        graph = _spread_graph(200, packages=1, modules=1)
        hierarchy = _build_path_hierarchy(graph, max_branching=4)
        for children in hierarchy.children.values():
            self.assertLessEqual(len(children), 4)

    def test_inactive_entities_are_excluded(self) -> None:
        graph = _spread_graph(10)
        graph.nodes["N9"] = Node(
            "N9", "retired", "function", "src/pkg1/mod4.py", active=False
        )
        result = compile_hybrid_representation(
            graph, {"N0": 1.0}, config=HybridRepresentationConfig(token_budget=400)
        )
        self.assertEqual(result.receipt["active_entities"], 9)
        self.assertNotIn("N9", result.exact_nodes)

    def test_reserved_cell_id_collision_is_rejected(self) -> None:
        graph = _spread_graph(5)
        colliding = f"{CELL_PREFIX}project"
        graph.nodes[colliding] = Node(colliding, "impostor", "function", "src/x.py")
        with self.assertRaises(ValueError):
            compile_hybrid_representation(graph, {"N0": 1.0})


class HybridBudgetAcceptanceTest(unittest.TestCase):
    def _overflowing(self) -> object:
        graph = _spread_graph(12, packages=12, modules=12)
        # Reserving all twelve entities exactly cannot fit a 64-token budget.
        return compile_hybrid_representation(
            graph,
            {"N0": 1.0},
            priority=tuple(f"N{i}" for i in range(12)),
            config=HybridRepresentationConfig(token_budget=64),
        )

    def test_over_budget_packet_is_withheld(self) -> None:
        result = self._overflowing()
        self.assertFalse(result.receipt["within_budget"])
        packet, receipt = accept_representation(result)
        self.assertIsNone(packet)
        self.assertEqual(receipt["status"], "fallback_flat")
        self.assertIn("proxy tokens", str(receipt["reason"]))
        # The overflow stays auditable rather than being erased by the fallback.
        self.assertGreater(receipt["proxy_tokens"], receipt["token_budget"])

    def test_within_budget_packet_is_returned_unchanged(self) -> None:
        graph = _spread_graph(40)
        result = compile_hybrid_representation(
            graph, {"N0": 1.0}, config=HybridRepresentationConfig(token_budget=800)
        )
        packet, receipt = accept_representation(result)
        self.assertEqual(packet, result.packet)
        self.assertEqual(receipt["status"], "experimental_opt_in")

    def test_accept_does_not_mutate_the_original_receipt(self) -> None:
        result = self._overflowing()
        accept_representation(result)
        self.assertEqual(result.receipt["status"], "experimental_opt_in")


class HybridContractTest(unittest.TestCase):
    def test_unsupported_packet_format_is_rejected(self) -> None:
        graph = _spread_graph(10)
        with self.assertRaises(ValueError):
            compile_hybrid_representation(graph, {"N0": 1.0}, packet_format="svo")

    def test_supported_packet_formats_all_compile(self) -> None:
        graph = _spread_graph(40)
        for packet_format in ("gg", "gg_hybrid", "gg_lex", "gg_lex_hybrid"):
            with self.subTest(packet_format=packet_format):
                result = compile_hybrid_representation(
                    graph,
                    {"N0": 1.0},
                    packet_format=packet_format,
                    config=HybridRepresentationConfig(token_budget=700),
                )
                validation = validate_packet(result.packet)
                self.assertTrue(validation.ok, validation.errors)

    def test_empty_and_seedless_graphs_raise_value_error(self) -> None:
        # Both call sites degrade to flat on ValueError, so these must not
        # escape as some other exception type.
        with self.assertRaises(ValueError):
            compile_hybrid_representation(Graph(), {"N0": 1.0})
        graph = _spread_graph(5)
        with self.assertRaises(ValueError):
            compile_hybrid_representation(graph, {})
        with self.assertRaises(ValueError):
            compile_hybrid_representation(graph, {"absent": 1.0})
        with self.assertRaises(ValueError):
            compile_hybrid_representation(graph, {"N0": 0.0})

    def test_config_rejects_out_of_range_values(self) -> None:
        for kwargs in (
            {"token_budget": 32},
            {"exact_fraction": 0.0},
            {"exact_fraction": 1.0},
            {"max_branching": 1},
        ):
            with self.subTest(**kwargs):
                with self.assertRaises(ValueError):
                    HybridRepresentationConfig(**kwargs)

    def test_schema_advertises_the_opt_in_default(self) -> None:
        schema = representation_schema()
        self.assertEqual(schema["default"], "flat")
        self.assertEqual(schema["enum"], ["flat", "hybrid"])


if __name__ == "__main__":
    unittest.main()
