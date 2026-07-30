"""Machine-checkable claim/candidate/experiment registry for research tournaments."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

CLAIM_STATUSES = frozenset(
    {"idea", "specified", "prototype", "measured", "rejected", "promoted", "normative", "implemented"}
)
CANDIDATE_STATUSES = frozenset(
    {"idea", "specified", "prototype", "measured", "rejected", "promoted", "implemented", "deferred"}
)
EXPERIMENT_STATUSES = frozenset({"pending", "implemented", "passing", "failing", "inconclusive", "superseded"})


def load_research_registry(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _duplicate_ids(rows: list[dict[str, Any]], key: str) -> list[str]:
    seen: set[str] = set()
    duplicate: set[str] = set()
    for row in rows:
        value = str(row.get(key) or "")
        if value in seen:
            duplicate.add(value)
        seen.add(value)
    return sorted(duplicate)


def validate_research_registry(registry: dict[str, Any], *, root: Path | None = None) -> list[str]:
    errors: list[str] = []
    claims = list(registry.get("claims") or [])
    candidates = list(registry.get("candidates") or [])
    experiments = list(registry.get("experiments") or [])
    for rows, key, label in (
        (claims, "claim_id", "claim"),
        (candidates, "candidate_id", "candidate"),
        (experiments, "experiment_id", "experiment"),
    ):
        for duplicate in _duplicate_ids(rows, key):
            errors.append(f"duplicate {label} id: {duplicate}")
        for row in rows:
            if not row.get(key):
                errors.append(f"{label} missing {key}")

    claim_ids = {str(row.get("claim_id")) for row in claims}
    candidate_ids = {str(row.get("candidate_id")) for row in candidates}
    experiment_ids = {str(row.get("experiment_id")) for row in experiments}

    for claim in claims:
        claim_id = str(claim.get("claim_id"))
        status = str(claim.get("status"))
        if status not in CLAIM_STATUSES:
            errors.append(f"{claim_id}: invalid claim status {status!r}")
        if not claim.get("source") or not claim.get("mechanism"):
            errors.append(f"{claim_id}: source and mechanism are required")
        linked = tuple(str(value) for value in claim.get("experiment_ids") or ())
        if status not in {"idea", "normative", "implemented"} and not linked:
            errors.append(f"{claim_id}: empirical claim has no experiment")
        for experiment_id in linked:
            if experiment_id not in experiment_ids:
                errors.append(f"{claim_id}: unknown experiment {experiment_id}")
        if status in {"measured", "rejected", "promoted"} and not claim.get("evidence"):
            errors.append(f"{claim_id}: terminal evidence status requires immutable evidence")
        if root is not None and claim.get("source"):
            source_path = str(claim["source"]).split("#", 1)[0]
            if not (root / source_path).exists():
                errors.append(f"{claim_id}: source path does not exist: {source_path}")

    # A candidate is only meaningful if some experiment can decide it. Without
    # this rule the ledger enforces "no claim without an experiment" but lets an
    # implementation ship with no gate at all -- which is how a candidate
    # reached the production CLI while still recorded as `specified`.
    tested_candidates = {
        str(candidate_id)
        for experiment in experiments
        for candidate_id in experiment.get("candidate_ids") or ()
    }
    for candidate in candidates:
        candidate_id = str(candidate.get("candidate_id"))
        status = str(candidate.get("status"))
        if status not in CANDIDATE_STATUSES:
            errors.append(f"{candidate_id}: invalid candidate status {status!r}")
        for field in ("stage", "algorithm", "fallback", "complexity"):
            if not candidate.get(field):
                errors.append(f"{candidate_id}: missing {field}")
        if status not in {"idea"} and candidate_id not in tested_candidates:
            errors.append(f"{candidate_id}: candidate has no experiment")

    for experiment in experiments:
        experiment_id = str(experiment.get("experiment_id"))
        status = str(experiment.get("status"))
        if status not in EXPERIMENT_STATUSES:
            errors.append(f"{experiment_id}: invalid experiment status {status!r}")
        for claim_id in experiment.get("claim_ids") or ():
            if str(claim_id) not in claim_ids:
                errors.append(f"{experiment_id}: unknown claim {claim_id}")
        for candidate_id in experiment.get("candidate_ids") or ():
            if str(candidate_id) not in candidate_ids:
                errors.append(f"{experiment_id}: unknown candidate {candidate_id}")
        for field in ("primary_metric", "budgets", "baselines", "stop_condition"):
            if not experiment.get(field):
                errors.append(f"{experiment_id}: missing {field}")
        if status in {"passing", "failing", "inconclusive", "superseded"} and not experiment.get("artifacts"):
            errors.append(f"{experiment_id}: completed experiment requires artifacts")
        if root is not None:
            for artifact in experiment.get("artifacts") or ():
                if not (root / str(artifact)).exists():
                    errors.append(f"{experiment_id}: artifact does not exist: {artifact}")
    return errors


__all__ = ["load_research_registry", "validate_research_registry"]
