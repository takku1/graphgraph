"""Document enumeration + validation-parity case (GG10-LC-005 / D9+D14).

Builds a doc with eight numbered stages, answers a scoped enumeration query, and
checks two things the usage report found broken: the packet grounds to the doc,
and plain-mode validation agrees with JSON-mode validation on node/edge counts
(the reported defect was plain reporting ``nodes=0`` while JSON reported a
populated packet). Self-contained, so it does not depend on the target repo.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from graphgraph.packets.validation import validate_any
from graphgraph.services.native import render_native_context

from .model import FAIL, PASS, CaseResult, GateResult, Task
from .tokens import count_tokens

_STAGE_COUNT = 8
_QUERY = "According to docs/pipeline.md, what stages form the pipeline?"


def _write_fixture(root: Path) -> None:
    docs = root / "docs"
    docs.mkdir()
    stages = "\n\n".join(
        f"## Stage {n}: phase_{n}\n\nStage {n} performs the phase_{n} step of the pipeline."
        for n in range(1, _STAGE_COUNT + 1)
    )
    (docs / "pipeline.md").write_text(
        f"# Backbone pipeline\n\nThe pipeline forms {_STAGE_COUNT} stages.\n\n{stages}\n",
        encoding="utf-8",
    )


def _stages_present(text: str) -> set[int]:
    return {n for n in range(1, _STAGE_COUNT + 1) if f"Stage {n}" in text or f"phase_{n}" in text}


def run_doc_enumeration(task: Task) -> CaseResult:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write_fixture(root)
        graph_path = root / ".graphgraph" / "graph.gg"

        json_raw, _s = render_native_context(
            query=_QUERY,
            query_class="doc_summary",
            directory=root,
            graph_path=graph_path,
            json_output=True,
            json_details=True,
            show_anchors=True,
            max_nodes=30,
        )
        payload = json.loads(json_raw)
        packet = str(payload.get("packet", ""))
        status = str((payload.get("retrieval") or {}).get("answerability", {}).get("status", ""))

        plain_out, _s2 = render_native_context(
            query=_QUERY,
            query_class="doc_summary",
            directory=root,
            graph_path=graph_path,
            json_output=False,
            show_anchors=False,
            max_nodes=30,
        )

        v_json = validate_any(packet)
        v_plain = validate_any(plain_out)  # exactly what the CLI validates in plain mode

        parity_ok = (
            v_json.node_count == v_plain.node_count
            and v_json.edge_count == v_plain.edge_count
            and v_json.ok == v_plain.ok
        )
        present = _stages_present(packet)
        complete = status in ("answerable", "complete")

        gates = [
            GateResult(
                "packet_populated",
                PASS if v_json.node_count > 0 else FAIL,
                f"json validation nodes={v_json.node_count} edges={v_json.edge_count}",
            ),
            GateResult(
                "validation_parity",
                PASS if parity_ok else FAIL,
                f"plain(nodes={v_plain.node_count},edges={v_plain.edge_count},ok={v_plain.ok}) "
                f"json(nodes={v_json.node_count},edges={v_json.edge_count},ok={v_json.ok})",
            ),
            GateResult(
                "doc_grounded",
                PASS if present else FAIL,
                f"stages present in packet: {sorted(present)}",
            ),
            GateResult(
                "doc_no_false_complete",
                PASS if (not complete or len(present) == _STAGE_COUNT) else FAIL,
                f"status={status} stages={len(present)}/{_STAGE_COUNT}",
            ),
        ]
        if task.token_ceiling is not None and v_json.node_count > 0:
            tokens = count_tokens(packet)
            gates.append(
                GateResult(
                    "token_ceiling",
                    PASS if tokens.controlling <= task.token_ceiling else FAIL,
                    f"{tokens.controlling}<= {task.token_ceiling} [{tokens.detail}]",
                )
            )
        return CaseResult(task=task, probe=None, gates=gates)
