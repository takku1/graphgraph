"""Versioned evaluation suites, stratified reports, and paired comparisons.

This module freezes measurement policy without changing retrieval policy.  A
suite is repository-held-out, every qrel names its independent source receipt,
and reports preserve weak strata instead of averaging them out of sight.
"""

from __future__ import annotations

import json
import random
import re
from dataclasses import asdict, dataclass, fields, replace
from pathlib import Path
from statistics import fmean

from .calibration import calibration_report
from .eval import EvalResult, EvalTask, load_eval_tasks

EVAL_SCHEMA_VERSION = "graphgraph.eval.v1"
TASK_RESOLVER_VERSION = "node-qrel-v3-facets"
TOKEN_PROXY_VERSION = "piece-punctuation-ls-v1"
REFERENCE_TOKENIZERS_VERSION = "cl100k_base+o200k_base@tiktoken-0.13.0"
EXPECTED_EVIDENCE_VERSION = "independent-source-receipt-v1"
PROTOCOL_VERSIONS = {
    "task_resolver": TASK_RESOLVER_VERSION,
    "reference_tokenizers": REFERENCE_TOKENIZERS_VERSION,
    "token_proxy": TOKEN_PROXY_VERSION,
    "expected_evidence": EXPECTED_EVIDENCE_VERSION,
}
SPLITS = frozenset({"train", "calibration", "test"})
_IDENTIFIER_PART = re.compile(r"[A-Z]+(?=[A-Z][a-z]|\b)|[A-Z]?[a-z]+|[0-9]+")


class EvalProtocolError(ValueError):
    """A frozen evaluation suite violates its schema or independence rules."""


@dataclass(frozen=True)
class EvalProject:
    project_id: str
    repository: str
    commit: str
    language: str
    split: str
    task_path: Path
    oracle_method: str
    oracle_refs: tuple[str, ...]
    tasks: tuple[EvalTask, ...]


@dataclass(frozen=True)
class EvalSuite:
    schema_version: str
    suite_id: str
    versions: dict[str, str]
    projects: tuple[EvalProject, ...]


def load_eval_manifest(path: Path) -> EvalSuite:
    """Load and validate one repository-held-out evaluation manifest."""
    manifest = _read_object(path)
    _require_version_block(manifest, path)
    suite_id = _required_text(manifest, "suite_id", path)
    raw_projects = manifest.get("projects")
    if not isinstance(raw_projects, list) or not raw_projects:
        raise EvalProtocolError(f"{path}: projects must be a non-empty list")

    projects: list[EvalProject] = []
    seen_ids: set[str] = set()
    seen_tasks: set[str] = set()
    repositories_by_split: dict[str, set[str]] = {}
    root = path.resolve().parent
    for item in raw_projects:
        if not isinstance(item, dict):
            raise EvalProtocolError(f"{path}: every project entry must be an object")
        relative = _required_text(item, "tasks", path)
        task_path = (root / relative).resolve()
        if root not in task_path.parents:
            raise EvalProtocolError(f"{path}: task file escapes the suite directory: {relative}")
        project = _load_project(task_path)
        if project.project_id in seen_ids:
            raise EvalProtocolError(f"{path}: duplicate project id {project.project_id!r}")
        seen_ids.add(project.project_id)
        repositories_by_split.setdefault(project.split, set()).add(project.repository)
        for task in project.tasks:
            if not task.task_id:
                raise EvalProtocolError(f"{task_path}: every task requires a stable id")
            if task.task_id in seen_tasks:
                raise EvalProtocolError(f"{path}: duplicate task id {task.task_id!r}")
            seen_tasks.add(task.task_id)
        projects.append(project)

    split_sets = list(repositories_by_split.items())
    for index, (left_name, left) in enumerate(split_sets):
        for right_name, right in split_sets[index + 1 :]:
            overlap = left & right
            if overlap:
                raise EvalProtocolError(
                    f"{path}: repositories cross held-out splits {left_name}/{right_name}: {sorted(overlap)}"
                )
    if set(repositories_by_split) != SPLITS:
        raise EvalProtocolError(f"{path}: suite must contain exactly train/calibration/test splits")
    return EvalSuite(
        schema_version=EVAL_SCHEMA_VERSION,
        suite_id=suite_id,
        versions=dict(PROTOCOL_VERSIONS),
        projects=tuple(projects),
    )


