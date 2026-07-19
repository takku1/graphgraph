"""Natural-language flow / scope-inference case (GG10-LC-006 / D5+D7).

Builds a small multi-package repo with a real frontend->engine flow plus a
term-matching test and a historical audit doc, then asks a natural-language flow
question. Checks that production entry points outrank lexical test/audit matches,
that structural evidence connects the flow, and that the packet stays bounded.
Self-contained, so it does not depend on the target repository.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from graphgraph.services.native import render_native_context

from .model import FAIL, PASS, CaseResult, GateResult, Task
from .runner import _parse_packet
from .tokens import count_tokens

_QUERY = "How does expression parsing flow from frontends into the engine expression representation?"


def _write_fixture(root: Path) -> None:
    (root / "engine").mkdir()
    (root / "engine" / "__init__.py").write_text("", encoding="utf-8")
    (root / "engine" / "expr.py").write_text(
        "class Expr:\n    def __init__(self, value):\n        self.value = value\n\n"
        "def lift(expr):\n    # engine expression representation\n    return expr.value\n",
        encoding="utf-8",
    )
    (root / "frontends").mkdir()
    (root / "frontends" / "__init__.py").write_text("", encoding="utf-8")
    (root / "frontends" / "parse.py").write_text(
        "from engine.expr import Expr, lift\n\n"
        "def parse_expr(source):\n"
        "    # production entry point: frontend parsing into the engine expr\n"
        "    return lift(Expr(source))\n",
        encoding="utf-8",
    )
    (root / "tests").mkdir()
    (root / "tests" / "test_parse.py").write_text(
        "from frontends.parse import parse_expr\n\n"
        "def test_expression_parsing_flow_from_frontends_into_engine():\n"
        "    assert parse_expr('x') == 'x'\n",
        encoding="utf-8",
    )
    (root / "docs").mkdir()
    (root / "docs" / "audit.md").write_text(
        "# Historical audit\n\n"
        "A past audit reviewed expression parsing flow from frontends into the "
        "engine expression representation before the current design.\n",
        encoding="utf-8",
    )


def _top_anchor_path(payload: dict) -> str:
    anchors = payload.get("anchors") or []
    return str(anchors[0].get("path", "")) if anchors else ""


def run_scope_inference(task: Task) -> CaseResult:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write_fixture(root)
        graph_path = root / ".graphgraph" / "graph.gg"

        rendered, _s = render_native_context(
            query=_QUERY,
            query_class="subsystem_summary",
            directory=root,
            graph_path=graph_path,
            json_output=True,
            json_details=True,
            show_anchors=True,
            max_nodes=40,
        )
        payload = json.loads(rendered)
        packet = str(payload.get("packet", ""))
        _relations, nodes, _edges = _parse_packet(packet)
        labels = {n.label for n in nodes}
        top_path = _top_anchor_path(payload)

        production_present = "parse_expr" in labels and ("lift" in labels or "Expr" in labels)
        # The historical audit doc must not be the top anchor for a code-flow query.
        audit_not_top = "audit.md" not in top_path
        # Production is anchored above the test: a production node must be an
        # anchor, and the top anchor is a code (not doc/test-only) node.
        top_is_production = top_path.endswith(".py") and "test" not in top_path
        tokens = count_tokens(packet)

        gates = [
            GateResult(
                "production_flow_present",
                PASS if production_present else FAIL,
                f"parse_expr+lift/Expr in packet: {sorted(labels & {'parse_expr', 'lift', 'Expr'})}",
            ),
            GateResult(
                "audit_doc_not_top_anchor",
                PASS if audit_not_top else FAIL,
                f"top_anchor_path={top_path!r}",
            ),
            GateResult(
                "production_outranks_tests",
                PASS if top_is_production else FAIL,
                f"top_anchor_path={top_path!r}",
            ),
            GateResult(
                "token_ceiling",
                PASS if task.token_ceiling is None or tokens.controlling <= task.token_ceiling else FAIL,
                f"{tokens.controlling}<= {task.token_ceiling} [{tokens.detail}]",
            ),
        ]
        return CaseResult(task=task, probe=None, gates=gates)
