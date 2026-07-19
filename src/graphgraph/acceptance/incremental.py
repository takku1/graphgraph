"""Incremental edit-loop acceptance case (GG10-LC-007 / D13).

Builds a graph, edits one file to add a new caller, splices the change with
``changed_paths``, and proves the incremental result is byte-identical to a clean
rebuild from the edited state while the splice touched only the changed file.
Self-contained, so it does not depend on the target repository.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from graphgraph.services.native import render_native_context

from .model import FAIL, PASS, CaseResult, GateResult, Task
from .runner import _parse_packet

_QUERY = "What directly calls normalize_value?"

_V1 = (
    "def normalize_value(x):\n    return x + 1\n\n"
    "def public_entry():\n    return normalize_value(1)\n\n"
    "def other_entry():\n    return normalize_value(2)\n"
)
# One-file edit: adds a third caller.
_V2 = _V1 + "\ndef third_entry():\n    return normalize_value(3)\n"


def _query(directory: Path, graph_path: Path, *, rebuild: bool = False, changed: tuple[str, ...] = ()):
    rendered, status = render_native_context(
        query=_QUERY,
        query_class="reverse_lookup",
        directory=directory,
        graph_path=graph_path,
        json_output=True,
        json_details=True,
        show_anchors=True,
        max_nodes=20,
        rebuild=rebuild,
        changed_paths=changed,
    )
    return json.loads(rendered), status


def _callers(packet: str) -> set[str]:
    _relations, nodes, _edges = _parse_packet(packet)
    wanted = {"public_entry", "other_entry", "third_entry"}
    return {n.label for n in nodes if n.label in wanted}


def run_incremental_edit(task: Task) -> CaseResult:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp) / "base"
        base.mkdir()
        (base / "app.py").write_text(_V1, encoding="utf-8")
        base_graph = base / ".graphgraph" / "graph.gg"

        # Initial build + baseline (two callers).
        baseline, _s0 = _query(base, base_graph)
        baseline_callers = _callers(str(baseline.get("packet", "")))

        # One-file edit, then an explicit incremental splice.
        (base / "app.py").write_text(_V2, encoding="utf-8")
        incremental, inc_status = _query(base, base_graph, changed=("app.py",))
        inc_packet = str(incremental.get("packet", ""))

        # Clean rebuild from the edited state in a fresh directory.
        clean = Path(tmp) / "clean"
        clean.mkdir()
        (clean / "app.py").write_text(_V2, encoding="utf-8")
        clean_graph = clean / ".graphgraph" / "graph.gg"
        rebuilt, _s2 = _query(clean, clean_graph, rebuild=True)
        clean_packet = str(rebuilt.get("packet", ""))

        inc_callers = _callers(inc_packet)
        clean_callers = _callers(clean_packet)
        splice_scope = set(inc_status.changed_paths)

        gates = [
            GateResult(
                "edit_reflected",
                PASS if "third_entry" in inc_callers and "third_entry" not in baseline_callers else FAIL,
                f"baseline={sorted(baseline_callers)} after_splice={sorted(inc_callers)}",
            ),
            GateResult(
                "incremental_equals_rebuild",
                PASS if inc_packet.strip() == clean_packet.strip() else FAIL,
                "byte-identical to clean rebuild"
                if inc_packet.strip() == clean_packet.strip()
                else f"splice={sorted(inc_callers)} rebuild={sorted(clean_callers)}",
            ),
            GateResult(
                "splice_scoped",
                PASS if splice_scope == {"app.py"} and not inc_status.deleted_paths else FAIL,
                f"changed={sorted(splice_scope)} deleted={list(inc_status.deleted_paths)}",
            ),
        ]
        return CaseResult(task=task, probe=None, gates=gates)