def _load_project(path: Path) -> EvalProject:
    data = _read_object(path)
    _require_version_block(data, path)
    raw_project = data.get("project")
    if not isinstance(raw_project, dict):
        raise EvalProtocolError(f"{path}: project must be an object")
    project_id = _required_text(raw_project, "id", path)
    repository = _required_text(raw_project, "repository", path)
    commit = _required_text(raw_project, "commit", path)
    language = _required_text(raw_project, "language", path).lower()
    split = _required_text(raw_project, "split", path).lower()
    if split not in SPLITS:
        raise EvalProtocolError(f"{path}: invalid split {split!r}")

    oracle = data.get("oracle")
    if not isinstance(oracle, dict):
        raise EvalProtocolError(f"{path}: oracle must be an object")
    oracle_method = _required_text(oracle, "method", path)
    if "graphgraph" in oracle_method.lower():
        raise EvalProtocolError(f"{path}: GraphGraph output cannot be its own oracle")
    oracle_refs = _text_tuple(oracle.get("refs"), field="oracle.refs", path=path)
    if not oracle_refs:
        raise EvalProtocolError(f"{path}: oracle.refs must not be empty")

    tasks = load_eval_tasks(path)
    raw_tasks = data.get("tasks")
    if not isinstance(raw_tasks, list) or len(raw_tasks) != len(tasks):
        raise EvalProtocolError(f"{path}: tasks must be a non-empty list of runnable task objects")
    normalized: list[EvalTask] = []
    for raw, task in zip(raw_tasks, tasks, strict=True):
        if not isinstance(raw, dict):
            raise EvalProtocolError(f"{path}: every task must be an object")
        task_oracle_refs = _text_tuple(raw.get("oracle_refs"), field="oracle_refs", path=path)
        if not task_oracle_refs:
            raise EvalProtocolError(f"{path}: task {task.task_id!r} requires oracle_refs")
        if not task.strata:
            raise EvalProtocolError(f"{path}: task {task.task_id!r} requires at least one stratum")
        if task.expected_answerable is not False and not task.expected_nodes and not task.expected_edges:
            raise EvalProtocolError(f"{path}: task {task.task_id!r} has no independently checkable expectation")
        task = replace(
            task,
            project=project_id,
            split=split,
            oracle_refs=task_oracle_refs,
        )
        if "lexical_disjoint" in task.strata:
            overlap = lexical_expectation_overlap(task)
            if overlap:
                raise EvalProtocolError(
                    f"{path}: lexical_disjoint task {task.task_id!r} overlaps expectations: {sorted(overlap)}"
                )
        normalized.append(task)
    return EvalProject(
        project_id=project_id,
        repository=repository,
        commit=commit,
        language=language,
        split=split,
        task_path=path,
        oracle_method=oracle_method,
        oracle_refs=oracle_refs,
        tasks=tuple(normalized),
    )


def lexical_expectation_overlap(task: EvalTask) -> set[str]:
    """Return normalized identifier parts shared by a query and its qrels."""
    query_tokens = _identifier_tokens(task.query)
    expectation_tokens: set[str] = set()
    for expectation in task.expected_nodes:
        expectation_tokens.update(_identifier_tokens(expectation))
    return query_tokens & expectation_tokens


def stratified_report(
    results: list[EvalResult],
    *,
    calibration_bins: int = 10,
    abstain_threshold: float = 0.5,
) -> dict[str, object]:
    """Report overall and non-collapsible query-class/split/stratum metrics."""
    if not results:
        raise ValueError("cannot report over zero evaluation results")
    if not 0.0 <= abstain_threshold <= 1.0:
        raise ValueError("abstain_threshold must be in [0, 1]")
    return {
        "schema_version": EVAL_SCHEMA_VERSION,
        "versions": dict(PROTOCOL_VERSIONS),
        "abstain_threshold": abstain_threshold,
        "overall": _group_summary(results, calibration_bins, abstain_threshold),
        "by_query_class": _grouped_summary(
            results,
            lambda result: (result.query_class,),
            calibration_bins,
            abstain_threshold,
        ),
        "by_split": _grouped_summary(
            results,
            lambda result: (result.split or "unspecified",),
            calibration_bins,
            abstain_threshold,
        ),
        "by_stratum": _grouped_summary(
            results,
            lambda result: result.strata or ("unspecified",),
            calibration_bins,
            abstain_threshold,
        ),
    }


def _grouped_summary(
    results: list[EvalResult],
    keys,
    calibration_bins: int,
    abstain_threshold: float,
) -> dict[str, object]:
    groups: dict[str, list[EvalResult]] = {}
    for result in results:
        for key in keys(result):
            groups.setdefault(key, []).append(result)
    return {
        key: _group_summary(group, calibration_bins, abstain_threshold)
        for key, group in sorted(groups.items())
    }


