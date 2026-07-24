"""Calibration of the tool's confidence signals against ground truth.

The largest measured cost of using GraphGraph as an agent context tool is the
*reverification tax*: an agent re-greps because it cannot trust a confidence
number. Trust is only worth anything if the number is *calibrated* -- if
"confidence 0.8" means "correct 80% of the time." This module is the
measurement layer that makes that claim checkable, and the recalibration layer
that repairs it.

The instruments are the standard, assumption-light tools for the job:

* **Reliability diagram + ECE/MCE** -- the binned view of calibration and its
  expected / worst-case error.
* **Brier score with Murphy's (1973) decomposition** --
  ``Brier = reliability - resolution + uncertainty`` -- which separates
  *calibration* (is the number honest) from *resolution* (is it discriminative).
  A constant 0.5 forecaster is perfectly calibrated and useless; only the
  decomposition catches that, so both terms are reported.
* **Isotonic recalibration via Pool-Adjacent-Violators** -- the O(n log n)
  optimal monotone least-squares fit that maps a raw confidence to a calibrated
  probability without any distributional assumption.

Everything is pure-Python and deterministic. Per-stratum (multicalibration) and
conformal-coverage layers build on ``reliability_table`` / ``pav_isotonic``
here; this module is their foundation, kept independent of any grouping so the
grouping policy can live with the caller.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ReliabilityBin:
    """One bucket of a reliability diagram."""

    lower: float
    upper: float
    count: int
    mean_confidence: float
    accuracy: float

    @property
    def gap(self) -> float:
        """Signed calibration gap: positive = overconfident (conf > accuracy)."""
        return self.mean_confidence - self.accuracy


@dataclass(frozen=True)
class CalibrationReport:
    """A full calibration receipt for one set of (confidence, outcome) pairs."""

    count: int
    base_rate: float
    brier: float
    binned_brier: float
    reliability: float
    resolution: float
    uncertainty: float
    ece: float
    mce: float
    bins: tuple[ReliabilityBin, ...]

    @property
    def decomposition_residual(self) -> float:
        """``reliability - resolution + uncertainty - binned_brier``; ~0 by identity."""
        return self.reliability - self.resolution + self.uncertainty - self.binned_brier


def _validate(pairs: list[tuple[float, bool]]) -> list[tuple[float, float]]:
    cleaned: list[tuple[float, float]] = []
    for confidence, outcome in pairs:
        c = float(confidence)
        if not 0.0 <= c <= 1.0:
            raise ValueError(f"confidence must be in [0, 1], got {confidence!r}")
        cleaned.append((c, 1.0 if outcome else 0.0))
    return cleaned


def reliability_table(
    pairs: list[tuple[float, bool]], *, bins: int = 10
) -> tuple[ReliabilityBin, ...]:
    """Bin (confidence, outcome) pairs into a reliability diagram.

    Equal-width bins over [0, 1]; a confidence of exactly 1.0 lands in the top
    bin. Empty bins are dropped so the diagram carries only observed regions.
    """
    if bins < 1:
        raise ValueError("bins must be >= 1")
    cleaned = _validate(pairs)
    buckets: list[list[tuple[float, float]]] = [[] for _ in range(bins)]
    for confidence, outcome in cleaned:
        index = min(bins - 1, int(confidence * bins))
        buckets[index].append((confidence, outcome))
    table: list[ReliabilityBin] = []
    for index, bucket in enumerate(buckets):
        if not bucket:
            continue
        count = len(bucket)
        table.append(ReliabilityBin(
            lower=index / bins,
            upper=(index + 1) / bins,
            count=count,
            mean_confidence=sum(c for c, _ in bucket) / count,
            accuracy=sum(o for _, o in bucket) / count,
        ))
    return tuple(table)


def calibration_report(
    pairs: list[tuple[float, bool]], *, bins: int = 10
) -> CalibrationReport:
    """Compute the full calibration receipt.

    ``reliability`` is the calibration loss (0 = perfectly calibrated).
    ``resolution`` is discriminative power (higher = better, bins depart from
    the base rate). ``uncertainty`` is the irreducible base-rate variance. By
    Murphy's identity these satisfy ``reliability - resolution + uncertainty ==
    binned_brier`` exactly, which ``decomposition_residual`` verifies.
    """
    cleaned = _validate(pairs)
    n = len(cleaned)
    if n == 0:
        raise ValueError("cannot compute calibration over zero predictions")
    base_rate = sum(o for _, o in cleaned) / n
    brier = sum((c - o) ** 2 for c, o in cleaned) / n

    table = reliability_table(pairs, bins=bins)
    reliability = sum(b.count * (b.mean_confidence - b.accuracy) ** 2 for b in table) / n
    resolution = sum(b.count * (b.accuracy - base_rate) ** 2 for b in table) / n
    uncertainty = base_rate * (1.0 - base_rate)
    binned_brier = reliability - resolution + uncertainty  # Murphy identity

    ece = sum(b.count * abs(b.gap) for b in table) / n
    mce = max((abs(b.gap) for b in table), default=0.0)

    return CalibrationReport(
        count=n,
        base_rate=round(base_rate, 6),
        brier=round(brier, 6),
        binned_brier=round(binned_brier, 6),
        reliability=round(reliability, 6),
        resolution=round(resolution, 6),
        uncertainty=round(uncertainty, 6),
        ece=round(ece, 6),
        mce=round(mce, 6),
        bins=table,
    )


def pav_isotonic(
    pairs: list[tuple[float, bool]]
) -> tuple[tuple[float, float], ...]:
    """Pool-Adjacent-Violators isotonic regression of outcome on confidence.

    Returns ``(upper_confidence, calibrated_probability)`` blocks of the
    optimal non-decreasing step function fitting the outcomes in least squares.
    Equal confidence values are one indivisible weighted observation; grouping
    them before PAV makes the fit independent of their input order. Feed a raw
    confidence through ``apply_isotonic`` to recalibrate it.

    PAV: sort by confidence, then repeatedly merge any block whose mean falls
    below its predecessor's (a monotonicity violation), pooling by weighted
    average. Each merge only ever moves the boundary forward, so it is O(n)
    after the sort.
    """
    cleaned = sorted(_validate(pairs), key=lambda item: item[0])
    if not cleaned:
        return ()

    # Group tied predictors before fitting. Treating tied x values as separate
    # ordered observations lets the arbitrary input order change the fit.
    grouped: list[list[float]] = []
    for x, y in cleaned:
        if grouped and grouped[-1][0] == x:
            grouped[-1][1] += y
            grouped[-1][2] += 1.0
        else:
            grouped.append([x, y, 1.0])

    # Each block: [maximum_x, summed_y, weight]. The maximum x is the inclusive
    # upper threshold needed to reproduce the fitted values for training data.
    blocks: list[list[float]] = []
    for x, summed_y, weight in grouped:
        blocks.append([x, summed_y, weight])
        # Merge backwards while the last block violates monotonicity.
        while len(blocks) >= 2 and blocks[-2][1] / blocks[-2][2] > blocks[-1][1] / blocks[-1][2]:
            max_x, sy2, w2 = blocks.pop()
            blocks[-1][0] = max_x
            blocks[-1][1] += sy2
            blocks[-1][2] += w2
    return tuple((max_x, sy / weight) for max_x, sy, weight in blocks)


def apply_isotonic(breakpoints: tuple[tuple[float, float], ...], confidence: float) -> float:
    """Map a raw confidence through the fitted non-decreasing step function."""
    if not breakpoints:
        return confidence
    for upper_confidence, probability in breakpoints:
        if confidence <= upper_confidence:
            return probability
    return breakpoints[-1][1]
