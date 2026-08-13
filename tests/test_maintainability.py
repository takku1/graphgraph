from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE = json.loads(
    (ROOT / "components" / "maintainability" / "baseline.json").read_text(encoding="utf-8")
)
RULES = tuple(str(rule) for rule in BASELINE["rules"])
OBSERVED_BASELINE = int(BASELINE["structural_complexity_diagnostics"])


def _ruff_complexity_diagnostics() -> list[dict[str, object]]:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "src/graphgraph",
            "--select",
            ",".join(RULES),
            "--output-format",
            "json",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if result.returncode not in {0, 1}:
        raise AssertionError(f"Ruff instrument failed ({result.returncode}): {result.stderr}")
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise AssertionError(f"Ruff emitted invalid JSON: {result.stdout[:500]}") from exc
    if not isinstance(payload, list):
        raise AssertionError(f"Ruff JSON must be a list, got {type(payload).__name__}")
    return payload


class MaintainabilityRatchetTest(unittest.TestCase):
    def test_structural_complexity_diagnostics_do_not_regress(self) -> None:
        diagnostics = _ruff_complexity_diagnostics()
        self.assertLessEqual(
            len(diagnostics),
            OBSERVED_BASELINE,
            "structural-complexity diagnostics increased; decompose the new hotspot "
            "or deliberately re-baseline the maintainability spec with evidence",
        )

    def test_instrument_reports_only_selected_production_rules(self) -> None:
        diagnostics = _ruff_complexity_diagnostics()
        production_root = (ROOT / "src" / "graphgraph").resolve()
        for item in diagnostics:
            self.assertIn(str(item["code"]), RULES)
            self.assertTrue(
                Path(str(item["filename"])).resolve().is_relative_to(production_root),
                f"complexity instrument escaped production scope: {item['filename']}",
            )


if __name__ == "__main__":
    unittest.main()