def _group_summary(
    results: list[EvalResult],
    calibration_bins: int,
    abstain_threshold: float,
) -> dict[str, object]:
    node_recalls = [result.node_recall for result in results if result.node_recall is not None]
    edge_recalls = [result.edge_recall for result in results if result.edge_recall is not None]
    facets = [result.facet_completeness for result in results if result.facet_completeness is not None]
    pairs = _calibration_pairs(results)
    utilities = _abstention_utilities(results, abstain_threshold)
    latency: dict[str, dict[str, object]] = {}
    for state in sorted({result.latency_state for result in results if result.latency_ms is not None}):
        samples = sorted(
            float(result.latency_ms)
            for result in results
            if result.latency_ms is not None and result.latency_state == state
        )
        latency[state] = {
            "count": len(samples),
            "p50": round(_quantile(samples, 0.5), 4),
            "p95": round(_quantile(samples, 0.95), 4),
            "samples": samples,
        }
    failing = sorted(
        result.task_id or result.query
        for result in results
        if _is_failure(result, abstain_threshold)
    )
    return {
        "count": len(results),
        "scored_count": sum(result.scored for result in results),
        "node_recall_mean": _mean_or_none(node_recalls),
        "edge_recall_mean": _mean_or_none(edge_recalls),
        "mrr_mean": round(fmean(result.mrr for result in results), 6),
        "ndcg_at_5_mean": round(fmean(result.ndcg_at_5 for result in results), 6),
        "ndcg_at_10_mean": round(fmean(result.ndcg_at_10 for result in results), 6),
        "facet_completeness_mean": _mean_or_none(facets),
        "tokens": _distribution([float(result.token_estimate) for result in results]),
        "latency_ms": latency,
        "calibration": asdict(calibration_report(pairs, bins=calibration_bins)) if pairs else None,
        "abstention": {
            "count": len(utilities),
            "utility_mean": _mean_or_none(utilities),
        },
        "failing_tasks": failing,
    }


def paired_bootstrap_comparison(
    incumbent: list[EvalResult],
    candidate: list[EvalResult],
    *,
    metric: str,
    minimum_effect: float,
    samples: int = 10_000,
    seed: int = 1337,
    confidence: float = 0.95,
) -> dict[str, object]:
    """Paired percentile bootstrap over stable task identities."""
    if metric not in {"node_recall", "edge_recall", "mrr", "ndcg_at_5", "ndcg_at_10", "facet_completeness"}:
        raise ValueError(f"unsupported comparison metric: {metric}")
    if minimum_effect < 0.0:
        raise ValueError("minimum_effect must be non-negative")
    if samples < 1:
        raise ValueError("samples must be >= 1")
    if not 0.0 < confidence < 1.0:
        raise ValueError("confidence must be in (0, 1)")
    incumbent_by_id = _result_map(incumbent)
    candidate_by_id = _result_map(candidate)
    matched = sorted(incumbent_by_id.keys() & candidate_by_id.keys())
    deltas: list[float] = []
    task_ids: list[str] = []
    for task_id in matched:
        left = getattr(incumbent_by_id[task_id], metric)
        right = getattr(candidate_by_id[task_id], metric)
        if left is None or right is None:
            continue
        task_ids.append(task_id)
        deltas.append(float(right) - float(left))
    if not deltas:
        raise ValueError("paired comparison has no matched scored tasks")

    rng = random.Random(seed)
    size = len(deltas)
    boot = sorted(fmean(deltas[rng.randrange(size)] for _ in range(size)) for _ in range(samples))
    alpha = (1.0 - confidence) / 2.0
    lower = _quantile(boot, alpha)
    upper = _quantile(boot, 1.0 - alpha)
    mean_delta = fmean(deltas)
    verdict = "inconclusive"
    if lower >= minimum_effect:
        verdict = "promote"
    elif upper <= -minimum_effect:
        verdict = "reject"
    return {
        "metric": metric,
        "matched_tasks": len(deltas),
        "task_ids": task_ids,
        "mean_delta": round(mean_delta, 8),
        "confidence": confidence,
        "confidence_interval": [round(lower, 8), round(upper, 8)],
        "minimum_effect": minimum_effect,
        "improved": sum(delta > 0.0 for delta in deltas),
        "tied": sum(delta == 0.0 for delta in deltas),
        "regressed": sum(delta < 0.0 for delta in deltas),
        "bootstrap_samples": samples,
        "seed": seed,
        "verdict": verdict,
    }


