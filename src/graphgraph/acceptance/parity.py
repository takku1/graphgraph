"""Transport-parity acceptance case (GG10-LC-011 / D14).

Runs one identical query through three real renderings — CLI plain, CLI JSON,
and the MCP ``query_context`` tool — over a single self-contained graph, and
proves the logical packet (text, node/edge counts, answerability) agrees. Any
disagreement is a real transport defect, not a presentation difference.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from graphgraph.mcp.server import build_query_context
from graphgraph.services.native import render_native_context

from .model import FAIL, PASS, CaseResult, GateResult, Task
from .runner import _parse_packet

_QUERY = "What directly calls normalize_value?"


def _write_fixture(root: Path) -> None:
    (root / "app.py").write_text(
        "def normalize_value(x):\n    return x + 1\n\n"
        "def public_entry():\n    return normalize_value(1)\n\n"
        "def other_entry():\n    return normalize_value(2)\n",
        encoding="utf-8",
    )


def _strip_message(text: str) -> str:
    # Plain rendering may prefix a partial-result note before the packet.
    marker = text.find("#gg")
    return text[marker:].strip() if marker != -1 else text.strip()


def _counts(packet: str) -> tuple[int, int]:
    _relations, nodes, edges = _parse_packet(packet)
    return len(nodes), len(edges)


def run_transport_parity(task: Task) -> CaseResult:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write_fixture(root)
        graph_path = root / ".graphgraph" / "graph.gg"

        # CLI JSON (also builds the graph the other transports reuse).
        cli_json_raw, _status = render_native_context(
            query=_QUERY,
            query_class="reverse_lookup",
            directory=root,
            graph_path=graph_path,
            json_output=True,
            json_details=True,
            show_anchors=True,
            max_nodes=20,
        )
        cli_json = json.loads(cli_json_raw)

        # CLI plain (packet only).
        cli_plain_raw, _status2 = render_native_context(
            query=_QUERY,
            query_class="reverse_lookup",
            directory=root,
            graph_path=graph_path,
            json_output=False,
            show_anchors=False,
            max_nodes=20,
        )

        # MCP query_context tool.
        mcp_raw = build_query_context(
            {
                "query": _QUERY,
                "query_class": "reverse_lookup",
                "directory": str(root),
                "graph_path": str(graph_path),
                "show_anchors": True,
                "max_nodes": 20,
            }
        )
        mcp = json.loads(mcp_raw)

        cli_json_packet = str(cli_json.get("packet", ""))
        mcp_packet = str(mcp.get("packet", ""))
        cli_plain_packet = _strip_message(cli_plain_raw)

        cj_nodes, cj_edges = _counts(cli_json_packet)
        mc_nodes, mc_edges = _counts(mcp_packet)
        cp_nodes, cp_edges = _counts(cli_plain_packet)

        cj_status = str((cli_json.get("retrieval") or {}).get("answerability", {}).get("status", ""))
        mc_status = str((mcp.get("retrieval") or {}).get("answerability", {}).get("status", ""))

        packets_equal = cli_json_packet.strip() == mcp_packet.strip() == cli_plain_packet
        counts_equal = (cj_nodes, cj_edges) == (mc_nodes, mc_edges) == (cp_nodes, cp_edges)

        gates = [
            GateResult(
                "packet_parity",
                PASS if packets_equal else FAIL,
                "identical packet across CLI-plain/CLI-JSON/MCP"
                if packets_equal
                else f"packets differ (json={len(cli_json_packet)}c plain={len(cli_plain_packet)}c mcp={len(mcp_packet)}c)",
            ),
            GateResult(
                "node_edge_parity",
                PASS if counts_equal else FAIL,
                f"json={cj_nodes}/{cj_edges} plain={cp_nodes}/{cp_edges} mcp={mc_nodes}/{mc_edges}",
            ),
            GateResult(
                "status_parity",
                PASS if cj_status == mc_status and cj_status else FAIL,
                f"json={cj_status!r} mcp={mc_status!r}",
            ),
            GateResult(
                "reverse_lookup_correct",
                PASS
                if all(sym in cli_json_packet for sym in ("public_entry", "other_entry"))
                else FAIL,
                "both callers present in the shared packet",
            ),
        ]
        return CaseResult(task=task, probe=None, gates=gates)
