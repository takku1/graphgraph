"""Offline, line-budget evaluation for repository navigation traces."""

from __future__ import annotations

import json
import math
import statistics
from dataclasses import dataclass
from pathlib import Path

DEFAULT_NAVIGATION_PROFILE = {
    "time": 0.05,
    "source_lines": 0.10,
    "tokens": 0.05,
    "actions": 0.10,
    "missed_evidence": 0.40,
    "noise": 0.10,
    "unsupported_claims": 0.10,
    "freshness_risk": 0.10,
}


class NavigationEvalError(ValueError):
    """Raised when task or trace input cannot license an evaluation."""


@dataclass(frozen=True)
class RelevantRegion:
    path: str
    start_line: int | None = None
    end_line: int | None = None

    @property
    def lines(self) -> int:
        if self.start_line is None or self.end_line is None:
            return 1
        return max(1, self.end_line - self.start_line + 1)


def _load_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise NavigationEvalError(f"cannot load {path}: {exc}") from exc


def _rows(payload: object, key: str) -> list[dict[str, object]]:
    if isinstance(payload, dict):
        payload = payload.get(key, [])
    if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
        raise NavigationEvalError(f"expected a list of {key}")
    return payload


def _region(raw: object) -> RelevantRegion:
    if isinstance(raw, str):
        return RelevantRegion(raw.replace("\\", "/"))
    if not isinstance(raw, dict) or not raw.get("path"):
        raise NavigationEvalError("every relevant/returned region requires a path")
    start = raw.get("start_line")
    end = raw.get("end_line")
    return RelevantRegion(
        str(raw["path"]).replace("\\", "/"),
        int(start) if start is not None else None,
        int(end) if end is not None else None,
    )


def _overlap(relevant: RelevantRegion, returned: RelevantRegion) -> int:
    if relevant.path.casefold() != returned.path.casefold():
        return 0
    if relevant.start_line is None or relevant.end_line is None:
        return 1
    if returned.start_line is None or returned.end_line is None:
        return relevant.lines
    return max(
        0,
        min(relevant.end_line, returned.end_line)
        - max(relevant.start_line, returned.start_line)
        + 1,
    )


def _returned_lines(region: RelevantRegion) -> int:
    return region.lines


def _rank_metrics(qrels: list[RelevantRegion], returned: list[RelevantRegion]) -> tuple[float, float]:
    gains = [
        max((_overlap(relevant, candidate) / relevant.lines for relevant in qrels), default=0.0)
        for candidate in returned[:10]
    ]
    reciprocal_rank = next((1.0 / rank for rank, gain in enumerate(gains, start=1) if gain > 0), 0.0)
    dcg = sum((2**gain - 1) / math.log2(rank + 1) for rank, gain in enumerate(gains, start=1))
    ideal_gains = sorted(gains, reverse=True)
    idcg = sum((2**gain - 1) / math.log2(rank + 1) for rank, gain in enumerate(ideal_gains, start=1))
    return reciprocal_rank, dcg / idcg if idcg else 0.0


def _coverage(qrels: list[RelevantRegion], returned: list[RelevantRegion]) -> float:
    total = sum(region.lines for region in qrels)
    if total == 0:
        return 1.0
    covered = sum(
        min(relevant.lines, sum(_overlap(relevant, candidate) for candidate in returned))
        for relevant in qrels
    )
    return min(1.0, covered / total)


def _coverage_auc(
    qrels: list[RelevantRegion],
    returned: list[RelevantRegion],
    line_budget: int,
) -> float:
    if line_budget <= 0:
        return 0.0
    cumulative = 0
    previous_coverage = 0.0
    area = 0.0
    selected: list[RelevantRegion] = []
    for region in returned:
        width = min(_returned_lines(region), max(0, line_budget - cumulative))
        if width <= 0:
            break
        selected.append(region)
        coverage = _coverage(qrels, selected)
        area += (previous_coverage + coverage) * 0.5 * width
        cumulative += width
        previous_coverage = coverage
    if cumulative < line_budget:
        area += previous_coverage * (line_budget - cumulative)
    return area / line_budget


def _cost_ratio(run: dict[str, object], budget: dict[str, object], name: str) -> float:
    actual = float(run.get(name, 0) or 0)
    limit = float(budget.get(name, 0) or 0)
    return actual / limit if limit > 0 else 0.0


def _profile(payload: object | None) -> dict[str, float]:
    if payload is None:
        return dict(DEFAULT_NAVIGATION_PROFILE)
    if isinstance(payload, dict) and "weights" in payload:
        payload = payload["weights"]
    if not isinstance(payload, dict):
        raise NavigationEvalError("profile must be an object or contain a weights object")
    result = dict(DEFAULT_NAVIGATION_PROFILE)
    for name, value in payload.items():
        if name not in result:
            raise NavigationEvalError(f"unknown navigation-loss weight: {name}")
        result[name] = float(value)
    if any(value < 0 for value in result.values()) or sum(result.values()) <= 0:
        raise NavigationEvalError("navigation-loss weights must be non-negative with a positive sum")
    total = sum(result.values())
    return {name: value / total for name, value in result.items()}


