from __future__ import annotations

MIN_SUPPORTED_CONCEPT_COVERAGE = 0.20
STRONG_CONCEPT_COVERAGE = 0.80


def concept_link_health(eligible_nodes: int, linked_nodes: int) -> dict[str, object]:
    """Classify whether semantic edges are usable as retrieval evidence."""
    coverage = linked_nodes / max(1, eligible_nodes)
    if eligible_nodes <= 0:
        status = "unavailable"
        reason = "no source nodes were eligible for concept linking"
    elif linked_nodes <= 0:
        status = "unavailable"
        reason = "concept linking produced no exact registry-alias links"
    elif coverage < MIN_SUPPORTED_CONCEPT_COVERAGE:
        status = "sparse"
        reason = (
            f"coverage {coverage:.2%} is below the supported semantic-evidence "
            f"threshold {MIN_SUPPORTED_CONCEPT_COVERAGE:.0%}"
        )
    elif coverage < STRONG_CONCEPT_COVERAGE:
        status = "partial"
        reason = "semantic links are usable but do not cover most eligible source nodes"
    else:
        status = "strong"
        reason = ""
    return {
        "status": status,
        "coverage_ratio": round(coverage, 4),
        "minimum_supported_coverage_ratio": MIN_SUPPORTED_CONCEPT_COVERAGE,
        "diagnostic_reason": reason,
        "supported": status in {"partial", "strong"},
    }
