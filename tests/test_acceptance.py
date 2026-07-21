from __future__ import annotations

import unittest
from pathlib import Path

from graphgraph.acceptance.gates import (
    gate_call_edges,
    gate_expected_completeness,
    gate_irrelevant_ratio,
    gate_no_false_complete,
    gate_token_ceiling,
)
from graphgraph.acceptance.model import (
    FAIL,
    PASS,
    PENDING,
    CaseResult,
    GateResult,
    GroundTruth,
    ProbeResult,
    Task,
)
from graphgraph.acceptance.runner import _parse_packet, run_case
from graphgraph.services.control import GATE_ORDER
from graphgraph.acceptance.scoreboard import summarize, to_markdown
from graphgraph.acceptance.service import select_tasks
from graphgraph.acceptance.tokens import count_tokens
from graphgraph.cli.parser import build_parser

_PACKET = """#gg
[r]
1:calls
2:contains
[n]
1 parse_to_ir @crates/locus-pipeline/src/lib.rs:759 fn parse_to_ir(&self)
2 lift_expr @crates/locus-engine/src/lift.rs:14 pub fn lift_expr(expr: &Expr)
3 schedule_candidates @crates/locus-pipeline/src/lib.rs:243 pub fn schedule_candidates
[e]
1:
1 2
2:
1 3
"""


def _probe(
    *,
    packet: str = _PACKET,
    state: str = "answerable",
    next_action: str = "answer",
    gates: dict[str, bool | None] | None = None,
) -> ProbeResult:
    relations, nodes, edges = _parse_packet(packet)
    if gates is None:
        gates = {name: True for name in GATE_ORDER}
    return ProbeResult(
        task_id="T",
        query="q",
        query_class="direct_lookup",
        state=state,
        next_action=next_action,
        control_raw="ggc1 op=direct_lookup",
        packet=packet,
        nodes=len(nodes),
        edges=len(edges),
        tokens=count_tokens(packet),
        packet_nodes=nodes,
        packet_edges=edges,
        relations=relations,
        facet_coverage={},
        structural_facet_coverage={},
        answerability={"status": state},
        anchors=[{"label": "parse_to_ir"}],
        plain_nodes=len(nodes),
        plain_edges=len(edges),
        graph_identity={},
        query_ms=1.0,
        cache_state="miss",
        raw={},
        gates=gates,
    )


class PacketParserTest(unittest.TestCase):
    def test_parses_relations_nodes_and_edges(self) -> None:
        relations, nodes, edges = _parse_packet(_PACKET)
        self.assertEqual(relations, {"1": "calls", "2": "contains"})
        self.assertEqual([n.label for n in nodes], ["parse_to_ir", "lift_expr", "schedule_candidates"])
        self.assertEqual(nodes[1].path, "crates/locus-engine/src/lift.rs:14")
        self.assertIn(("calls", "1", "2"), [(e.relation, e.src, e.dst) for e in edges])
        self.assertIn(("contains", "1", "3"), [(e.relation, e.src, e.dst) for e in edges])