def evaluate_navigation(
    tasks_payload: object,
    runs_payload: object,
    *,
    profile_payload: object | None = None,
) -> dict[str, object]:
    """Evaluate strategy traces against independent evidence/facet qrels."""

    tasks = _rows(tasks_payload, "tasks")
    runs = _rows(runs_payload, "runs")
    weights = _profile(profile_payload)
    by_id: dict[str, dict[str, object]] = {}
    for task in tasks:
        task_id = str(task.get("id") or "")
        if not task_id or task_id in by_id:
            raise NavigationEvalError("task ids must be non-empty and unique")
        by_id[task_id] = task

    results: list[dict[str, object]] = []
    for run in runs:
        task_id = str(run.get("task_id") or "")
        task = by_id.get(task_id)
        if task is None:
            raise NavigationEvalError(f"run references unknown task_id {task_id!r}")
        strategy = str(run.get("strategy") or "")
        if not strategy:
            raise NavigationEvalError(f"run {task_id!r} requires a strategy")
        qrels = [_region(item) for item in task.get("relevant_regions", [])]
        returned = [_region(item) for item in run.get("regions", [])]
        expected_facets = {str(item) for item in task.get("facets", [])}
        found_facets = {str(item) for item in run.get("facets", [])}
        budget = task.get("budget") or {}
        if not isinstance(budget, dict):
            raise NavigationEvalError(f"task {task_id!r} budget must be an object")
        line_budget = int(budget.get("source_lines", 0) or 0)
        line_coverage = _coverage(qrels, returned)
        facet_completeness = (
            len(expected_facets & found_facets) / len(expected_facets)
            if expected_facets else 1.0
        )
        evidence_completeness = (line_coverage + facet_completeness) / 2.0
        returned_line_count = int(run.get("source_lines", 0) or 0)
        if returned_line_count <= 0:
            returned_line_count = sum(_returned_lines(region) for region in returned)
        relevant_returned_lines = sum(
            min(candidate.lines, sum(_overlap(relevant, candidate) for relevant in qrels))
            for candidate in returned
        )
        noise = max(0.0, 1.0 - relevant_returned_lines / max(1, returned_line_count))
        unsupported = min(1.0, float(run.get("unsupported_claims", 0) or 0))
        freshness_risk = min(1.0, max(0.0, float(run.get("freshness_risk", 0) or 0)))
        components = {
            "time": _cost_ratio(run, budget, "milliseconds"),
            "source_lines": returned_line_count / line_budget if line_budget > 0 else 0.0,
            "tokens": _cost_ratio(run, budget, "tokens"),
            "actions": _cost_ratio(run, budget, "actions"),
            "missed_evidence": 1.0 - evidence_completeness,
            "noise": noise,
            "unsupported_claims": unsupported,
            "freshness_risk": freshness_risk,
        }
        loss = sum(weights[name] * value for name, value in components.items())
        reciprocal_rank, ndcg_at_10 = _rank_metrics(qrels, returned)
        complete_claimed = bool(run.get("complete_claimed", False))
        abstained = bool(run.get("abstained", False))
        results.append({
            "task_id": task_id,
            "strategy": strategy,
            "stratum": str(task.get("stratum") or "unclassified"),
            "line_coverage": round(line_coverage, 6),
            "coverage_auc": round(_coverage_auc(qrels, returned, line_budget), 6),
            "mrr": round(reciprocal_rank, 6),
            "ndcg_at_10": round(ndcg_at_10, 6),
            "facet_completeness": round(facet_completeness, 6),
            "navigation_loss": round(loss, 6),
            "components": {name: round(value, 6) for name, value in components.items()},
            "within_line_budget": line_budget <= 0 or returned_line_count <= line_budget,
            "false_complete": complete_claimed and evidence_completeness < 1.0,
            "false_incomplete": abstained and evidence_completeness >= 1.0,
        })

    grouped: dict[str, list[dict[str, object]]] = {}
    for result in results:
        grouped.setdefault(str(result["strategy"]), []).append(result)
    strategies = {
        name: {
            "runs": len(rows),
            "mean_navigation_loss": round(statistics.fmean(float(row["navigation_loss"]) for row in rows), 6),
            "median_navigation_loss": round(statistics.median(float(row["navigation_loss"]) for row in rows), 6),
            "mean_line_coverage": round(statistics.fmean(float(row["line_coverage"]) for row in rows), 6),
            "mean_facet_completeness": round(statistics.fmean(float(row["facet_completeness"]) for row in rows), 6),
            "within_line_budget_rate": round(statistics.fmean(1.0 if row["within_line_budget"] else 0.0 for row in rows), 6),
            "false_complete": sum(1 for row in rows if row["false_complete"]),
            "false_incomplete": sum(1 for row in rows if row["false_incomplete"]),
        }
        for name, rows in sorted(grouped.items())
    }
    return {
        "schema": "navigation_eval_v1",
        "profile": {"weights": weights},
        "results": results,
        "strategies": strategies,
    }


def evaluate_navigation_files(
    tasks_path: Path,
    runs_path: Path,
    *,
    profile_path: Path | None = None,
) -> dict[str, object]:
    return evaluate_navigation(
        _load_json(tasks_path),
        _load_json(runs_path),
        profile_payload=_load_json(profile_path) if profile_path else None,
    )


__all__ = [
    "DEFAULT_NAVIGATION_PROFILE",
    "NavigationEvalError",
    "evaluate_navigation",
    "evaluate_navigation_files",
]
