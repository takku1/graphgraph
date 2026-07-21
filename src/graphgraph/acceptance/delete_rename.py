"""Delete-and-rename acceptance case (GG10-LC-008 / D13).

Builds a graph, renames one source file and deletes another in the same
splice, and proves the old paths leave no ghost nodes behind, the renamed
path carries its definitions and relations across, the receipts name exactly
the paths that moved, and the spliced graph still equals a clean rebuild.

Self-contained like :mod:`incremental`, so it does not depend on the target
repository.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from graphgraph.services.native import render_native_context

from .model import FAIL, PASS, CaseResult, GateResult, Task
from .runner import _parse_packet

_QUERY = "What directly calls normalize_value?"

# core.py defines the target and one caller; it gets renamed to engine.py.
_CORE = (
    "def normalize_value(x):\n    return x + 1\n\n"
    "def core_entry():\n    return normalize_value(1)\n"
)
# helper.py adds a second caller; it gets deleted outright.
_HELPER = "from core import normalize_value\n\n\ndef helper_entry():\n    return normalize_value(2)\n"
# Untouched throughout, so it anchors "the splice touched only what moved".
_STABLE = "from core import normalize_value\n\n\ndef stable_entry():\n    return normalize_value(3)\n"


def _query(
    directory: Path,
    graph_path: Path,
    *,
    rebuild: bool = False,
    changed: tuple[str, ...] = (),
    deleted: tuple[str, ...] = (),
):
    rendered, status = render_native_context(
        query=_QUERY,
        query_class="reverse_lookup",
        directory=directory,
        graph_path=graph_path,
        json_output=True,
        json_details=True,
        show_anchors=True,
        max_nodes=30,
        rebuild=rebuild,
        changed_paths=changed,
        deleted_paths=deleted,
    )
    return json.loads(rendered), status


def _nodes(packet: str):
    _relations, nodes, _edges = _parse_packet(packet)
    return nodes


def _labels(packet: str) -> set[str]:
    return {n.label for n in _nodes(packet)}


def _paths(packet: str) -> set[str]:
    """Path fragments present in the packet, minus any line suffix."""
    return {n.path.split(":", 1)[0] for n in _nodes(packet) if n.path}


def run_delete_rename(task: Task) -> CaseResult:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp) / "base"
        base.mkdir()
        (base / "core.py").write_text(_CORE, encoding="utf-8")
        (base / "helper.py").write_text(_HELPER, encoding="utf-8")
        (base / "stable.py").write_text(_STABLE, encoding="utf-8")
        base_graph = base / ".graphgraph" / "graph.gg"

        baseline, _s0 = _query(base, base_graph)
        baseline_packet = str(baseline.get("packet", ""))
        baseline_labels = _labels(baseline_packet)

        # Rename core.py -> engine.py and delete helper.py in one splice.
        (base / "engine.py").write_text(_CORE, encoding="utf-8")
        (base / "core.py").unlink()
        (base / "helper.py").unlink()
        spliced, splice_status = _query(
            base,
            base_graph,
            changed=("engine.py",),
            deleted=("core.py", "helper.py"),
        )
        spliced_packet = str(spliced.get("packet", ""))
        spliced_labels = _labels(spliced_packet)
        spliced_paths = _paths(spliced_packet)

        # Clean rebuild from the post-rename state.
        clean = Path(tmp) / "clean"
        clean.mkdir()
        (clean / "engine.py").write_text(_CORE, encoding="utf-8")
        (clean / "stable.py").write_text(_STABLE, encoding="utf-8")
        clean_graph = clean / ".graphgraph" / "graph.gg"
        rebuilt, _s2 = _query(clean, clean_graph, rebuild=True)
        clean_packet = str(rebuilt.get("packet", ""))

        ghosts = {p for p in spliced_paths if p in ("core.py", "helper.py")}
        ghost_labels = {label for label in ("helper_entry",) if label in spliced_labels}
        receipt_changed = set(splice_status.changed_paths)
        receipt_deleted = set(splice_status.deleted_paths)

        gates = [
            GateResult(
                "baseline_populated",
                PASS if {"core_entry", "helper_entry", "stable_entry"} <= baseline_labels else FAIL,
                f"baseline callers={sorted(baseline_labels & {'core_entry', 'helper_entry', 'stable_entry'})}",
            ),
            GateResult(
                "no_ghost_nodes",
                PASS if not ghosts and not ghost_labels else FAIL,
                f"stale paths={sorted(ghosts) or 'none'} stale labels={sorted(ghost_labels) or 'none'}",
            ),
            GateResult(
                "renamed_path_carries_definitions",
                PASS if "engine.py" in spliced_paths and "core_entry" in spliced_labels else FAIL,
                f"engine.py present={'engine.py' in spliced_paths} core_entry={'core_entry' in spliced_labels}",
            ),
            GateResult(
                "untouched_file_survives",
                PASS if "stable_entry" in spliced_labels else FAIL,
                f"stable_entry present={'stable_entry' in spliced_labels}",
            ),
            GateResult(
                "receipts_exact",
                PASS
                if receipt_changed == {"engine.py"} and receipt_deleted == {"core.py", "helper.py"}
                else FAIL,
                f"changed={sorted(receipt_changed)} deleted={sorted(receipt_deleted)}",
            ),
            GateResult(
                "incremental_equals_rebuild",
                PASS if spliced_packet.strip() == clean_packet.strip() else FAIL,
                "byte-identical to clean rebuild"
                if spliced_packet.strip() == clean_packet.strip()
                else f"splice={sorted(spliced_labels)} rebuild={sorted(_labels(clean_packet))}",
            ),
        ]
        return CaseResult(task=task, probe=None, gates=gates)
