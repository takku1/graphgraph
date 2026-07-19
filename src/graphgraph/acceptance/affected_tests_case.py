"""Affected-tests + executable-command cases (GG10-LC-001 / GG10-LC-002, D8).

Queries the real target repo for affected-test recommendations, checks the static
D8 contract (a focused command is recommended and carries a covers receipt), and
— only when a runner is available and execution is explicitly enabled — runs each
command and proves it selects at least one test. A zero-selected command is a
failed recommendation.

Execution is opt-in (``GG_ACCEPT_EXEC=1`` plus the runner on PATH) so the shared
board never launches a compiler unexpectedly. When execution is skipped, the
selection gate is ``PENDING`` and therefore cannot produce a clear release
floor.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from graphgraph.services.native import render_native_context

from .model import FAIL, PASS, PENDING, CaseResult, GateResult, Task
from .test_exec import ZERO_SELECTED, run_command, tool_available


def _covers_ok(provenance: list) -> tuple[bool, str]:
    if not provenance:
        return False, "no command_provenance"
    for entry in provenance:
        tests = entry.get("tests") or []
        if not tests:
            return False, f"empty covers for {entry.get('command')!r}"
        if not any((t.get("root_paths") or []) for t in tests):
            return False, f"no source->test path for {entry.get('command')!r}"
    return True, f"{len(provenance)} command(s) carry a covers path"


def _test_items(affected: dict) -> list[dict]:
    return [
        item
        for key in ("direct", "transitive")
        for item in (affected.get(key) or [])
        if isinstance(item, dict)
    ]


def _evidence_relations(items: list[dict]) -> set[str]:
    return {
        str(edge.get("type", ""))
        for item in items
        for path in (item.get("root_paths") or [])
        for edge in (path.get("edges") or [])
        if isinstance(edge, dict)
    }


def run_affected_tests(task: Task, repo: Path, graph_path: Path | None = None) -> CaseResult:
    graph_path = graph_path or (repo / ".graphgraph" / "graph.gg")
    rendered, _status = render_native_context(
        query=task.query,
        query_class="affected_tests",
        directory=repo,
        graph_path=graph_path,
        json_output=True,
        json_details=True,
        show_anchors=True,
        max_nodes=task.max_nodes or 40,
    )
    payload = json.loads(rendered)
    affected = (payload.get("retrieval") or {}).get("affected_tests") or {}
    commands = [c for c in (affected.get("commands") or []) if c]
    provenance = affected.get("command_provenance") or []
    items = _test_items(affected)

    gates: list[GateResult] = [
        GateResult(
            "commands_emitted",
            PASS if commands else FAIL,
            f"{len(commands)} focused command(s): {commands[:3]}" if commands
            else "no focused test command recommended",
        )
    ]
    required_tests = task.ground_truth.required_tests
    if required_tests:
        labels = {str(item.get("label", "")) for item in items}
        missing_tests = [label for label in required_tests if label not in labels]
        gates.append(
            GateResult(
                "required_tests",
                PASS if not missing_tests else FAIL,
                f"present={sorted(labels & set(required_tests))} "
                f"missing={missing_tests or 'none'}",
            )
        )
    required_relations = task.ground_truth.required_evidence_relations
    if required_relations:
        relations = _evidence_relations(items)
        missing_relations = [
            relation for relation in required_relations if relation not in relations
        ]
        gates.append(
            GateResult(
                "type_reference_evidence",
                PASS if not missing_relations else FAIL,
                f"relations={sorted(relations)} missing={missing_relations or 'none'}",
            )
        )

    if not commands:
        # The static contract already fails; nothing to execute (e.g. LC-002).
        return CaseResult(task=task, probe=None, gates=gates)

    covers_ok, covers_detail = _covers_ok(provenance)
    gates.append(GateResult("covers_present", PASS if covers_ok else FAIL, covers_detail))

    exec_enabled = os.environ.get("GG_ACCEPT_EXEC") == "1"
    runner_available = tool_available(commands[0])
    if not (exec_enabled and runner_available):
        gates.append(
            GateResult(
                "command_selects_test",
                PENDING,
                f"execution skipped (set GG_ACCEPT_EXEC=1; runner_on_path={runner_available})",
            )
        )
        return CaseResult(task=task, probe=None, gates=gates)

    outcomes = [run_command(command, repo, timeout=900) for command in commands]
    zero = [o for o in outcomes if o.classification == ZERO_SELECTED]
    selecting = [o for o in outcomes if o.selects_test]
    gates.append(
        GateResult(
            "command_selects_test",
            PASS if len(selecting) == len(outcomes) else FAIL,
            f"{len(selecting)}/{len(outcomes)} select >=1 test; "
            f"zero_selected={[o.command for o in zero]}",
        )
    )
    return CaseResult(task=task, probe=None, gates=gates)
