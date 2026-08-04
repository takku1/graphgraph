#!/usr/bin/env python3
"""
baseline.py — Back-Channel B baseline comparison.

Pure decision logic for the branching-measurement gate defined in
docs/process/dual-backchannel-loop.md:

    keep iff checks pass AND metric improves AND no telemetry contradiction

This module owns the "metric improves" half. It reads the append-only
evidence log written by evidence_logger, resolves the metric's direction
(lower-is-better vs higher-is-better), and classifies the delta.

Epistemic rule (research foundation SS5): when direction or baseline cannot be
established, this module returns UNKNOWN rather than guessing. A guessed
comparison would manufacture Measured-grade evidence out of nothing.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

# --- Metric direction -------------------------------------------------------
# Explicit `direction` in the measure.sh payload always wins. These patterns are
# the fallback for metrics that do not declare one.

LOWER_IS_BETTER = re.compile(
    r"(latency|duration|_ms$|_ns$|_us$|elapsed|time|cost|error|failure|"
    r"regression|bytes|size|memory|alloc|p50|p95|p99|overhead)",
    re.IGNORECASE,
)
HIGHER_IS_BETTER = re.compile(
    r"(rate|ratio|throughput|ops_per|per_sec|accuracy|precision|recall|"
    r"pass|score|coverage|success|hit|uptime|yield)",
    re.IGNORECASE,
)

IMPROVED = "improved"
NEUTRAL = "neutral"
REGRESSED = "regressed"
UNKNOWN = "unknown"


def resolve_direction(metric: str, declared: Optional[str] = None) -> Optional[str]:
    """Return 'lower' | 'higher' | None (undecidable).

    `declared` comes from the measure.sh JSON payload and is authoritative.
    """
    if declared:
        d = declared.strip().lower()
        if d in ("lower", "lower_is_better", "min", "minimize"):
            return "lower"
        if d in ("higher", "higher_is_better", "max", "maximize"):
            return "higher"
        raise ValueError(
            f"Unrecognized metric direction {declared!r}; "
            "use 'lower' or 'higher'."
        )

    # A metric can match both families (e.g. 'error_rate' -> lower wins because
    # the subject noun dominates). Check lower first: cost/error/latency nouns
    # are the stronger signal.
    if LOWER_IS_BETTER.search(metric):
        return "lower"
    if HIGHER_IS_BETTER.search(metric):
        return "higher"
    return None


# --- Evidence log access ----------------------------------------------------


def read_events(component: str, log_dir: str = ".measure") -> List[Dict[str, Any]]:
    """Read the append-only evidence log. Malformed lines are skipped, not fatal:
    the log is append-only and a torn write must not block the gate."""
    path = os.path.join(log_dir, component, "log.jsonl")
    if not os.path.exists(path):
        return []
    events: List[Dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return events


def find_baseline(
    component: str,
    metric: str,
    log_dir: str = ".measure",
    baseline_branch: str = "main",
) -> Optional[Dict[str, Any]]:
    """Most recent accepted measurement of `metric` on the baseline branch.

    Only events that were actually admitted to the trunk count as baseline:
    a measurement taken on a hypothesis branch that was later reverted must
    never become the bar the next hypothesis is judged against.
    """
    candidates = [
        e
        for e in read_events(component, log_dir)
        if e.get("branch") == baseline_branch
        and e.get("event_type") in ("baseline", "measurement")
        and isinstance(e.get("metrics"), dict)
        and e["metrics"].get("metric") == metric
        and _numeric(e["metrics"].get("value")) is not None
    ]
    return candidates[-1] if candidates else None


def _numeric(v: Any) -> Optional[float]:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    return None


# --- Comparison -------------------------------------------------------------


@dataclass
class Comparison:
    verdict: str  # IMPROVED | NEUTRAL | REGRESSED | UNKNOWN
    metric: str
    current: Optional[float]
    baseline: Optional[float]
    delta_pct: Optional[float]
    direction: Optional[str]
    reason: str

    @property
    def blocks_merge(self) -> bool:
        return self.verdict in (REGRESSED, UNKNOWN)


def compare(
    metric: str,
    current: Any,
    baseline: Any,
    tolerance_pct: float = 20.0,
    declared_direction: Optional[str] = None,
    noise_pct: float = 2.0,
) -> Comparison:
    """Classify current vs baseline.

    tolerance_pct: regression beyond this is REGRESSED (Signal D metric drift).
                   Within it, the run is NEUTRAL - acceptable for changes that
                   are not performance work.
    noise_pct:     movement smaller than this in either direction is NEUTRAL.
    """
    cur = _numeric(current)
    if cur is None:
        return Comparison(
            UNKNOWN, metric, None, _numeric(baseline), None, None,
            f"measure.sh produced no numeric value for {metric!r}",
        )

    base = _numeric(baseline)
    if base is None:
        return Comparison(
            NEUTRAL, metric, cur, None, None, resolve_direction(metric, declared_direction),
            "no prior baseline; recording first measurement",
        )

    direction = resolve_direction(metric, declared_direction)
    if direction is None:
        return Comparison(
            UNKNOWN, metric, cur, base, None, None,
            f"cannot resolve whether higher or lower is better for {metric!r}; "
            "declare \"direction\": \"lower\"|\"higher\" in measure.sh output",
        )

    if base == 0:
        # Percentage change is undefined against a zero baseline; fall back to
        # sign comparison only.
        if cur == 0:
            return Comparison(NEUTRAL, metric, cur, base, 0.0, direction, "unchanged at zero baseline")
        better = cur < base if direction == "lower" else cur > base
        return Comparison(
            IMPROVED if better else REGRESSED, metric, cur, base, None, direction,
            "zero baseline; compared by sign only",
        )

    raw_pct = (cur - base) / abs(base) * 100.0
    # Signed so that positive always means "better", whichever way the metric runs.
    improvement_pct = -raw_pct if direction == "lower" else raw_pct

    if abs(improvement_pct) < noise_pct:
        verdict, reason = NEUTRAL, f"within +/-{noise_pct}% noise band"
    elif improvement_pct > 0:
        verdict, reason = IMPROVED, f"improved {improvement_pct:.2f}%"
    elif -improvement_pct > tolerance_pct:
        verdict, reason = REGRESSED, (
            f"regressed {-improvement_pct:.2f}% (> {tolerance_pct}% tolerance) - Signal D metric drift"
        )
    else:
        verdict, reason = NEUTRAL, (
            f"regressed {-improvement_pct:.2f}% but within {tolerance_pct}% tolerance"
        )

    return Comparison(verdict, metric, cur, base, improvement_pct, direction, reason)


# --- measure.sh payload parsing --------------------------------------------


def parse_measurement(stdout: str) -> Dict[str, Any]:
    """Extract the JSON measurement payload from measure.sh stdout.

    Raises ValueError when no payload can be recovered. It must never invent a
    value: a fabricated metric silently becomes Measured-grade evidence and
    corrupts every later comparison.
    """
    text = stdout.strip()
    if not text:
        raise ValueError("measure.sh produced no output")

    # Whole-stdout parse handles the common case, including pretty-printed JSON.
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass

    # Otherwise scan for the last balanced {...} block, so a harness may emit
    # log lines before its payload.
    for start in range(len(text) - 1, -1, -1):
        if text[start] != "{":
            continue
        depth = 0
        for end in range(start, len(text)):
            if text[end] == "{":
                depth += 1
            elif text[end] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        obj = json.loads(text[start : end + 1])
                        if isinstance(obj, dict) and "metric" in obj:
                            return obj
                    except json.JSONDecodeError:
                        pass
                    break
    raise ValueError(
        "could not parse a JSON measurement payload from measure.sh output; "
        'expected an object with at least {"metric": ..., "value": ...}'
    )


def telemetry_contradiction(payload: Dict[str, Any]) -> Optional[str]:
    """Detect a broken instrument (graybox red test).

    An instrument that reports success while omitting its own reading, or that
    claims an evidence stage it cannot support, is not trustworthy evidence.
    """
    status = str(payload.get("status", "success")).lower()
    if status not in ("success", "ok", "pass", "passed"):
        return f"measure.sh reported status={status!r}"

    if _numeric(payload.get("value")) is None:
        return "measure.sh reported success but emitted no numeric value"

    stage = payload.get("evidence_stage")
    if stage is not None and stage not in ("Measured", "Sampled", "Observed"):
        return (
            f"measure.sh claimed evidence_stage={stage!r}; a harness run can only "
            "produce Observed, Sampled, or Measured"
        )
    return None
