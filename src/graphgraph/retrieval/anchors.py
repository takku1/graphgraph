"""Anchor match selection, scoring shape, and doc-root selection."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, replace

from ..concepts import (
    INTERPRETATION_CONCEPT_IDS,
)
from ..concepts.terms import term_key
from ..graph.core import Graph
from ..planning import ContextPlan
from ..planning.budgets import explicit_query_identifiers, plan_terms
from ..planning.shape import profile_graph_shape, recommend_node_budget
from .facets import (
    _affected_output_contract_facet,
    _facet_evidence_terms,
    _facet_label_matched_terms,
    _facet_matched_terms,
    _facet_matched_text_terms,
    _facet_matches_node,
    _facet_node_text,
    _symbol_identity_terms,
    query_facets,
)
from .models import Match
from .scoping import (
    _ENUMERATED_DOC_QUERY,
    _FLOW_ORIENTATION_QUERY,
    _ORDERED_DOC_QUERY,
    NON_STRUCTURAL_KINDS,
    STRUCTURAL_QUERY_CLASSES,
    STRUCTURAL_RELATIONS,
    _is_test_node,
    _package_scope,
    _path_in_scopes,
    _qualified_query_symbols,
    structural_anchor_query,
)
from .search import search_nodes


def interpretation_concept_anchor_matches(
    graph: Graph,
    query: str,
    *,
    scopes: tuple[str, ...] = (),
) -> tuple[Match, ...]:
    """Resolve registry concept labels embedded in natural-language queries."""
    # Global concept hubs have no source path. Until scoped traversal can keep
    # a hub while constraining only its neighbors, leave strict scoped queries
    # on the existing path-local ranker.
    if scopes:
        return ()
    query_key = f" {re.sub(r'[^a-z0-9 ]+', ' ', term_key(query))} "
    matches: list[Match] = []
    for node_id in INTERPRETATION_CONCEPT_IDS:
        node = graph.nodes.get(node_id)
        if node is None or not node.active:
            continue
        label_key = term_key(node.label)
        if label_key and f" {label_key} " in query_key:
            matches.append(Match(
                node=node,
                score=64.0 + min(4.0, len(label_key.split()) * 0.5),
                reasons=(
                    "interpretation_registry_exact_phrase",
                    "exact_fast_path",
                ),
            ))
    return tuple(sorted(matches, key=lambda match: (-match.score, match.node.id)))

def preferred_path_anchor_matches(
    graph: Graph,
    query: str,
    query_class: str,
    paths: tuple[str, ...],
    facets: tuple[tuple[str, tuple[str, ...]], ...],
) -> tuple[Match, ...]:
    """Compile exact edited paths into bounded per-file/per-facet anchor hints."""
    anchor_query = structural_anchor_query(query, query_class)
    # Exact-path locality is already strong evidence. Retain process terms
    # here (for example ``receipt consistency`` -> ``reconcile_*_receipt``)
    # so a relevant symbol can win without allowing those generic terms to
    # become global anchors.
    term_groups = list(facets)
    if not term_groups:
        terms = plan_terms(anchor_query)
        if terms:
            term_groups = [(anchor_query, terms)]
    named_owner_groups = tuple(
        terms
        for label, terms in facets
        if "_" in label or any(char.isupper() for char in label[1:])
    )
    named_owner_terms = tuple(dict.fromkeys(
        term for terms in named_owner_groups for term in terms
    ))
    degree: dict[str, int] = {}
    for edge in graph.edges:
        if edge.active:
            degree[edge.source] = degree.get(edge.source, 0) + 1
            degree[edge.target] = degree.get(edge.target, 0) + 1
    max_degree = max(degree.values(), default=0)

    normalized_paths = tuple(
        dict.fromkeys(path.replace("\\", "/").strip("/") for path in paths)
    )
    nodes_by_path: dict[str, list[object]] = {path: [] for path in normalized_paths}
    for node in graph.nodes.values():
        normalized = node.path.replace("\\", "/").strip("/")
        if node.active and normalized in nodes_by_path:
            nodes_by_path[normalized].append(node)

    file_node_kinds = {
        "python", "rust", "javascript", "typescript", "go", "java", "c", "cpp",
        "csharp", "ruby", "php", "kotlin", "scala", "swift",
        # Exact changed paths are I/O roots, including documentation. A blast
        # request must not discard an explicitly changed Markdown file merely
        # because structural traversal normally deprioritizes prose nodes.
        "file", "markdown", "rst", "html", "text",
    }
    per_path: list[list[Match]] = []
    for normalized in normalized_paths:
        path_nodes = nodes_by_path.get(normalized, ())
        file_nodes = [node for node in path_nodes if node.kind in file_node_kinds]
        eligible_nodes = [
            node
            for node in path_nodes
            if node.kind not in file_node_kinds
            if query_class == "doc_summary" or node.kind not in NON_STRUCTURAL_KINDS
            if not (query_class == "affected_tests" and _is_test_node(node))
        ]
        candidates: dict[str, Match] = {}
        query_winners: list[str] = []
        for label, terms in term_groups:
            if not terms:
                continue
            local_matches: list[Match] = []
            for node in eligible_nodes:
                hits = _facet_matched_terms(node, terms)
                if not hits:
                    continue
                label_hits = _facet_label_matched_terms(node, terms)
                owner_hits = _facet_matched_text_terms(
                    term_key(str(getattr(node, "id", ""))),
                    named_owner_terms,
                )
                owner_supported = any(
                    set(owner_terms) <= owner_hits
                    for owner_terms in named_owner_groups
                )
                required_hits = max(1, math.floor(len(terms) / 2) + 1)
                if len(hits) < required_hits:
                    # One generic word from a compound facet is not enough to
                    # make an exact-path symbol relevant (for example an
                    # `ideals_equal` helper answering "pinned corpus
                    # equality"). Fall back to the file when no symbol reaches
                    # this bounded evidence threshold.
                    continue
                if (
                    len(normalized_paths) > 1
                    and named_owner_groups
                    and not owner_supported
                    and not hits <= label_hits
                ):
                    # In a multi-slice request, a behavior word found only in
                    # a summary/fact does not bind that facet to every changed
                    # file. Require a named owner in the node identity or keep
                    # every matched behavior term in the symbol identity.
                    continue
                term_count = max(1, len(terms))
                coverage = len(hits) / term_count
                identity_coverage = len(label_hits) / term_count
                owner_coverage = max(
                    (
                        len(set(owner_terms) & owner_hits) / max(1, len(owner_terms))
                        for owner_terms in named_owner_groups
                    ),
                    default=0.0,
                )
                centrality = (
                    math.log2(degree.get(node.id, 0) + 1)
                    / math.log2(max_degree + 1)
                    if max_degree > 0
                    else 0.0
                )
                # Dimensionless evidence score: semantic coverage, identity
                # coverage, owner coherence, then a query-complexity-damped
                # topology tie-breaker. No repository-specific tuned weights.
                score = coverage + identity_coverage + owner_coverage + centrality / term_count
                local_matches.append(Match(
                    node,
                    score,
                    ("exact_changed_path_terms", f"facet:{label}"),
                ))
            if local_matches:
                winner = max(
                    local_matches,
                    key=lambda match: (
                        term_key(match.node.label) == term_key(label),
                        match.score,
                        degree.get(match.node.id, 0),
                        match.node.id,
                    ),
                )
                query_winners.append(winner.node.id)
                # A path is a hard locality constraint, not evidence that every
                # symbol in the file answers the facet. Keep one winner per
                # facet/path; traversal can recover its real neighbors.
                prior = candidates.get(winner.node.id)
                if prior is None or winner.score > prior.score:
                    candidates[winner.node.id] = winner
        if not candidates:
            fallback = max(
                file_nodes,
                key=lambda node: (degree.get(node.id, 0), node.id),
                default=None,
            )
            if fallback is not None:
                candidates[fallback.id] = Match(fallback, 0.0, ("file_fallback",))
        if not candidates:
            continue
        winner_ids = set(query_winners)
        ranked = sorted(
            candidates.values(),
            key=lambda match: (
                match.node.id not in winner_ids,
                -match.score,
                -degree.get(match.node.id, 0),
                match.node.id,
            ),
        )
        per_path.append(ranked)

    candidate_pool = {
        match.node.id: match
        for ranked in per_path
        for match in ranked
    }
    ordered: list[Match] = []
    for _label, terms in facets:
        evidence_terms = _facet_evidence_terms(terms)
        eligible = [
            match
            for match in candidate_pool.values()
            if _facet_matches_node(match.node, evidence_terms)
        ]
        if eligible:
            ordered.append(max(
                eligible,
                key=lambda match: (match.score, degree.get(match.node.id, 0), match.node.id),
            ))
    ordered.extend(ranked[0] for ranked in per_path if ranked)
    depth = 1
    max_depth = max((len(ranked) for ranked in per_path), default=0)
    while depth < max_depth:
        added = False
        for ranked in per_path:
            if depth < len(ranked):
                ordered.append(ranked[depth])
                added = True
        if not added:
            break
        depth += 1

    preferred: list[Match] = []
    seen: set[str] = set()
    for match in ordered:
        if match.node.id in seen:
            continue
        seen.add(match.node.id)
        preferred.append(Match(
            match.node,
            match.score,
            tuple(dict.fromkeys(("exact_changed_path", *match.reasons))),
        ))
        if len(preferred) >= 12:
            break
    return tuple(preferred)

def qualified_symbol_anchor_matches(
    graph: Graph,
    query: str,
    *,
    scopes: tuple[str, ...] = (),
) -> tuple[Match, ...]:
    """Resolve one explicit ``Type::member`` to its owner-qualified definition."""
    qualified = _qualified_query_symbols(query)
    if len(qualified) != 1:
        return ()
    owner, member = qualified[0]
    owner_terms = set(term_key(owner).split())
    candidates = search_nodes(
        graph,
        member,
        limit=24,
        scopes=scopes,
        exact_fast_path=False,
    )
    matched: list[Match] = []
    for candidate in candidates:
        node = candidate.node
        if term_key(node.label) != term_key(member):
            continue
        context_terms = set(term_key(" ".join((
            node.id,
            node.summary,
            graph.nodes[node.parent].label
            if node.parent and node.parent in graph.nodes
            else "",
        ))).split())
        if owner_terms and owner_terms <= context_terms:
            matched.append(Match(
                node,
                candidate.score + 25.0,
                tuple(dict.fromkeys((
                    "exact_fast_path",
                    "qualified_owner_exact",
                    *candidate.reasons,
                ))),
            ))
    if len(matched) != 1:
        return ()
    return (matched[0],)

def exact_token_symbol_anchor_matches(
    graph: Graph,
    query: str,
    *,
    scopes: tuple[str, ...] = (),
) -> tuple[Match, ...]:
    """Resolve unique exact symbol-table labels before inflectional ranking."""
    terms = set(plan_terms(query))
    if not terms:
        return ()
    by_label: dict[str, list[object]] = {}
    for node in graph.nodes.values():
        label = node.label.casefold()
        if (
            node.active
            and label in terms
            and node.kind not in NON_STRUCTURAL_KINDS
            and not _is_test_node(node)
            and (not scopes or _path_in_scopes(node.path, scopes))
        ):
            by_label.setdefault(label, []).append(node)
    return tuple(
        Match(
            candidates[0],
            64.0,
            (f"label_exact:{label}", "exact_query_symbol"),
        )
        for label in plan_terms(query)
        if len(candidates := by_label.get(label, ())) == 1
    )

def infer_dominant_scope(matches: tuple[Match, ...], query: str) -> str:
    """Infer scope only from high-confidence symbol anchors, never generic words."""
    exact = [match for match in matches[:8] if _is_targeted_symbol_anchor(match)]
    if not exact:
        return ""
    mass: dict[str, float] = {}
    for match in exact:
        scope = _package_scope(match.node.path)
        if scope:
            mass[scope] = mass.get(scope, 0.0) + max(0.0, match.score)
    if not mass:
        return ""
    winner, winner_mass = max(mass.items(), key=lambda item: item[1])
    total = sum(mass.values()) or 1.0
    return winner if winner_mass / total >= 0.67 else ""

def apply_shape_budget(graph: Graph, plan: ContextPlan, query: str) -> ContextPlan:
    recommendation = recommend_node_budget(plan.query_class, query, profile_graph_shape(graph))
    recommended_budget = recommendation.recommended_budget
    if recommended_budget == plan.node_budget:
        return plan
    return replace(
        plan,
        node_budget=recommended_budget,
        reason=f"{plan.reason}; shape budget: {recommendation.reason}",
        planner_version=f"{plan.planner_version}_shape_budget",
    )

def _adaptive_anchor_limit(matches: tuple[Match, ...], plan: ContextPlan, query: str) -> int:
    """Pick anchor fanout from the continuous score shape, not threshold ladders."""
    if not matches:
        return plan.anchor_limit

    top = matches[0]
    query_terms = plan_terms(query)
    term_count = len(query_terms)
    limit = plan.anchor_limit

    identifiers = explicit_query_identifiers(query)
    if len(identifiers) >= 2 and plan.query_class in STRUCTURAL_QUERY_CLASSES:
        return min(limit, max(len(identifiers), min(8, len(identifiers) * 2)))

    if top.node.kind in {"concept", "section"}:
        return min(limit, 2)

    if plan.query_class == "subsystem_summary":
        # Summary queries often contain several implementation nouns. The old
        # term_count*3 default could turn each loose lexical hit into a start,
        # mixing unrelated same-word functions before traversal even began.
        # Let the score distribution choose a small evidence set instead.
        threshold_count = sum(
            1 for match in matches[: min(12, len(matches))]
            if top.score > 0 and match.score / top.score >= 0.55
        )
        shaped = max(2, min(6, threshold_count))
        if _is_high_confidence_exact_anchor(top):
            shaped = min(shaped, 3)
        return min(limit, shaped)

    if term_count == 1:
        if plan.query_class == "direct_lookup":
            plateau_count = sum(
                1
                for match in matches[:24]
                if top.score > 0
                and match.score / top.score >= 0.45
                and match.node.kind in {"function", "method", "class", "struct", "field", "python", "rust", "go", "java", "typescript", "javascript"}
            )
            if plateau_count >= 4:
                return min(16, max(plan.anchor_limit, plateau_count))
            return plan.anchor_limit

        if top.node.kind in {"function", "method"}:
            shape = _anchor_score_shape(matches, window=min(8, max(3, limit)))
            if shape.same_stem_mass >= 0.72:
                return min(limit, max(2, round(1 + 3 * shape.same_stem_mass)))
            ambiguity = 0.20 * shape.entropy + 0.42 * shape.path_diversity + 0.10 * shape.plateau_mass
            confidence = 0.30 * shape.top_mass + 0.35 * shape.score_gap
            shaped = 1 + round((limit - 1) * max(0.0, ambiguity - confidence))
            if any(_is_file_like_anchor(match.node) for match in matches[:6]):
                shaped = max(shaped, min(limit, 5))
            if plan.query_class == "blast_radius":
                shaped = max(shaped, 2)
            return max(1, min(limit, shaped))

        if top.node.kind == "python":
            shape = _anchor_score_shape(matches, window=min(5, limit))
            return min(limit, 1 + round(1.5 * shape.entropy))

        if top.node.kind in {"class", "markdown", "java", "header", "source"}:
            return min(limit, 1)

    if term_count >= 2:
        if top.node.kind == "python":
            shape = _anchor_score_shape(matches, window=min(5, limit))
            return min(limit, 1 + round(1.5 * shape.entropy))
        if top.node.kind in {"markdown"}:
            return min(limit, 1)
        if top.node.kind in {"class", "java", "typescript", "javascript", "source", "header"}:
            if _is_high_confidence_exact_anchor(top):
                return min(limit, 1)
            shape = _anchor_score_shape(matches, window=min(8, limit))
            shaped = 1 + round(limit * (0.55 * shape.entropy + 0.45 * shape.plateau_mass))
            return max(2, min(limit, shaped))

    shape = _anchor_score_shape(matches, window=min(8, limit))
    shaped = 1 + round(limit * (0.55 * shape.entropy + 0.45 * shape.plateau_mass))
    return max(1, min(limit, shaped))

@dataclass(frozen=True)
class AnchorScoreShape:
    top_mass: float
    score_gap: float
    entropy: float
    plateau_mass: float
    path_diversity: float
    same_stem_mass: float

def _anchor_score_shape(matches: tuple[Match, ...], *, window: int) -> AnchorScoreShape:
    sample = tuple(match for match in matches[:max(1, window)] if match.score > 0)
    if not sample:
        return AnchorScoreShape(0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    scores = [match.score for match in sample]
    total = sum(scores) or 1.0
    probs = [score / total for score in scores]
    entropy = -sum(p * math.log(p) for p in probs if p > 0) / math.log(len(probs)) if len(probs) > 1 else 0.0
    top = scores[0]
    second = scores[1] if len(scores) > 1 else 0.0
    score_gap = max(0.0, min(1.0, (top - second) / max(top, 1e-9)))
    plateau_mass = sum(score for score in scores if score / max(top, 1e-9) >= 0.75) / total
    stems = [_node_stem(match.node.path) for match in sample]
    path_diversity = len(set(stems)) / max(1, len(stems))
    top_stem = stems[0]
    same_stem_mass = sum(score for score, stem in zip(scores, stems) if stem == top_stem) / total
    return AnchorScoreShape(
        top_mass=probs[0],
        score_gap=score_gap,
        entropy=max(0.0, min(1.0, entropy)),
        plateau_mass=max(0.0, min(1.0, plateau_mass)),
        path_diversity=max(0.0, min(1.0, path_diversity)),
        same_stem_mass=max(0.0, min(1.0, same_stem_mass)),
    )

def _node_stem(path: str | None) -> str:
    if not path:
        return ""
    return path.replace("\\", "/").rsplit("/", 1)[-1]

def _is_file_like_anchor(node: object) -> bool:
    return getattr(node, "kind", "") in {
        "file",
        "python",
        "typescript",
        "javascript",
        "rust",
        "go",
        "java",
        "c",
        "cpp",
        "header",
        "markdown",
        "rst",
        "html",
        "text",
    }

def _is_high_confidence_exact_anchor(match: Match) -> bool:
    return any(
        reason in {"label_exact_terms", "label_all_terms", "basename_exact_terms", "basename_all_terms"}
        for reason in match.reasons
    )

def _is_targeted_symbol_anchor(match: Match) -> bool:
    if match.node.kind not in {"function", "method", "class", "struct", "trait", "enum", "field"}:
        return False
    return _is_high_confidence_exact_anchor(match) or any(
        reason.startswith(("id:", "label_exact:")) or reason == "basename_stem_exact"
        for reason in match.reasons
    )

def select_anchor_matches(
    matches: tuple[Match, ...],
    anchor_limit: int,
    query_class: str,
    doc_intent: bool = False,
    query: str = "",
    graph: Graph | None = None,
    dominant_scope: str = "",
) -> tuple[Match, ...]:
    # Preserve explicit multi-entity intent before generic score ordering.
    # Reserve up to two exact matches per snake_case identifier (declaration
    # and implementation commonly share a label) and one per CamelCase type.
    explicit = explicit_query_identifiers(query)
    qualified = _qualified_query_symbols(query)
    resolved_qualified_owners: set[str] = set()
    if explicit or qualified:
        reserved: list[Match] = []
        seen_reserved: set[str] = set()
        for owner, member in qualified:
            owner_key = term_key(owner)
            candidate = next(
                (
                    match for match in matches
                    if match.node.id not in seen_reserved
                    and match.node.label.casefold() == member.casefold()
                    and owner_key in _facet_node_text(match.node)
                ),
                None,
            )
            if candidate is None and graph is not None:
                # Exact qualified symbols are stronger than a bounded lexical
                # candidate list. Same-named methods can otherwise be crowded
                # out by fields and the owner type before selection runs.
                node = next(
                    (
                        node for node in graph.nodes.values()
                        if node.label.casefold() == member.casefold()
                        and owner_key in _facet_node_text(node)
                    ),
                    None,
                )
                if node is not None:
                    candidate = Match(
                        node=node,
                        score=(matches[0].score if matches else 0.0) + 40.0,
                        reasons=(f"qualified_exact:{owner}::{member}",),
                    )
            if candidate is not None:
                reserved.append(candidate)
                seen_reserved.add(candidate.node.id)
                resolved_qualified_owners.add(owner.casefold())
        for identifier in explicit:
            # Once Type::member resolved exactly, the owner type is redundant.
            # Reserving it would let a two-hop traversal fan through the source
            # file's contains edges and pull unrelated sibling definitions.
            if identifier.casefold() in resolved_qualified_owners:
                continue
            per_identifier = 2 if "_" in identifier else 1
            found = 0
            for match in matches:
                if match.node.label.casefold() != identifier or match.node.id in seen_reserved:
                    continue
                reserved.append(match)
                seen_reserved.add(match.node.id)
                found += 1
                if len(reserved) >= anchor_limit or found >= per_identifier:
                    break
            if len(reserved) >= anchor_limit:
                return tuple(reserved)
        if reserved:
            matches = tuple(reserved + [match for match in matches if match.node.id not in seen_reserved])
    if query_class == "subsystem_summary" and _FLOW_ORIENTATION_QUERY.search(query):
        # Compile architecture-flow prose to executable/type roots. A prose
        # paragraph or test name can repeat the whole question verbatim, but
        # production symbols are the nodes whose typed edges prove the flow.
        production_kinds = {
            "function", "method", "class", "struct", "trait", "enum",
            "python", "rust", "javascript", "typescript", "go", "java",
            "c", "cpp", "csharp", "ruby", "php", "kotlin", "scala", "swift",
        }
        production = [
            match
            for match in matches
            if match.node.kind in production_kinds
            and match.node.kind not in NON_STRUCTURAL_KINDS
            and not _is_test_node(match.node)
        ]
        if production:
            return tuple(production[:anchor_limit])
    if doc_intent:
        doc_matches = [match for match in matches if match.node.kind in NON_STRUCTURAL_KINDS]
        if doc_matches:
            selected: list[Match] = []
            seen: set[str] = set()
            seen_content: set[str] = set()
            candidates = doc_matches if query_class == "doc_summary" else doc_matches + list(matches)
            for match in candidates:
                if match.node.id in seen:
                    continue
                content_key = _document_content_key(match.node)
                if content_key and content_key in seen_content:
                    continue
                selected.append(match)
                seen.add(match.node.id)
                if content_key:
                    seen_content.add(content_key)
                if len(selected) >= anchor_limit:
                    return tuple(selected)
            return tuple(selected)
    if query_class == "affected_tests":
        implementation = [
            match for match in matches
            if not _is_test_node(match.node)
            and match.node.kind not in NON_STRUCTURAL_KINDS
            and not _unrequested_identifier_sibling(match.node.label, explicit)
        ]
        if implementation:
            selected = [
                match
                for match in implementation
                if "exact_changed_path" in match.reasons
            ][:anchor_limit]
            seen = {match.node.id for match in selected}
            adjacency: dict[str, set[str]] = {}
            if graph is not None:
                for edge in graph.edges:
                    if not edge.active or edge.type not in STRUCTURAL_RELATIONS:
                        continue
                    adjacency.setdefault(edge.source, set()).add(edge.target)
                    adjacency.setdefault(edge.target, set()).add(edge.source)
            for identifier in explicit:
                if identifier.casefold() in resolved_qualified_owners:
                    continue
                for match in implementation:
                    if match.node.id not in seen and match.node.label.casefold() == identifier:
                        selected.append(match)
                        seen.add(match.node.id)
                        break
            for _label, terms in query_facets(query):
                if _affected_output_contract_facet(terms):
                    continue
                candidates = [
                    match for match in implementation
                    if match.node.id not in seen
                    and _facet_matches_node(match.node, terms)
                ]
                selected_ids = {match.node.id for match in selected}
                selected_term_sets = [_symbol_identity_terms(match.node) for match in selected]

                def anchor_coherence(match: Match) -> float:
                    candidate_terms = _symbol_identity_terms(match.node)
                    return max(
                        (
                            len(candidate_terms & anchor_terms)
                            / math.sqrt(max(1, len(candidate_terms) * len(anchor_terms)))
                            for anchor_terms in selected_term_sets
                        ),
                        default=0.0,
                    )

                candidate = max(
                    candidates,
                    key=lambda match: (
                        any(node_id in adjacency.get(match.node.id, ()) for node_id in selected_ids),
                        anchor_coherence(match),
                        bool(dominant_scope and _path_in_scopes(match.node.path, (dominant_scope,))),
                        match.node.kind in {"struct", "class", "trait", "enum"},
                        match.node.kind in {"function", "method"},
                        match.score,
                        match.node.id,
                    ),
                    default=None,
                )
                if candidate is not None:
                    selected.append(candidate)
                    seen.add(candidate.node.id)
                if len(selected) >= anchor_limit:
                    return tuple(selected)
            if (qualified or explicit) and selected:
                return tuple(selected)
            for match in implementation:
                if match.node.id not in seen:
                    selected.append(match)
                    seen.add(match.node.id)
                if len(selected) >= anchor_limit:
                    break
            return tuple(selected)
    if query_class not in STRUCTURAL_QUERY_CLASSES:
        return matches[:anchor_limit]
    structural = [match for match in matches if match.node.kind not in NON_STRUCTURAL_KINDS]
    if not structural:
        return matches[:anchor_limit]
    selected: list[Match] = []
    seen: set[str] = set()
    for match in structural:
        if match.node.id not in seen:
            selected.append(match)
            seen.add(match.node.id)
        if len(selected) >= anchor_limit:
            return tuple(selected)
    for match in matches:
        if match.node.id not in seen:
            selected.append(match)
            seen.add(match.node.id)
        if len(selected) >= anchor_limit:
            break
    return tuple(selected)

def select_enumerated_doc_roots(
    selected: tuple[Match, ...],
    candidates: tuple[Match, ...],
    *,
    query: str,
    query_class: str,
) -> tuple[Match, ...]:
    """Compile list-shaped document questions to one document root per path.

    Paragraphs repeat the query vocabulary and can consume every anchor slot.
    An enumeration is lower-level as ``document -> ordered section siblings``:
    root the document once, then let ``reserve_ordered_doc_siblings`` spend the
    node budget on the requested stages/phases/steps.
    """
    if (
        query_class != "doc_summary"
        or not _ORDERED_DOC_QUERY.search(query)
        or not _ENUMERATED_DOC_QUERY.search(query)
    ):
        return selected

    limit = max(1, len(selected))
    document_kinds = {"file", "markdown", "rst", "html", "text"}
    roots: list[Match] = []
    seen_paths: set[str] = set()
    for match in candidates:
        path = match.node.path.replace("\\", "/").strip("/")
        if (
            not path
            or path in seen_paths
            or match.node.kind not in document_kinds
        ):
            continue
        roots.append(match)
        seen_paths.add(path)
        if len(roots) >= limit:
            return tuple(roots)
    if roots:
        return tuple(roots)

    # Graphs produced by external frontends may have sections but no file node.
    # Keep one strongest section/paragraph root per document path.
    for match in selected:
        path = match.node.path.replace("\\", "/").strip("/")
        if not path or path in seen_paths:
            continue
        roots.append(match)
        seen_paths.add(path)
        if len(roots) >= limit:
            break
    return tuple(roots) or selected

_TOPIC_LOCAL_ROADMAP_ROW = re.compile(
    r"\bfrom\s+(?:the\s+)?(?P<topic>[A-Za-z0-9][A-Za-z0-9 &/+\-]{0,80}?)"
    r"\s+(?:roadmap\s+)?row\b",
    re.I,
)

def select_topic_local_doc_roots(
    selected: tuple[Match, ...],
    candidates: tuple[Match, ...],
    *,
    query: str,
    query_class: str,
) -> tuple[Match, ...]:
    """Compile ``From the X roadmap row`` into one topic-local prose root.

    A strict path is only a file boundary; it does not make sibling roadmap
    rows interchangeable. Keep the best paragraph matching the named topic,
    while preserving independently selected code roots for compound doc/code
    requests.
    """
    if query_class != "doc_summary":
        return selected
    match = _TOPIC_LOCAL_ROADMAP_ROW.search(query)
    if match is None:
        return selected
    topic_terms = tuple(plan_terms(match.group("topic")))
    if not topic_terms:
        return selected
    topic_docs = [
        candidate
        for candidate in candidates
        if candidate.node.kind in NON_STRUCTURAL_KINDS
        and _facet_matches_node(candidate.node, topic_terms)
    ]
    if not topic_docs:
        return selected
    winner = max(
        topic_docs,
        key=lambda candidate: (
            len(_facet_matched_terms(candidate.node, topic_terms)),
            candidate.score,
            candidate.node.id,
        ),
    )
    code_candidates = [
        candidate
        for candidate in candidates
        if candidate.node.kind not in NON_STRUCTURAL_KINDS
        and candidate.node.id != winner.node.id
    ]
    code_roots = (
        [max(
            code_candidates,
            key=lambda candidate: (
                candidate.node.kind
                in {"function", "method", "class", "struct", "trait", "enum"},
                candidate.score,
                candidate.node.id,
            ),
        )]
        if code_candidates
        else []
    )
    limit = max(2 if code_roots else 1, len(selected))
    return tuple([winner, *code_roots][:limit])

def _document_content_key(node: object) -> str:
    facts = " ".join(getattr(node, "facts", ()) or ())
    normalized = term_key(facts)
    if len(normalized) < 24:
        return ""
    return f"{getattr(node, 'kind', '')}:{normalized}"

def _unrequested_identifier_sibling(label: str, explicit: tuple[str, ...]) -> bool:
    folded = label.casefold()
    if folded in explicit or "_" not in folded:
        return False
    parts = set(part for part in folded.split("_") if len(part) >= 2)
    for identifier in explicit:
        other = set(part for part in identifier.split("_") if len(part) >= 2)
        if len(other) < 3:
            continue
        overlap = len(parts & other) / max(1, min(len(parts), len(other)))
        if overlap >= 0.75 and parts != other:
            return True
    return False
