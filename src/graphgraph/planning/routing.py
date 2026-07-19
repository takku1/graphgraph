"""Automatic query-class routing as an additive log-linear intent classifier.

Model
-----
Each query class starts from a prior, accrues weight from every lexical intent
signal that fires, and receives a few context-dependent adjustments. The winner
is the highest-scoring class, ties broken by a fixed precedence prior. When no
class is decisive the router abstains to a broad fallback. Confidence is a convex
blend of normalized evidence strength and margin separation.

    score(c)   = prior(c) + Σ signal_weight(c) + Σ context_adjustment(c)
    winner     = argmax_c (score(c), precedence(c))
    margin     = score(winner) − score(runner_up)
    confidence = w_e · clamp01(score/EVIDENCE_SCALE)
               + w_s · clamp01(margin/SEPARATION_SCALE)

The weights and scales are hand-set priors. Replacing the confidence blend with a
calibrated multinomial-logit (softmax) posterior is deferred to the evaluation
loop (`graphgraph.acceptance.quality`), because it shifts the abstention
boundary and must be measured, not guessed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .budgets import explicit_query_identifiers, plan_terms

ROUTER_VERSION = "query_router_v3_calibrated_recovery"

# Broad class used both as the default prior and the low-evidence fallback.
BROAD_FALLBACK = "subsystem_summary"
BROAD_FALLBACK_PRIOR = 0.75

# Repeated wording should compound but never dominate the score.
REPEAT_SIGNAL_WEIGHT = 2.0
MAX_COMPOUNDED_REPEATS = 2

# Abstention boundary: keep the broad fallback unless the winner is decisive.
DECISIVE_SCORE = 5.0
MIN_WINNING_SCORE = 2.0
MIN_DECISIVE_MARGIN = 0.75

# Confidence blend: convex combination of normalized evidence and separation.
EVIDENCE_WEIGHT = 0.65
SEPARATION_WEIGHT = 0.35
EVIDENCE_SCALE = 6.0  # score at which evidence strength saturates to 1.0
SEPARATION_SCALE = 4.0  # margin at which separation saturates to 1.0


@dataclass(frozen=True)
class QueryRoute:
    query_class: str
    confidence: float
    margin: float
    reasons: tuple[str, ...]
    router_version: str = ROUTER_VERSION


# Primary lexical signals: (query_class, weight, reason, pattern).
_SIGNALS: tuple[tuple[str, float, str, re.Pattern[str]], ...] = (
    ("affected_tests", 7.0, "affected-test intent", re.compile(
        r"\b(affected tests?|which tests? (?:are affected|cover|exercise|should run|to run)|"
        r"what tests? (?:are affected|cover|exercise|should run|to run)|"
        r"tests? (?:cover|exercise|should run|to run)|test selection|"
        r"(?:direct|transitive|behavioral|affected) tests?|"
        r"(?:which|what|identify|find|list|return).{0,80}\btests?\b.{0,80}"
        r"(?:affected|cover|exercise|direct|transitive|should run|to run)|"
        r"(?:minimal runnable )?(?:cargo )?test commands?)\b"
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

# Unconditional context signals, applied identically to the primary signals but
# without the repeat-compounding bonus.
_CONTEXT_SIGNALS: tuple[tuple[str, float, str, re.Pattern[str]], ...] = (
    ("multi_hop_path", 3.0, "trace intent", re.compile(r"\btrace\b")),
    ("negative_query", 5.0, "existence probe",
     re.compile(r"^\s*(?:is\s+)?(?:there\s+)?(?:a\s+)?missing\b|\bdoes .{0,80}\bexist\b")),
    ("reverse_lookup", 8.0, "consumer/test usage intent",
     re.compile(r"\bwhich tests? (?:uses?|consumes?|calls?|verifies?)\b")),
)

# Identifier-conditioned adjustments (weights applied only when the identifier
# precondition also holds).
_GENERIC_LOOKUP_RE = re.compile(r"\b(what is|where|show|find|locate)\b")
_RELATION_BETWEEN_RE = re.compile(r"\b(depends? on|dependency between|connects? to|relationship between)\b")
MULTI_SYMBOL_DEPENDENCY_WEIGHT = 5.5
FOCUSED_IDENTIFIER_WEIGHT = 3.0
FOCUSED_IDENTIFIER_MAX_TERMS = 2

# Tie-break priors: higher wins when two classes share a score.
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


def _clamp01(value: float) -> float:
    return min(1.0, max(0.0, value))


def _route_confidence(top_score: float, margin: float) -> float:
    """Convex blend of normalized evidence strength and margin separation."""
    evidence = _clamp01(top_score / EVIDENCE_SCALE)
    separation = _clamp01(margin / SEPARATION_SCALE)
    return EVIDENCE_WEIGHT * evidence + SEPARATION_WEIGHT * separation


def route_query(query: str, requested_class: str | None = "auto") -> QueryRoute:
    """Resolve an explicit or automatic query class with no I/O."""
    requested = (requested_class or "auto").strip().lower()
    if requested and requested != "auto":
        return QueryRoute(requested, 1.0, 1.0, ("explicit query class",))

    normalized = " ".join((query or "").lower().split())
    scores = {name: 0.0 for name in _PRECEDENCE}
    reasons: dict[str, list[str]] = {name: [] for name in _PRECEDENCE}
    scores[BROAD_FALLBACK] = BROAD_FALLBACK_PRIOR
    reasons[BROAD_FALLBACK].append("safe broad fallback")

    for query_class, weight, reason, pattern in _SIGNALS:
        matches = tuple(pattern.finditer(normalized))
        if matches:
            repeats = min(MAX_COMPOUNDED_REPEATS, len(matches) - 1)
            scores[query_class] += weight + repeats * REPEAT_SIGNAL_WEIGHT
            reasons[query_class].append(reason)

    for query_class, weight, reason, pattern in _CONTEXT_SIGNALS:
        if pattern.search(normalized):
            scores[query_class] += weight
            reasons[query_class].append(reason)

    identifiers = explicit_query_identifiers(query)
    terms = plan_terms(query)
    if len(identifiers) >= 2 and _RELATION_BETWEEN_RE.search(normalized):
        scores["multi_hop_path"] += MULTI_SYMBOL_DEPENDENCY_WEIGHT
        reasons["multi_hop_path"].append("explicit multi-symbol dependency intent")
    if identifiers and (_GENERIC_LOOKUP_RE.search(normalized) or len(terms) <= FOCUSED_IDENTIFIER_MAX_TERMS):
        scores["direct_lookup"] += FOCUSED_IDENTIFIER_WEIGHT
        reasons["direct_lookup"].append("focused code identifier")

    ordered = sorted(scores, key=lambda name: (scores[name], _PRECEDENCE[name]), reverse=True)
    winner, runner_up = ordered[:2]
    top_score = scores[winner]
    margin = top_score - scores[runner_up]

    indecisive = top_score < MIN_WINNING_SCORE or (top_score < DECISIVE_SCORE and margin < MIN_DECISIVE_MARGIN)
    if indecisive:
        winner = BROAD_FALLBACK
        top_score = scores[winner]
        other_best = max(score for name, score in scores.items() if name != winner)
        margin = max(0.0, top_score - other_best)
        reasons[winner].append("ambiguous intent kept broad")

    confidence = _route_confidence(top_score, margin)
    return QueryRoute(winner, confidence, margin, tuple(dict.fromkeys(reasons[winner])))