class GateTest(unittest.TestCase):
    def test_symbol_presence_uses_nodes_not_packet_prose(self) -> None:
        packet = """#gg
[n]
1 unrelated @src/other.py:1 fn lift_expr(value)
[e]
"""
        self.assertFalse(_probe(packet=packet).has_symbol("lift_expr"))

    def test_required_calls_are_typed_edges(self) -> None:
        self.assertEqual(
            gate_call_edges(_probe(), (("parse_to_ir", "lift_expr"),)).status,
            PASS,
        )
        self.assertEqual(
            gate_call_edges(_probe(), (("parse_to_ir", "schedule_candidates"),)).status,
            FAIL,
        )

    def test_false_complete_is_caught(self) -> None:
        probe = _probe()  # answerable/answer but missing formula.rs
        gate = gate_no_false_complete(probe, ("lift_expr", "formula.rs"))
        self.assertEqual(gate.status, FAIL)
        self.assertIn("formula.rs", gate.detail)

    def test_complete_is_allowed_when_required_present(self) -> None:
        probe = _probe()
        gate = gate_no_false_complete(probe, ("parse_to_ir", "lift_expr"))
        self.assertEqual(gate.status, PASS)

    def test_expected_incomplete_matches(self) -> None:
        probe = _probe(state="incomplete", next_action="retry_narrow")
        self.assertEqual(gate_expected_completeness(probe, False).status, PASS)
        self.assertEqual(gate_expected_completeness(probe, True).status, FAIL)

    def test_stale_graph_alone_does_not_deny_completeness(self) -> None:
        # A graph older than the newest source edit fails the `fresh` gate,
        # and choose_next_action short-circuits to "refresh" before consulting
        # any retrieval gate. That must not read as "retrieval was
        # incomplete": found live against a stale sibling-repo graph, where a
        # reverse lookup returned 8/8 verified callers yet scored as a
        # completeness failure.
        gates = {name: True for name in GATE_ORDER}
        gates["fresh"] = False
        probe = _probe(next_action="refresh", gates=gates)
        self.assertTrue(probe.stale_only())
        self.assertTrue(probe.is_complete())
        gate = gate_expected_completeness(probe, True)
        self.assertEqual(gate.status, PASS)
        self.assertIn("graph=stale", gate.detail)

    def test_stale_graph_does_not_mask_a_real_retrieval_failure(self) -> None:
        # The converse, and the reason staleness cannot simply be ignored: a
        # failing retrieval gate must still deny completeness even while the
        # graph is also stale, or `fresh` becomes a blanket amnesty.
        gates = {name: True for name in GATE_ORDER}
        gates["fresh"] = False
        gates["evidence"] = False
        probe = _probe(next_action="refresh", gates=gates)
        self.assertFalse(probe.stale_only())
        self.assertFalse(probe.is_complete())

    def test_false_complete_gate_stays_armed_on_a_stale_graph(self) -> None:
        # gate_no_false_complete can only fail when is_complete() is True, so
        # pinning completeness to False under staleness silently disarmed it.
        gates = {name: True for name in GATE_ORDER}
        gates["fresh"] = False
        probe = _probe(next_action="refresh", gates=gates)
        gate = gate_no_false_complete(probe, ("lift_expr", "formula.rs"))
        self.assertEqual(gate.status, FAIL)
        self.assertIn("formula.rs", gate.detail)

    def test_token_worse_value_controls_and_proxy_is_labelled(self) -> None:
        count = count_tokens("alpha beta gamma")
        self.assertGreater(count.controlling, 0)
        gate = gate_token_ceiling(_probe(), 1)
        self.assertEqual(gate.status, FAIL)

    def test_containment_siblings_count_as_irrelevant(self) -> None:
        # schedule_candidates is reachable only by `contains`, not a callee.
        task = Task(
            id="T",
            title="t",
            dimension="D6",
            severity="P1",
            query="q",
            check_noise=True,
            ground_truth=GroundTruth(relevant_labels=("parse_to_ir", "lift_expr")),
        )
        gate = gate_irrelevant_ratio(_probe(), task)
        self.assertEqual(gate.status, FAIL)
        self.assertIn("schedule_candidates", gate.detail)


class ScoreboardTest(unittest.TestCase):
    def test_release_floor_blocks_on_blocking_failure(self) -> None:
        task = Task(id="T", title="t", dimension="D6", severity="P1", query="q")
        blocked = CaseResult(task=task, probe=None, gates=[], error="boom")
        summary = summarize([blocked])
        self.assertTrue(summary["release_blocked"])
        self.assertEqual(summary["release_floor"], "blocked")

    def test_pending_cases_are_not_counted_as_passing(self) -> None:
        task = Task(id="T", title="t", dimension="D6", severity="P1", query="q", status="pending")
        case = CaseResult(task=task, probe=None, gates=[])
        self.assertEqual(case.status, PENDING)
        summary = summarize([case])
        self.assertEqual(summary["passed"], 0)
        self.assertFalse(summary["release_ready"])
        self.assertEqual(summary["release_floor"], "pending")
        self.assertEqual(summary["blocking_pending"], ["T"])

    def test_pending_gate_cannot_clear_release_floor(self) -> None:
        task = Task(id="T", title="t", dimension="D8", severity="P0", query="q")
        case = CaseResult(
            task=task,
            probe=None,
            gates=[
                GateResult("static_evidence", PASS, "present"),
                GateResult("live_execution", PENDING, "not run"),
            ],
        )
        summary = summarize([case])
        self.assertEqual(case.status, PENDING)
        self.assertEqual(summary["release_floor"], "pending")
        self.assertFalse(summary["release_ready"])
        markdown = to_markdown([case])
        self.assertIn("live_execution", markdown)
        self.assertIn("not run", markdown)


class AcceptanceCliTest(unittest.TestCase):
    def test_native_platform_parser_exposes_acceptance(self) -> None:
        args = build_parser().parse_args(
            ["platform", "acceptance", "--repo", "../locus", "--case", "GG10-LC-003", "--json"]
        )
        self.assertEqual(args.platform_action, "acceptance")
        self.assertEqual(args.case, ["GG10-LC-003"])
        self.assertTrue(args.as_json)

    def test_native_platform_parser_exposes_quality_gate(self) -> None:
        args = build_parser().parse_args(["platform", "quality", "--json"])
        self.assertEqual(args.platform_action, "quality")
        self.assertTrue(args.as_json)

    def test_unknown_case_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown acceptance case"):
            select_tasks(("GG10-LC-NOT-REAL",))


class SecretBoundaryTest(unittest.TestCase):
    """GG10-LC-010 / D2: hermetic, no target repo needed."""

    def test_secret_canary_never_leaves_the_scan_boundary(self) -> None:
        from graphgraph.acceptance.boundary import CANARY, run_secret_boundary

        task = Task(id="GG10-LC-010", title="t", dimension="D2", severity="P0", query="q")
        case = run_secret_boundary(task)
        failing = [g for g in case.gates if g.status == FAIL]
        self.assertEqual(case.status, PASS, failing)
        # The single most important property: the canary reaches no artifact.
        canary_gate = next(g for g in case.gates if g.name == "canary_absent")
        self.assertEqual(canary_gate.status, PASS)
        self.assertTrue(CANARY.startswith("GG_SECRET_CANARY"))


