"""Render acceptance results as a Markdown/JSON scoreboard.

The release grade is controlled by the ``release_floor`` rule from the spec: a
high pass-rate cannot hide an open P0/P1 failure.
"""

from __future__ import annotations

from .model import FAIL, PASS, PENDING, CaseResult

_STATUS_MARK = {PASS: "PASS", FAIL: "FAIL", PENDING: "PENDING", "na": "NA"}
_BLOCKING = {"P0", "P1"}


def summarize(cases: list[CaseResult]) -> dict:
    graded = [c for c in cases if c.status in (PASS, FAIL)]
    passed = [c for c in graded if c.status == PASS]
    blocking_failures = [
        c for c in graded if c.status == FAIL and c.task.severity in _BLOCKING
    ]
    blocking_pending = [
        c for c in cases if c.status == PENDING and c.task.severity in _BLOCKING
    ]
    release_floor = (
        "blocked"
        if blocking_failures
        else "pending"
        if blocking_pending
        else "clear"
    )
    return {
        "total": len(cases),
        "active": len(graded),
        "pending": sum(1 for c in cases if c.status == PENDING),
        "passed": len(passed),
        "failed": len(graded) - len(passed),
        "pass_rate": round(len(passed) / len(graded), 4) if graded else None,
        "release_blocked": bool(blocking_failures),
        "release_ready": release_floor == "clear",
        "release_floor": release_floor,
        "blocking_failures": [c.task.id for c in blocking_failures],
        "blocking_pending": [c.task.id for c in blocking_pending],
    }


def to_markdown(cases: list[CaseResult], *, environment: dict | None = None) -> str:
    s = summarize(cases)
    lines = ["# GraphGraph acceptance scoreboard", ""]
    if environment:
        lines += [
            f"- repo: `{environment.get('repo')}`",
            f"- graph: `{environment.get('graph_hash', 'n/a')}` "
            f"({environment.get('graph_files', '?')} files)",
            f"- tokens: {environment.get('token_mode')}",
            "",
        ]
    verdict = {
        "blocked": "RELEASE BLOCKED",
        "pending": "BLOCKING EVIDENCE PENDING",
        "clear": "RELEASE FLOOR CLEAR",
    }[s["release_floor"]]
    rate = "n/a" if s["pass_rate"] is None else f"{s['pass_rate']:.0%}"
    lines += [
        f"**release_floor: {s['release_floor'].upper()}** ({verdict})  ",
        f"active {s['active']} | passed {s['passed']} | failed {s['failed']} "
        f"| pending {s['pending']} | pass-rate {rate}",
        "",
        "| Case | Dim | Sev | Status | Failing / pending gates |",
        "| --- | --- | --- | --- | --- |",
    ]
    for case in cases:
        mark = _STATUS_MARK.get(case.status, case.status.upper())
        if case.error:
            fails = f"error: {case.error}"
        else:
            open_gates = [
                g.name for g in case.gates if g.status in {FAIL, PENDING}
            ]
            fails = ", ".join(open_gates) or "-"
        lines.append(
            f"| {case.task.id} | {case.task.dimension} | {case.task.severity} "
            f"| {mark} | {fails} |"
        )
    lines.append("")
    # Per-gate evidence for active cases.
    for case in cases:
        if not case.gates:
            continue
        lines.append(f"### {case.task.id} — {case.task.title}")
        if case.probe is not None:
            p = case.probe
            lines.append(
                f"`{p.control_raw}`  \n"
                f"state={p.state} tokens={p.tokens.detail} "
                f"nodes={p.nodes}/{p.edges} time={p.query_ms}ms"
            )
        for g in case.gates:
            lines.append(f"- {_STATUS_MARK.get(g.status, g.status)} **{g.name}** — {g.detail}")
        lines.append("")
    return "\n".join(lines)


def to_json(cases: list[CaseResult], *, environment: dict | None = None) -> dict:
    return {
        "environment": environment or {},
        "summary": summarize(cases),
        "cases": [
            {
                "id": c.task.id,
                "title": c.task.title,
                "dimension": c.task.dimension,
                "severity": c.task.severity,
                "status": c.status,
                "reference": c.task.reference,
                "error": c.error,
                "control": c.probe.control_raw if c.probe else "",
                "tokens": c.probe.tokens.controlling if c.probe else None,
                "probe": (
                    {
                        "query": c.probe.query,
                        "query_class": c.probe.query_class,
                        "state": c.probe.state,
                        "next_action": c.probe.next_action,
                        "nodes": c.probe.nodes,
                        "edges": c.probe.edges,
                        "query_ms": c.probe.query_ms,
                        "cache_state": c.probe.cache_state,
                        "graph_identity": c.probe.graph_identity,
                    }
                    if c.probe
                    else None
                ),
                "gates": [
                    {"name": g.name, "status": g.status, "detail": g.detail}
                    for g in c.gates
                ],
            }
            for c in cases
        ],
    }