def load_eval_results(path: Path) -> list[EvalResult]:
    """Load a saved result list or a report envelope containing ``results``."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvalProtocolError(f"could not read evaluation results from {path}: {exc}") from exc
    if isinstance(data, dict):
        data = data.get("results")
    if not isinstance(data, list) or not data:
        raise EvalProtocolError(f"{path}: expected a non-empty result list or an object containing results")
    allowed = {field.name for field in fields(EvalResult)}
    results: list[EvalResult] = []
    for index, item in enumerate(data):
        if not isinstance(item, dict):
            raise EvalProtocolError(f"{path}: result {index} must be an object")
        unknown = set(item) - allowed
        if unknown:
            raise EvalProtocolError(f"{path}: result {index} has unknown fields: {sorted(unknown)}")
        normalized = dict(item)
        for field_name in ("strata", "expected_unresolved"):
            if isinstance(normalized.get(field_name), list):
                normalized[field_name] = tuple(normalized[field_name])
        try:
            results.append(EvalResult(**normalized))
        except TypeError as exc:
            raise EvalProtocolError(f"{path}: invalid result {index}: {exc}") from exc
    return results


def deterministic_result_signature(results: list[EvalResult]) -> str:
    """Canonical non-latency signature used to reject noisy eval baselines."""
    payload = []
    for result in results:
        item = asdict(result)
        item.pop("latency_ms", None)
        payload.append(item)
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _calibration_pairs(results: list[EvalResult]) -> list[tuple[float, bool]]:
    pairs: list[tuple[float, bool]] = []
    for result in results:
        confidence = result.answerability_confidence
        if confidence is None or result.expected_unresolved_count:
            continue
        if result.expected_answerable is False:
            pairs.append((confidence, False))
            continue
        recalls = [value for value in (result.node_recall, result.edge_recall) if value is not None]
        if recalls:
            complete = all(value >= 1.0 for value in recalls)
            if result.facet_completeness is not None:
                complete = complete and result.facet_completeness >= 1.0
            pairs.append((confidence, complete))
    return pairs


def _abstention_utilities(results: list[EvalResult], threshold: float) -> list[float]:
    utilities: list[float] = []
    for result in results:
        confidence = result.answerability_confidence
        if confidence is None:
            continue
        expected_answerable = result.expected_answerable
        if expected_answerable is None:
            if not result.scored:
                continue
            expected_answerable = True
        abstained = confidence < threshold
        if expected_answerable is False:
            utilities.append(1.0 if abstained else -1.0)
            continue
        complete = all(
            value >= 1.0
            for value in (result.node_recall, result.edge_recall, result.facet_completeness)
            if value is not None
        )
        utilities.append(1.0 if not abstained and complete else -1.0)
    return utilities


def _is_failure(result: EvalResult, threshold: float) -> bool:
    if result.expected_unresolved_count:
        return True
    confidence = result.answerability_confidence
    if result.expected_answerable is False:
        return confidence is not None and confidence >= threshold
    values = (result.node_recall, result.edge_recall, result.facet_completeness)
    return any(value is not None and value < 1.0 for value in values)


def _result_map(results: list[EvalResult]) -> dict[str, EvalResult]:
    mapped: dict[str, EvalResult] = {}
    for result in results:
        task_id = result.task_id or result.query
        if task_id in mapped:
            raise ValueError(f"duplicate paired task identity: {task_id!r}")
        mapped[task_id] = result
    return mapped


def _distribution(values: list[float]) -> dict[str, object]:
    ordered = sorted(values)
    return {
        "count": len(ordered),
        "mean": round(fmean(ordered), 6),
        "p50": round(_quantile(ordered, 0.5), 6),
        "p95": round(_quantile(ordered, 0.95), 6),
        "samples": ordered,
    }


def _quantile(values: list[float], probability: float) -> float:
    if not values:
        raise ValueError("cannot compute a quantile over zero values")
    position = (len(values) - 1) * probability
    lower = int(position)
    upper = min(len(values) - 1, lower + 1)
    weight = position - lower
    return values[lower] * (1.0 - weight) + values[upper] * weight


def _mean_or_none(values) -> float | None:
    materialized = list(values)
    return round(fmean(materialized), 6) if materialized else None


def _identifier_tokens(value: str) -> set[str]:
    normalized = re.sub(r"[_./\\:-]+", " ", value)
    return {part.lower() for part in _IDENTIFIER_PART.findall(normalized) if len(part) > 1}


def _read_object(path: Path) -> dict[str, object]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvalProtocolError(f"could not read evaluation protocol file {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise EvalProtocolError(f"{path}: expected a JSON object")
    return data


def _require_version_block(data: dict[str, object], path: Path) -> None:
    if data.get("schema_version") != EVAL_SCHEMA_VERSION:
        raise EvalProtocolError(f"{path}: schema_version must be {EVAL_SCHEMA_VERSION!r}")
    versions = data.get("versions")
    if versions != PROTOCOL_VERSIONS:
        raise EvalProtocolError(f"{path}: versions must equal {PROTOCOL_VERSIONS!r}")


def _required_text(data: dict[str, object], field: str, path: Path) -> str:
    value = data.get(field)
    if not isinstance(value, str) or not value.strip():
        raise EvalProtocolError(f"{path}: {field} must be a non-empty string")
    return value.strip()


def _text_tuple(value: object, *, field: str, path: Path) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise EvalProtocolError(f"{path}: {field} must be a list of non-empty strings")
    return tuple(item.strip() for item in value)