class TransportParityTest(unittest.TestCase):
    """GG10-LC-011 / D14: hermetic, exercises CLI-plain, CLI-JSON, and MCP."""

    def test_transports_agree_on_the_logical_packet(self) -> None:
        from graphgraph.acceptance.parity import run_transport_parity

        task = Task(id="GG10-LC-011", title="t", dimension="D14", severity="P1", query="q")
        case = run_transport_parity(task)
        failing = [g for g in case.gates if g.status == FAIL]
        self.assertEqual(case.status, PASS, failing)
        for name in ("packet_parity", "node_edge_parity", "status_parity"):
            self.assertEqual(next(g for g in case.gates if g.name == name).status, PASS)


class IncrementalEditTest(unittest.TestCase):
    """GG10-LC-007 / D13: hermetic incremental-vs-rebuild equivalence."""

    def test_incremental_splice_equals_clean_rebuild(self) -> None:
        from graphgraph.acceptance.incremental import run_incremental_edit

        task = Task(id="GG10-LC-007", title="t", dimension="D13", severity="P1", query="q")
        case = run_incremental_edit(task)
        failing = [g for g in case.gates if g.status == FAIL]
        self.assertEqual(case.status, PASS, failing)
        self.assertEqual(
            next(g for g in case.gates if g.name == "incremental_equals_rebuild").status, PASS
        )


class DocEnumerationTest(unittest.TestCase):
    """GG10-LC-005 / D9+D14: hermetic. Locks the fixed plain/JSON validation parity."""

    def test_plain_and_json_validation_agree(self) -> None:
        from graphgraph.acceptance.docs_case import run_doc_enumeration

        task = Task(
            id="GG10-LC-005", title="t", dimension="D9/D14", severity="P1",
            query="q", token_ceiling=900,
        )
        case = run_doc_enumeration(task)
        parity = next(g for g in case.gates if g.name == "validation_parity")
        populated = next(g for g in case.gates if g.name == "packet_populated")
        self.assertEqual(parity.status, PASS, parity.detail)
        self.assertEqual(populated.status, PASS, populated.detail)


class ScopeInferenceTest(unittest.TestCase):
    """GG10-LC-006 / D5+D7: hermetic. Locks that the production flow is retrievable."""

    def test_production_flow_is_present_and_bounded(self) -> None:
        from graphgraph.acceptance.scope_case import run_scope_inference

        task = Task(
            id="GG10-LC-006", title="t", dimension="D5/D7", severity="P2",
            query="q", token_ceiling=1200,
        )
        case = run_scope_inference(task)
        flow = next(g for g in case.gates if g.name == "production_flow_present")
        tokens = next(g for g in case.gates if g.name == "token_ceiling")
        self.assertEqual(flow.status, PASS, flow.detail)
        self.assertEqual(tokens.status, PASS, tokens.detail)


_LOCUS_GRAPH = Path(__file__).resolve().parents[1].parent / "locus" / ".graphgraph" / "graph.gg"


@unittest.skipUnless(_LOCUS_GRAPH.exists(), "Locus graph not present")
class LocusRegressionTest(unittest.TestCase):
    """Guards behaviors already verified correct against live Locus."""

    def test_reverse_lookup_returns_all_direct_callers_with_budget(self) -> None:
        from graphgraph.acceptance.tasks import CANONICAL_TASKS

        task = next(t for t in CANONICAL_TASKS if t.id == "GG10-LC-004b")
        case = run_case(task, _LOCUS_GRAPH.parents[1], _LOCUS_GRAPH)
        self.assertEqual(case.status, PASS, [g for g in case.gates if g.status == FAIL])

    def test_truncated_reverse_lookup_reports_incomplete(self) -> None:
        from graphgraph.acceptance.tasks import CANONICAL_TASKS

        task = next(t for t in CANONICAL_TASKS if t.id == "GG10-LC-004a")
        case = run_case(task, _LOCUS_GRAPH.parents[1], _LOCUS_GRAPH)
        self.assertEqual(case.status, PASS, [g for g in case.gates if g.status == FAIL])

    def test_focused_test_recommendation_emits_commands_with_covers(self) -> None:
        # Locks the fixed LC-001 command generation (exact label + covers path).
        from graphgraph.acceptance.tasks import CANONICAL_TASKS

        task = next(t for t in CANONICAL_TASKS if t.id == "GG10-LC-001")
        case = run_case(task, _LOCUS_GRAPH.parents[1], _LOCUS_GRAPH)
        by_name = {g.name: g for g in case.gates}
        self.assertEqual(by_name["commands_emitted"].status, PASS, by_name["commands_emitted"].detail)
        self.assertEqual(by_name["covers_present"].status, PASS, by_name["covers_present"].detail)


if __name__ == "__main__":
    unittest.main()
