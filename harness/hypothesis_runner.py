#!/usr/bin/env python3
"""
hypothesis_runner.py — branching measurement harness for Back-Channel B.

Implements the keep/revert gate from docs/process/dual-backchannel-loop.md:

    keep iff checks.sh passes
         AND the primary metric does not regress beyond tolerance
         AND telemetry does not contradict itself

Every outcome is appended to .measure/<component>/log.jsonl. A REGRESSED
verdict emits Signal D (metric drift), which /reconcile-spec turns into a
Wayfinder Type B research ticket.

Usage:
    python hypothesis_runner.py <component> <hypothesis_branch> [--tolerance PCT]
                                [--baseline-branch main] [--record-baseline]

Exit codes: 0 = keep authorized · 1 = revert · 2 = harness/usage error.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from typing import Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from baseline import (  # noqa: E402
    REGRESSED,
    UNKNOWN,
    Comparison,
    compare,
    find_baseline,
    parse_measurement,
    telemetry_contradiction,
)
from evidence_logger import log_event  # noqa: E402

KEEP, REVERT, ERROR = 0, 1, 2


def _bash() -> Optional[str]:
    return shutil.which("bash")


def run_script(script_path: str, component: str, timeout: int = 300) -> Tuple[int, str, str]:
    """Run a harness script, returning (returncode, stdout, stderr).

    stdout and stderr are kept separate: the measurement payload is parsed from
    stdout alone, so diagnostics on stderr cannot corrupt it.
    """
    if not os.path.exists(script_path):
        return 127, "", f"Script not found: {script_path}"
    bash = _bash()
    if bash is None:
        return 127, "", "No `bash` on PATH; harness scripts require a POSIX shell."
    try:
        res = subprocess.run(
            [bash, script_path, component],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return res.returncode, res.stdout, res.stderr
    except subprocess.TimeoutExpired:
        return 124, "", f"Timed out after {timeout}s: {script_path}"
    except OSError as e:
        return 126, "", f"Could not execute {script_path}: {e}"


def evaluate_hypothesis(
    component: str,
    hypothesis_branch: str,
    tolerance_pct: float = 20.0,
    baseline_branch: str = "main",
    log_dir: str = ".measure",
    record_baseline: bool = False,
) -> Tuple[int, str]:
    checks_path = os.path.join("components", component, "checks.sh")
    measure_path = os.path.join("components", component, "measure.sh")

    def record(event_type, metrics, stage, verdict=None, reason=None, branch=None):
        log_event(
            component,
            event_type,
            metrics,
            evidence_stage=stage,
            branch=branch or hypothesis_branch,
            verdict=verdict,
            reason=reason,
            log_dir=log_dir,
        )

    print(f"=== EVALUATING {component} @ {hypothesis_branch} ===")

    # 1. Correctness backpressure. Non-negotiable and always first: a metric
    #    improvement on incorrect code is not an improvement.
    code, out, err = run_script(checks_path, component)
    if code != 0:
        detail = (err or out).strip()
        print(f"[REVERT] checks.sh FAILED (exit {code})\n{detail}")
        record("decision", {}, "Refuted", "revert", f"checks.sh failed (exit {code})")
        return REVERT, "checks.sh failed"
    print("[PASS] correctness backpressure green")

    # 2. Measurement.
    code, out, err = run_script(measure_path, component)
    if code != 0:
        detail = (err or out).strip()
        print(f"[REVERT] measure.sh FAILED (exit {code})\n{detail}")
        record("decision", {}, "Refuted", "revert", f"measure.sh failed (exit {code})")
        return REVERT, "measure.sh failed"

    try:
        payload = parse_measurement(out)
    except ValueError as e:
        # Unparseable output is an instrument failure, never a pass. The old
        # behaviour substituted value=0 here, which reads as a perfect score
        # for any lower-is-better metric.
        print(f"[REVERT] unusable measure.sh output: {e}")
        record("decision", {}, "Unknown", "revert", f"unparseable measurement: {e}")
        return REVERT, "unparseable measurement"

    contradiction = telemetry_contradiction(payload)
    if contradiction:
        print(f"[REVERT] telemetry contradiction: {contradiction}")
        record("decision", payload, "Unknown", "revert", f"telemetry contradiction: {contradiction}")
        return REVERT, "telemetry contradiction"

    metric = payload.get("metric", "unknown_metric")
    print(f"[MEASURED] {metric} = {payload.get('value')} {payload.get('unit', '')}".rstrip())
    record("hypothesis", payload, "Measured")

    # 3. Baseline comparison.
    base_event = find_baseline(component, metric, log_dir, baseline_branch)
    base_value = base_event["metrics"].get("value") if base_event else None

    cmp_result: Comparison = compare(
        metric,
        payload.get("value"),
        base_value,
        tolerance_pct=tolerance_pct,
        declared_direction=payload.get("direction"),
    )

    base_str = "none" if base_value is None else f"{base_value}"
    print(f"[BASELINE] {base_str} -> {cmp_result.current} :: {cmp_result.verdict.upper()} ({cmp_result.reason})")

    if cmp_result.verdict == REGRESSED:
        record(
            "signal_d",
            {**payload, "baseline": base_value, "delta_pct": cmp_result.delta_pct},
            "Measured",
            "revert",
            cmp_result.reason,
        )
        print(
            "[REVERT] metric drift. Signal D logged - /reconcile-spec should emit a "
            "Wayfinder Type B research ticket before this leaf is retried."
        )
        return REVERT, cmp_result.reason

    if cmp_result.verdict == UNKNOWN:
        record("decision", payload, "Unknown", "revert", cmp_result.reason)
        print(f"[REVERT] undecidable comparison: {cmp_result.reason}")
        return REVERT, cmp_result.reason

    record(
        "decision",
        {**payload, "baseline": base_value, "delta_pct": cmp_result.delta_pct},
        "Measured",
        "keep",
        cmp_result.reason,
    )
    if record_baseline:
        # Promote to the trunk baseline only on explicit instruction, after the
        # Outer Loop has actually merged the worktree.
        record("baseline", payload, "Measured", branch=baseline_branch)
        print(f"[BASELINE] promoted {metric}={payload.get('value')} on {baseline_branch}")

    print(f"[KEEP] {hypothesis_branch} authorized for merge ({cmp_result.reason})")
    return KEEP, cmp_result.reason


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="RSS Back-Channel B branching measurement gate")
    p.add_argument("component")
    p.add_argument("hypothesis_branch")
    p.add_argument("--tolerance", type=float, default=20.0, help="regression tolerance %% (default 20)")
    p.add_argument("--baseline-branch", default="main")
    p.add_argument("--log-dir", default=".measure")
    p.add_argument(
        "--record-baseline",
        action="store_true",
        help="on KEEP, promote this measurement to the baseline branch (use after merge)",
    )
    args = p.parse_args(argv)

    try:
        code, _ = evaluate_hypothesis(
            args.component,
            args.hypothesis_branch,
            tolerance_pct=args.tolerance,
            baseline_branch=args.baseline_branch,
            log_dir=args.log_dir,
            record_baseline=args.record_baseline,
        )
        return code
    except Exception as e:  # harness bug, distinct from a revert verdict
        print(f"[ERROR] harness failure: {e}", file=sys.stderr)
        return ERROR


if __name__ == "__main__":
    sys.exit(main())
