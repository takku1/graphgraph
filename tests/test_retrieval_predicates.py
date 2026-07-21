from __future__ import annotations

import unittest

from graphgraph import Edge, Graph, Node
from graphgraph.retrieval.predicates import (
    SelectionCriteria,
    caller_evidence_quality,
    parse_criteria,
    select_symbols,
)


def _graph() -> Graph:
    """A target called only by a test, one called by production, one orphan."""
    nodes = {
        "prod_caller": Node("prod_caller", "run", "function", "src/app.py", "L10"),
        "test_caller": Node("test_caller", "test_run", "function", "tests/test_app.py", "L5"),
        "test_only": Node("test_only", "helper_used_by_tests", "function", "src/util.py", "L20"),
        "used": Node("used", "used_in_production", "function", "src/util.py", "L30"),
        "orphan": Node("orphan", "never_called", "function", "src/util.py", "L40"),
        "recursive": Node("recursive", "loops_on_self", "function", "src/util.py", "L50"),
    }
    edges = [
        Edge("test_caller", "test_only", "calls"),
        Edge("prod_caller", "used", "calls"),
        Edge("recursive", "recursive", "calls"),
    ]
    return Graph(nodes=nodes, edges=edges)


class PredicateParsingTest(unittest.TestCase):
    def test_parses_conjunction_of_supported_clauses(self) -> None:
        criteria = parse_criteria(
            "production_callers = 0 and crate contains locus-engine and kind = method"
        )
        self.assertEqual(criteria.production_callers.operator, "=")
        self.assertEqual(criteria.production_callers.value, 0)
        self.assertEqual(criteria.path_contains, "locus-engine")
        self.assertEqual(criteria.kinds, ("method",))

    def test_leading_where_and_quotes_are_tolerated(self) -> None:
        criteria = parse_criteria("where label contains 'normalize' and include_tests = false")
        self.assertEqual(criteria.label_contains, "normalize")
        self.assertFalse(criteria.include_tests)

    def test_unsupported_clause_raises_instead_of_being_approximated(self) -> None:
        # A silently-ignored clause would return a superset and read as an
        # authoritative answer -- the exact failure this surface prevents.
        with self.assertRaises(ValueError) as ctx:
            parse_criteria("production_callers = 0 and cyclomatic_complexity > 4")
        self.assertIn("unsupported predicate clause", str(ctx.exception))

    def test_non_integer_caller_count_raises(self) -> None:
        with self.assertRaises(ValueError):
            parse_criteria("production_callers = many")


class SelectSymbolsTest(unittest.TestCase):
    def test_test_only_callers_do_not_count_as_production(self) -> None:
        graph = _graph()
        result = select_symbols(graph, parse_criteria("production_callers = 0"), mode="select")
        labels = {s["label"] for s in result.symbols}
        # Called only from tests/ -- production-dead, so it must be listed.
        self.assertIn("helper_used_by_tests", labels)
        # Genuinely called from production -- must not be.
        self.assertNotIn("used_in_production", labels)

    def test_all_callers_counts_tests_but_production_callers_does_not(self) -> None:
        graph = _graph()
        target = next(
            s for s in select_symbols(graph, SelectionCriteria(), mode="select").symbols
            if s["label"] == "helper_used_by_tests"
        )
        self.assertEqual(target["callers"], 1)
        self.assertEqual(target["production_callers"], 0)

    def test_self_recursion_is_not_evidence_of_use(self) -> None:
        graph = _graph()
        result = select_symbols(graph, parse_criteria("callers = 0"), mode="select")
        self.assertIn("loops_on_self", {s["label"] for s in result.symbols})

    def test_count_and_exists_modes_do_not_materialize_symbols(self) -> None:
        graph = _graph()
        counted = select_symbols(graph, parse_criteria("production_callers = 0"), mode="count")
        self.assertGreater(counted.total, 0)
        self.assertEqual(counted.symbols, [])

        exists = select_symbols(graph, parse_criteria("production_callers = 0"), mode="exists")
        self.assertTrue(exists.exists)
        self.assertEqual(exists.symbols, [])

    def test_exists_is_false_when_nothing_matches(self) -> None:
        graph = _graph()
        result = select_symbols(
            graph, parse_criteria("label contains no_such_symbol"), mode="exists"
        )
        self.assertFalse(result.exists)
        self.assertEqual(result.total, 0)

    def test_excluding_tests_drops_test_symbols_themselves(self) -> None:
        graph = _graph()
        with_tests = select_symbols(graph, parse_criteria("production_callers = 0"), mode="count")
        without = select_symbols(
            graph, parse_criteria("production_callers = 0 and include_tests = false"), mode="count"
        )
        self.assertLess(without.total, with_tests.total)

    def test_limit_truncates_and_says_so(self) -> None:
        graph = _graph()
        result = select_symbols(
            graph, parse_criteria("production_callers = 0", limit=1), mode="select"
        )
        self.assertEqual(len(result.symbols), 1)
        self.assertTrue(result.truncated)
        self.assertGreater(result.total, 1)


