#!/usr/bin/env python3
"""
Correctness backpressure for the RSS harness itself.

Run:  python -m pytest harness/test_harness.py -q
"""

from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from baseline import (  # noqa: E402
    IMPROVED,
    NEUTRAL,
    REGRESSED,
    UNKNOWN,
    compare,
    find_baseline,
    parse_measurement,
    resolve_direction,
    telemetry_contradiction,
)
from evidence_logger import log_event  # noqa: E402

# --- direction resolution ---------------------------------------------------


@pytest.mark.parametrize(
    "metric,expected",
    [
        ("latency_p99_ms", "lower"),
        ("build_duration", "lower"),
        ("memory_bytes", "lower"),
        ("error_rate", "lower"),  # 'error' must dominate 'rate'
        ("ears_validation_pass_rate", "higher"),
        ("specs_generated_per_sec", "higher"),
        ("coverage", "higher"),
        ("wibble", None),  # undecidable -> must not guess
    ],
)
def test_resolve_direction(metric, expected):
    assert resolve_direction(metric) == expected


def test_declared_direction_overrides_inference():
    assert resolve_direction("latency_p99_ms", "higher") == "higher"


def test_bad_declared_direction_raises():
    with pytest.raises(ValueError):
        resolve_direction("latency_p99_ms", "sideways")


# --- comparison -------------------------------------------------------------


def test_lower_is_better_improvement():
    c = compare("latency_p99_ms", 80.0, 100.0)
    assert c.verdict == IMPROVED
    assert c.delta_pct == pytest.approx(20.0)


def test_lower_is_better_regression_beyond_tolerance():
    c = compare("latency_p99_ms", 130.0, 100.0, tolerance_pct=20.0)
    assert c.verdict == REGRESSED
    assert c.blocks_merge


def test_lower_is_better_regression_within_tolerance_is_neutral():
    c = compare("latency_p99_ms", 110.0, 100.0, tolerance_pct=20.0)
    assert c.verdict == NEUTRAL
    assert not c.blocks_merge


def test_higher_is_better_regression_is_caught():
    # The pre-fix runner had no direction awareness; a pass-rate drop from
    # 1.0 to 0.5 would have read as an improvement under a naive `<=`.
    c = compare("ears_validation_pass_rate", 0.5, 1.0, tolerance_pct=20.0)
    assert c.verdict == REGRESSED


def test_higher_is_better_improvement():
    assert compare("throughput_ops_per_sec", 150.0, 100.0).verdict == IMPROVED


def test_noise_band_is_neutral():
    assert compare("latency_p99_ms", 100.5, 100.0).verdict == NEUTRAL


def test_absent_baseline_is_neutral_not_improved():
    c = compare("latency_p99_ms", 42.0, None)
    assert c.verdict == NEUTRAL
    assert c.baseline is None


def test_undecidable_direction_blocks_merge():
    c = compare("wibble", 10.0, 5.0)
    assert c.verdict == UNKNOWN
    assert c.blocks_merge


def test_non_numeric_current_is_unknown():
    assert compare("latency_p99_ms", "fast", 100.0).verdict == UNKNOWN


def test_zero_baseline_compares_by_sign():
    assert compare("error_count", 3.0, 0.0).verdict == REGRESSED
    assert compare("error_count", 0.0, 0.0).verdict == NEUTRAL


# --- measurement parsing ----------------------------------------------------


PRETTY_TEMPLATE_OUTPUT = """{
  "ts": "2026-08-04T00:00:00Z",
  "event_type": "measurement",
  "component": "spec-engine",
  "metric": "latency_p99_ms",
  "value": 42.5,
  "unit": "ms",
  "evidence_stage": "Measured",
  "status": "success"
}"""


def test_parses_pretty_printed_template_output():
    # Regression guard: the previous parser took the last line starting with
    # '{', which for this payload is the opening brace alone.
    payload = parse_measurement(PRETTY_TEMPLATE_OUTPUT)
    assert payload["metric"] == "latency_p99_ms"
    assert payload["value"] == 42.5


def test_parses_payload_after_log_noise():
    out = "[measure] warming up\n[measure] 3 iterations\n" + PRETTY_TEMPLATE_OUTPUT
    assert parse_measurement(out)["value"] == 42.5


def test_unparseable_output_raises_rather_than_fabricating():
    with pytest.raises(ValueError):
        parse_measurement("no json here at all")
    with pytest.raises(ValueError):
        parse_measurement("")


# --- telemetry honesty ------------------------------------------------------


def test_clean_payload_has_no_contradiction():
    assert telemetry_contradiction(json.loads(PRETTY_TEMPLATE_OUTPUT)) is None


def test_success_without_value_is_a_contradiction():
    assert telemetry_contradiction({"metric": "x", "status": "success"}) is not None


def test_failure_status_is_a_contradiction():
    assert telemetry_contradiction({"metric": "x", "value": 1, "status": "error"}) is not None


def test_overclaimed_evidence_stage_is_a_contradiction():
    # A harness run cannot yield Proved (research foundation SS5).
    assert telemetry_contradiction(
        {"metric": "x", "value": 1, "evidence_stage": "Proved"}
    ) is not None


# --- evidence log round-trip ------------------------------------------------


def test_find_baseline_ignores_hypothesis_branches(tmp_path):
    log_dir = str(tmp_path)
    log_event("comp", "baseline", {"metric": "latency_p99_ms", "value": 100.0},
              branch="main", log_dir=log_dir)
    log_event("comp", "measurement", {"metric": "latency_p99_ms", "value": 10.0},
              branch="hypothesis/OW-01", log_dir=log_dir)

    found = find_baseline("comp", "latency_p99_ms", log_dir)
    assert found["metrics"]["value"] == 100.0, "a reverted branch must not set the bar"


def test_find_baseline_takes_most_recent_and_matches_metric(tmp_path):
    log_dir = str(tmp_path)
    log_event("comp", "baseline", {"metric": "latency_p99_ms", "value": 100.0},
              branch="main", log_dir=log_dir)
    log_event("comp", "baseline", {"metric": "other_metric", "value": 7.0},
              branch="main", log_dir=log_dir)
    log_event("comp", "baseline", {"metric": "latency_p99_ms", "value": 90.0},
              branch="main", log_dir=log_dir)

    assert find_baseline("comp", "latency_p99_ms", log_dir)["metrics"]["value"] == 90.0
    assert find_baseline("comp", "missing", log_dir) is None


def test_find_baseline_survives_torn_line(tmp_path):
    log_dir = str(tmp_path)
    log_event("comp", "baseline", {"metric": "m", "value": 5.0}, branch="main", log_dir=log_dir)
    with open(os.path.join(log_dir, "comp", "log.jsonl"), "a", encoding="utf-8") as f:
        f.write('{"ts": "trunc\n')
    assert find_baseline("comp", "m", log_dir)["metrics"]["value"] == 5.0


def test_log_event_rejects_invalid_stage(tmp_path):
    with pytest.raises(ValueError):
        log_event("comp", "measurement", {}, evidence_stage="Vibes", log_dir=str(tmp_path))
