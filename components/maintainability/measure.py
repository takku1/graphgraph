from __future__ import annotations

import datetime
import json
import subprocess
import sys
from pathlib import Path

BASELINE_PATH = Path(__file__).with_name("baseline.json")


def main() -> int:
    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    rules = [str(rule) for rule in baseline["rules"]]
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "src/graphgraph",
            "--select",
            ",".join(rules),
            "--output-format",
            "json",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode not in {0, 1}:
        print(result.stderr or f"ruff failed with exit {result.returncode}", file=sys.stderr)
        return 2
    try:
        diagnostics = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        print(f"ruff emitted invalid JSON: {exc}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "ts": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "event_type": "measurement",
                "component": "maintainability",
                "metric": "structural_complexity_diagnostics",
                "value": len(diagnostics),
                "unit": "diagnostics",
                "direction": "lower",
                "evidence_stage": "Measured",
                "status": "success",
                "rules": rules,
                "baseline": int(baseline["structural_complexity_diagnostics"]),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