class CallerEvidenceTest(unittest.TestCase):
    def test_partial_member_call_resolution_is_reported_as_incomplete(self) -> None:
        # Without this, a zero-caller count reads as proof of dead code even
        # though unresolved member calls emit no `calls` edge at all.
        graph = _graph()
        graph.metadata.update({
            "member_calls_resolved": "992",
            "member_calls_unknown_receiver": "4535",
        })
        complete, detail = caller_evidence_quality(graph)
        self.assertFalse(complete)
        self.assertIn("upper bound", detail)

        result = select_symbols(graph, parse_criteria("production_callers = 0"), mode="count")
        self.assertFalse(result.caller_evidence_complete)

    def test_full_resolution_reports_complete(self) -> None:
        graph = _graph()
        graph.metadata.update({
            "member_calls_resolved": "100",
            "member_calls_unknown_receiver": "0",
        })
        complete, _detail = caller_evidence_quality(graph)
        self.assertTrue(complete)

    def test_graph_without_telemetry_does_not_claim_a_ratio(self) -> None:
        complete, detail = caller_evidence_quality(_graph())
        self.assertTrue(complete)
        self.assertIn("no member-call telemetry", detail)



class ExtendedPredicateTest(unittest.TestCase):
    """Comparison, exclusion, and batch forms (retest G5)."""

    def test_comparison_operators_find_hubs_not_just_islands(self) -> None:
        graph = _graph()
        # `used_in_production` has exactly one caller; `never_called` has none.
        at_least_one = select_symbols(graph, parse_criteria("callers >= 1"), mode="select")
        self.assertIn("used_in_production", {s["label"] for s in at_least_one.symbols})
        self.assertNotIn("never_called", {s["label"] for s in at_least_one.symbols})

        none_at_all = select_symbols(graph, parse_criteria("callers < 1"), mode="select")
        self.assertIn("never_called", {s["label"] for s in none_at_all.symbols})

    def test_not_equal_on_caller_count(self) -> None:
        graph = _graph()
        result = select_symbols(graph, parse_criteria("callers != 0"), mode="select")
        labels = {s["label"] for s in result.symbols}
        self.assertIn("used_in_production", labels)
        self.assertNotIn("never_called", labels)

    def test_path_exclusion_supports_cross_crate_consumer_checks(self) -> None:
        graph = _graph()
        # "does anything outside tests/ use this" -- the island-triage question.
        excluded = select_symbols(
            graph, parse_criteria("path excludes tests/"), mode="select"
        )
        self.assertNotIn("test_run", {s["label"] for s in excluded.symbols})
        # `!=` is accepted as a synonym for the same intent.
        via_ne = select_symbols(graph, parse_criteria("path != tests/"), mode="select")
        self.assertEqual(
            {s["label"] for s in excluded.symbols}, {s["label"] for s in via_ne.symbols}
        )

    def test_batch_label_lookup_returns_caller_columns_for_a_list(self) -> None:
        # One call for many symbols, instead of one round trip per name.
        graph = _graph()
        result = select_symbols(
            graph,
            parse_criteria("label in [used_in_production, never_called]"),
            mode="select",
        )
        by_label = {s["label"]: s for s in result.symbols}
        self.assertEqual(set(by_label), {"used_in_production", "never_called"})
        self.assertEqual(by_label["used_in_production"]["production_callers"], 1)
        self.assertEqual(by_label["never_called"]["production_callers"], 0)

    def test_select_rows_carry_a_short_reference_handle(self) -> None:
        graph = _graph()
        result = select_symbols(graph, parse_criteria("callers >= 0"), mode="select")
        refs = [s["ref"] for s in result.symbols]
        self.assertEqual(refs, list(range(1, len(refs) + 1)))

    def test_receipt_restates_the_operator_not_just_the_number(self) -> None:
        # "callers 0" would not distinguish `= 0` from `<= 0`; the receipt has
        # to be readable back as the question that was asked.
        graph = _graph()
        result = select_symbols(graph, parse_criteria("callers > 3"), mode="count")
        self.assertIn("callers > 3", result.criteria_detail)

    def test_unsupported_operator_still_raises(self) -> None:
        with self.assertRaises(ValueError):
            parse_criteria("callers ~ 3")

if __name__ == "__main__":
    unittest.main()
