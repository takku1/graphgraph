"""Scan-boundary acceptance case (GG10-LC-010 / D2).

Builds a disposable repository with an ignored directory, a built-in-skipped
directory, and a secret canary, scans it through GraphGraph's public surface, and
proves the canary never reaches any produced artifact while ordinary source is
retained and the controlling exclusion rule is named in the receipt.

This is a *scan-level* property, so it runs its own fixture rather than querying
the target repository.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from graphgraph.scanner.files import collect_files
from graphgraph.services.native import render_native_context

from .model import FAIL, PASS, CaseResult, GateResult, Task

CANARY = "GG_SECRET_CANARY_a1b2c3d4e5f6"


def _write_fixture(root: Path) -> None:
    # Each exclusion path is exercised by exactly one canary carrier so a failure
    # attributes to the rule that broke: file-level gitignore, dir-level
    # gitignore, the built-in .env secret rule, and a built-in skipped dir.
    (root / ".gitignore").write_text("secrets/\ncredentials.txt\n", encoding="utf-8")
    (root / "app.py").write_text(
        "def public_entry():\n    return normalize_value(1)\n\n"
        "def normalize_value(x):\n    return x + 1\n",
        encoding="utf-8",
    )
    (root / "tests").mkdir()
    (root / "tests" / "test_app.py").write_text(
        "from app import public_entry\n\n"
        "def test_public_entry():\n    assert public_entry() == 2\n",
        encoding="utf-8",
    )
    # dir-level gitignore
    (root / "secrets").mkdir()
    (root / "secrets" / "leak.py").write_text(f"API_KEY = '{CANARY}'\n", encoding="utf-8")
    # file-level gitignore (non-dotfile, so exclusion is attributable to the rule)
    (root / "credentials.txt").write_text(f"token={CANARY}\n", encoding="utf-8")
    # built-in .env secret rule -- deliberately NOT gitignored
    (root / ".env").write_text(f"API_KEY={CANARY}\n", encoding="utf-8")
    # built-in skipped directory (agent config tree)
    (root / ".claude").mkdir()
    (root / ".claude" / "notes.md").write_text(f"# private\n{CANARY}\n", encoding="utf-8")


def _artifact_blob(root: Path, graph_path: Path, payload_text: str) -> str:
    """Concatenate every produced artifact so a single scan finds any leak."""
    parts = [payload_text]
    graph_dir = graph_path.parent
    if graph_dir.is_dir():
        for artifact in sorted(graph_dir.rglob("*")):
            if artifact.is_file():
                try:
                    parts.append(artifact.read_text(encoding="utf-8", errors="replace"))
                except OSError:
                    continue
    return "\n".join(parts)


def run_secret_boundary(task: Task) -> CaseResult:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write_fixture(root)
        graph_path = root / ".graphgraph" / "graph.gg"

        rendered, _status = render_native_context(
            query="secret canary API_KEY",
            query_class="negative_query",
            directory=root,
            graph_path=graph_path,
            json_output=True,
            json_details=True,
            show_anchors=True,
            max_nodes=20,
        )
        payload = json.loads(rendered)
        packet = str(payload.get("packet", ""))
        blob = _artifact_blob(root, graph_path, rendered)

        collected = collect_files(root, max_nodes=500)
        collected_rels = {p.relative_to(root).as_posix() for p in collected.files}
        pruned = set(collected.rule_pruned_dirs) | set(collected.default_pruned_dirs)

        gates = [
            GateResult(
                "canary_absent",
                PASS if CANARY not in blob else FAIL,
                "no secret canary in any produced artifact"
                if CANARY not in blob
                else "CANARY LEAKED into a produced artifact",
            ),
            GateResult(
                "canary_absent_from_packet",
                PASS if CANARY not in packet else FAIL,
                "packet is canary-free" if CANARY not in packet else "CANARY in packet",
            ),
            GateResult(
                "ignored_dir_pruned",
                PASS if "secrets" in pruned else FAIL,
                f"rule_pruned={collected.rule_pruned_dirs}",
            ),
            GateResult(
                "gitignored_file_excluded",
                PASS if "credentials.txt" not in collected_rels else FAIL,
                f"credentials.txt indexed={'credentials.txt' in collected_rels} "
                f"(ignored_by_rules={collected.ignored_by_rules})",
            ),
            GateResult(
                "builtin_env_secret_excluded",
                PASS if ".env" not in collected_rels else FAIL,
                f".env indexed={'.env' in collected_rels} (excluded by built-in secret rule, not gitignore)",
            ),
            GateResult(
                "builtin_dir_pruned",
                PASS if ".claude" in pruned else FAIL,
                f"default_pruned={collected.default_pruned_dirs}",
            ),
            GateResult(
                "source_retained",
                PASS if "app.py" in collected_rels and "tests/test_app.py" in collected_rels else FAIL,
                f"app.py={'app.py' in collected_rels} test={'tests/test_app.py' in collected_rels}",
            ),
            GateResult(
                "receipt_names_rule",
                PASS if collected.ignore_files else FAIL,
                f"ignore_files={collected.ignore_files}",
            ),
        ]
        return CaseResult(task=task, probe=None, gates=gates)
