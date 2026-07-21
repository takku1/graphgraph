"""Gate primitives.

Each gate is a small, total function from (probe, task) to a
:class:`GateResult`. The default gate function derives the applicable gates from
a task's ground truth so most cases need no bespoke logic. Gates never raise;
an inapplicable gate returns ``NA``.
"""

from __future__ import annotations

from .model import FAIL, NA, PASS, GateResult, ProbeResult, Task


def gate_symbols_present(probe: ProbeResult, symbols: tuple[str, ...], name: str) -> GateResult:
    if not symbols:
        return GateResult(name, NA, "no required symbols")
    missing = [s for s in symbols if not probe.has_symbol(s)]
    if missing:
        return GateResult(name, FAIL, f"missing {missing}")
    return GateResult(name, PASS, f"all {len(symbols)} present")


def gate_symbols_absent(probe: ProbeResult, symbols: tuple[str, ...], name: str) -> GateResult:
    if not symbols:
        return GateResult(name, NA, "no forbidden symbols")
    present = [s for s in symbols if probe.has_symbol(s)]
    if present:
        return GateResult(name, FAIL, f"present {present}")
    return GateResult(name, PASS, "no forbidden symbols in packet")


def gate_call_edges(probe: ProbeResult, edges: tuple[tuple[str, str], ...]) -> GateResult:
    if not edges:
        return GateResult("required_call_edges", NA, "no required call edges")
    missing = [
        f"{source}->{target}"
        for source, target in edges
        if not probe.has_edge("calls", source, target)
    ]
    if missing:
        return GateResult("required_call_edges", FAIL, f"missing {missing}")
    return GateResult("required_call_edges", PASS, f"all {len(edges)} calls edges present")


def gate_no_false_complete(probe: ProbeResult, required: tuple[str, ...]) -> GateResult:
    """A packet may claim complete only if every required symbol is present."""
    if not required:
        return GateResult("no_false_complete", NA, "no completeness contract")
    missing = [s for s in required if not probe.has_symbol(s)]
    if probe.is_complete() and missing:
        return GateResult(
            "no_false_complete",
            FAIL,
            f"state={probe.state} next={probe.next_action} but missing {missing}",
        )
    return GateResult("no_false_complete", PASS, f"state={probe.state} missing={missing or 'none'}")


def gate_expected_completeness(probe: ProbeResult, expected: bool | None) -> GateResult:
    if expected is None:
        return GateResult("completeness", NA, "no expectation")
    actual = probe.is_complete()
    status = PASS if actual == expected else FAIL
    stale = " graph=stale" if probe.gates.get("fresh") is False else ""
    return GateResult(
        "completeness",
        status,
        f"expected_complete={expected} actual_complete={actual} "
        f"(state={probe.state} next={probe.next_action}{stale})",
    )


def gate_token_ceiling(probe: ProbeResult, ceiling: int | None) -> GateResult:
    if ceiling is None:
        return GateResult("token_ceiling", NA, "no ceiling")
    tokens = probe.tokens
    status = PASS if tokens.controlling <= ceiling else FAIL
    suffix = "" if tokens.precise else " (proxy; install tiktoken for the graded count)"
    return GateResult(
        "token_ceiling",
        status,
        f"{tokens.controlling}<= {ceiling} [{tokens.detail}]{suffix}",
    )


def gate_irrelevant_ratio(probe: ProbeResult, task: Task) -> GateResult:
    if not task.check_noise:
        return GateResult("irrelevant_ratio", NA, "not checked for this task")
    relevant = set(task.ground_truth.relevant_labels) | set(task.ground_truth.required_callees)
    ratio, irrelevant = probe.irrelevant_ratio(relevant)
    status = PASS if ratio <= task.max_irrelevant_ratio else FAIL
    preview = irrelevant[:6]
    more = "" if len(irrelevant) <= 6 else f" +{len(irrelevant) - 6} more"
    return GateResult(
        "irrelevant_ratio",
        status,
        f"{ratio:.0%}<= {task.max_irrelevant_ratio:.0%} noise={preview}{more}",
    )


def gate_callers(probe: ProbeResult, task: Task) -> GateResult:
    callers = task.ground_truth.direct_callers
    if not callers:
        return GateResult("direct_callers", NA, "no caller ground truth")
    target = task.ground_truth.direct_call_target
    present = [
        caller
        for caller in callers
        if (
            probe.has_edge("calls", caller, target)
            if target
            else probe.has_symbol(caller)
        )
    ]
    complete_expected = task.expect_complete is True
    if complete_expected:
        missing = [c for c in callers if c not in present]
        status = PASS if not missing else FAIL
        evidence = f"calls->{target}" if target else "nodes"
        return GateResult(
            "direct_callers",
            status,
            f"{len(present)}/{len(callers)} verified by {evidence}, missing {missing or 'none'}",
        )
    # Truncated variant: we only require that it did not claim completeness while
    # dropping callers; caller subset coverage is informational.
    return GateResult("direct_callers", NA, f"{len(present)}/{len(callers)} present (truncated variant)")


def gate_packet_count_parity(probe: ProbeResult) -> GateResult:
    """JSON quality counts and the parsed compact packet must agree."""
    if probe.plain_nodes is None:
        return GateResult("packet_count_parity", NA, "packet was not parsed")
    counts_ok = probe.plain_nodes == probe.nodes and probe.plain_edges == probe.edges
    detail = (
        f"receipt={probe.nodes}/{probe.edges} "
        f"parsed_packet={probe.plain_nodes}/{probe.plain_edges}"
    )
    return GateResult("packet_count_parity", PASS if counts_ok else FAIL, detail)


def default_gates(probe: ProbeResult, task: Task) -> list[GateResult]:
    gt = task.ground_truth
    completeness_contract = gt.required_callees or gt.required_symbols
    gates = [
        gate_symbols_present(probe, gt.required_callees, "callees_present"),
        gate_symbols_present(probe, gt.required_symbols, "symbols_present"),
        gate_call_edges(probe, gt.required_call_edges),
        gate_symbols_absent(probe, gt.forbidden_symbols, "forbidden_absent"),
        gate_no_false_complete(probe, completeness_contract),
        gate_expected_completeness(probe, task.expect_complete),
        gate_callers(probe, task),
        gate_token_ceiling(probe, task.token_ceiling),
        gate_irrelevant_ratio(probe, task),
        gate_packet_count_parity(probe),
    ]
    return [g for g in gates if g.status != NA] or gates
