from __future__ import annotations

import re
from dataclasses import dataclass

from .budgets import explicit_query_identifiers, plan_terms


@dataclass(frozen=True)
class QueryRoute:
    query_class: str
    confidence: float
    margin: float
    reasons: tuple[str, ...]
    router_version: str = "query_router_v3_calibrated_recovery"


_SIGNALS: tuple[tuple[str, float, str, re.Pattern[str]], ...] = (
    ("affected_tests", 7.0, "affected-test intent", re.compile(
        r"\b(affected tests?|which tests? (?:are affected|cover|exercise|should run|to run)|"
        r"what tests? (?:are affected|cover|exercise|should run|to run)|"
        r"tests? (?:cover|exercise|should run|to run)|test selection)\b"
    )),
    ("recent_changes", 6.0, "recent/history intent", re.compile(
        r"\b(recent(?:ly)? changed|change history|git history|last commits?|recent commits?|what changed|modified recently)\b"
    )),
    ("negative_query", 6.0, "absence/isolation intent", re.compile(
        r"\b(unused|unreferenced|orphaned|isolated|dead code|no callers?|no references?|nothing (?:calls|uses|imports))\b"
    )),
    ("multi_hop_path", 6.0, "path/flow intent", re.compile(
        r"\b(path (?:from|between)|call chain|dependency chain|data flow|control flow|how .{0,80}\b(?:reach|flow|propagate)\b|trace .{0,80}\b(?:to|through|into)\b)"
    )),
    ("blast_radius", 6.0, "impact intent", re.compile(
        r"\b(blast radius|change impact|impact of|what (?:breaks|is affected)|affected by|if .{0,80}\bchanges?)\b"
    )),
    ("reverse_lookup", 5.0, "reverse dependency intent", re.compile(
        r"\b(callers?|called by|references?|referenced by|used by|users of|dependents?|implements?|implementors?|implemented by|where .{0,80}\btested|what calls|who calls)\b"
    )),
    ("doc_summary", 5.0, "documentation intent", re.compile(
        r"\b(readme|documentation|docs|installation|installing|usage guide|setup guide|tutorial|manual|"
        r"roadmap|backlog|milestones?|ordered (?:execution|work)|phases?|what (?:work )?(?:comes|happens) next|"
        r"before (?:new )?capabilit)\b"
    )),
    ("direct_lookup", 4.0, "definition/location intent", re.compile(
        r"\b(where (?:is|are)|locate|find (?:the )?(?:definition|implementation)|defined in|definition of|show (?:me )?(?:the )?(?:source|definition))\b"
    )),
    ("subsystem_summary", 3.0, "architecture/overview intent", re.compile(
        r"\b(architecture|overview|subsystem|how (?:does|is|are) .{0,80}\b(?:work|designed|structured)|design of|project status|what remains|unfinished|roadmap)\b"
    )),
)

_TRACE_RE = re.compile(r"\btrace\b")
_MISSING_RE = re.compile(r"^\s*(?:is\s+)?(?:there\s+)?(?:a\s+)?missing\b|\bdoes .{0,80}\bexist\b")
_GENERIC_LOOKUP_RE = re.compile(r"\b(what is|where|show|find|locate)\b")
_RELATION_BETWEEN_RE = re.compile(r"\b(depends? on|dependency between|connects? to|relationship between)\b")
_CONSUMER_RE = re.compile(r"\bwhich tests? (?:uses?|consumes?|calls?|verifies?)\b")
_PRECEDENCE = {
    "affected_tests": 9,
    "negative_query": 8,
    "recent_changes": 7,
    "multi_hop_path": 6,
    "blast_radius": 5,
    "reverse_lookup": 4,
    "doc_summary": 3,
    "direct_lookup": 2,
    "subsystem_summary": 1,
}


def route_query(query: str, requested_class: str | None = "auto") -> QueryRoute:
    """Resolve an explicit or automatic query class with no I/O."""
    requested = (requested_class or "auto").strip().lower()
    if requested and requested != "auto":
        return QueryRoute(requested, 1.0, 1.0, ("explicit query class",))

    normalized = " ".join((query or "").lower().split())
    scores = {name: 0.0 for name in _PRECEDENCE}
    reasons: dict[str, list[str]] = {name: [] for name in _PRECEDENCE}
    scores["subsystem_summary"] = 0.75
    reasons["subsystem_summary"].append("safe broad fallback")

    for query_class, weight, reason, pattern in _SIGNALS:
        matches = tuple(pattern.finditer(normalized))
        if matches:
            # Independent cues should compound, but cap the bonus so repeated
            # wording cannot dominate the router.
            scores[query_class] += weight + min(2, len(matches) - 1) * 2.0
            reasons[query_class].append(reason)

    if _TRACE_RE.search(normalized):
        scores["multi_hop_path"] += 3.0
        reasons["multi_hop_path"].append("trace intent")
    if _MISSING_RE.search(normalized):
        scores["negative_query"] += 5.0
        reasons["negative_query"].append("existence probe")
    if _CONSUMER_RE.search(normalized):
        scores["reverse_lookup"] += 8.0
        reasons["reverse_lookup"].append("consumer/test usage intent")

    identifiers = explicit_query_identifiers(query)
    terms = plan_terms(query)
    if len(identifiers) >= 2 and _RELATION_BETWEEN_RE.search(normalized):
        scores["multi_hop_path"] += 5.5
        reasons["multi_hop_path"].append("explicit multi-symbol dependency intent")
    if identifiers and (_GENERIC_LOOKUP_RE.search(normalized) or len(terms) <= 2):
        scores["direct_lookup"] += 3.0
        reasons["direct_lookup"].append("focused code identifier")

    ordered = sorted(scores, key=lambda name: (scores[name], _PRECEDENCE[name]), reverse=True)
    winner, runner_up = ordered[:2]
    top_score = scores[winner]
    margin = top_score - scores[runner_up]
    if top_score < 2.0 or (top_score < 5.0 and margin < 0.75):
        winner = "subsystem_summary"
        top_score = scores[winner]
        other_best = max(score for name, score in scores.items() if name != winner)
        margin = max(0.0, top_score - other_best)
        reasons[winner].append("ambiguous intent kept broad")

    evidence_strength = min(1.0, max(0.0, top_score) / 6.0)
    separation = min(1.0, max(0.0, margin) / 4.0)
    confidence = 0.65 * evidence_strength + 0.35 * separation
    return QueryRoute(winner, confidence, margin, tuple(dict.fromkeys(reasons[winner])))
