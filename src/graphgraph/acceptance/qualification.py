"""Same-named member qualification acceptance case (GG10-LC-009 / D5).

Locus defines ``count_ops`` twice -- on ``Expr`` (canonical.rs) and on
``Condition`` (display.rs). A qualified query must land on exactly the named
owner, an unqualified one must not silently pick a winner, and no call edge
may attribute a call to the wrong owner.

The unqualified half is the one that matters. Returning one owner with full
confidence for a name that has two is a wrong-answer mode: the caller cannot
tell a decisive answer from an arbitrary pick.
"""

from __future__ import annotations

import json
from pathlib import Path

from graphgraph.io import load_any
from graphgraph.services.native import render_native_context

from .model import FAIL, NA, PASS, CaseResult, GateResult, Task

# Ground truth, verified against Locus source.
_METHOD = "count_ops"
_OWNERS = {
    "Expr": "canonical.rs",
    "Condition": "display.rs",
}


def _query(query: str, repo: Path, graph_path: Path) -> dict:
    rendered, _status = render_native_context(
        query=query,
        query_class="direct_lookup",
        directory=repo,
        graph_path=graph_path,
        json_output=True,
        json_details=True,
        show_anchors=True,
        max_nodes=12,
    )
    return json.loads(rendered)


def _anchor_paths(payload: dict) -> list[str]:
    return [str(a.get("path", "")) for a in payload.get("anchors", []) or []]


def run_member_qualification(
    task: Task,
    repo: Path,
    graph_path: Path | None = None,
) -> CaseResult:
    if graph_path is None or not Path(graph_path).exists():
        return CaseResult(
            task=task,
            probe=None,
            gates=[GateResult("graph_present", NA, "no graph available")],
        )

    graph = load_any(Path(graph_path))
    method_nodes = {
        nid: node
        for nid, node in graph.nodes.items()
        if node.label == _METHOD and node.kind == "method"
    }
    owners_present = {
        owner: nid
        for owner, filename in _OWNERS.items()
        for nid, node in method_nodes.items()
        if filename in (node.path or "")
    }

    gates: list[GateResult] = [
        GateResult(
            "both_owners_indexed",
            PASS if len(owners_present) == len(_OWNERS) else FAIL,
            f"found {sorted(owners_present)} of {sorted(_OWNERS)}",
        )
    ]
    if len(owners_present) != len(_OWNERS):
        return CaseResult(task=task, probe=None, gates=gates)

    # 1. A qualified query must land on exactly the named owner.
    for owner, filename in _OWNERS.items():
        payload = _query(f"{owner}::{_METHOD}", repo, Path(graph_path))
        paths = _anchor_paths(payload)
        hit = bool(paths) and filename in paths[0]
        gates.append(GateResult(
            f"qualified_resolves_{owner}",
            PASS if hit else FAIL,
            f"{owner}::{_METHOD} -> {paths[:2] or 'no anchor'} (want {filename})",
        ))

    # 2. An unqualified query must not present one owner as the answer.
    payload = _query(_METHOD, repo, Path(graph_path))
    paths = _anchor_paths(payload)
    matched_owner_files = {
        filename for filename in _OWNERS.values() if any(filename in p for p in paths)
    }
    retrieval = payload.get("retrieval", {}) or {}
    declared = bool(retrieval.get("ambiguous")) or bool(
        (payload.get("routing", {}) or {}).get("ambiguous")
    )
    clarified = len(matched_owner_files) > 1
    gates.append(GateResult(
        "unqualified_declares_ambiguity",
        PASS if (declared or clarified) else FAIL,
        f"bare {_METHOD!r} -> owners in anchors={sorted(matched_owner_files)} "
        f"declared_ambiguous={declared}; must surface both owners or flag ambiguity",
    ))

    # 3. No call edge may attribute a call to the wrong owner. Receiver
    #    evidence names the type it resolved, so a mismatch is detectable.
    mixed: list[str] = []
    for edge in graph.edges:
        if edge.type != "calls" or edge.target not in method_nodes:
            continue
        evidence = edge.evidence or ""
        if ":" not in evidence:
            continue
        resolved_type = evidence.rsplit(":", 1)[1].strip()
        if resolved_type not in _OWNERS:
            continue
        target_path = method_nodes[edge.target].path or ""
        if _OWNERS[resolved_type] not in target_path:
            mixed.append(f"{edge.source}->{edge.target} claimed {resolved_type}")
    gates.append(GateResult(
        "no_owner_mixing",
        PASS if not mixed else FAIL,
        f"{len(mixed)} mis-attributed call edge(s)" + (f": {mixed[:3]}" if mixed else ""),
    ))

    return CaseResult(task=task, probe=None, gates=gates)
