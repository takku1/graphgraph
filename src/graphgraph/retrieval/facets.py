"""Query facet extraction, matching, and facet-evidence reservation."""

from __future__ import annotations

import re

from ..concepts.doccode import is_code_like
from ..concepts.terms import term_key
from ..graph.core import Graph
from ..planning.budgets import explicit_query_identifiers, plan_terms
from .models import Match
from .scoping import (
    STRUCTURAL_RELATIONS,
    _is_test_node,
    _qualified_query_symbols,
)


def query_facets(query: str) -> tuple[tuple[str, tuple[str, ...]], ...]:
    facets: list[tuple[str, tuple[str, ...]]] = []
    seen: set[tuple[str, ...]] = set()
    facet_query = re.sub(
        r"\b(?:the\s+)?(?:exact\s+)?changed[-\s]+(?:file[-\s]+)?paths\b",
        " ",
        query,
        flags=re.I,
    )
    command_contract = re.compile(
        r"\b(?:what\s+is\s+|and\s+)?(?:the\s+)?(?:smallest\s+)?"
        r"(?:exact\s+)?cargo\s+command\s+that\s+runs?\s+"
        r"(?:every|all)(?:\s+one)?\b",
        re.I,
    )
    if command_contract.search(query):
        terms = ("smallest", "exact", "command", "all", "direct", "tests")
        facets.append(("smallest exact command covering all direct tests", terms))
        seen.add(terms)
        facet_query = command_contract.sub(" ", facet_query)
    roadmap_paragraph = re.compile(
        r"\b(?:the\s+)?roadmap(?:'s)?\s+paragraph(?:\s+that\s+documents?\s+"
        r"(?:this|the)\s+api)?\b",
        re.I,
    )
    if roadmap_paragraph.search(query):
        qualified_doc_terms = tuple(dict.fromkeys(
            term
            for owner, member in _qualified_query_symbols(query)
            for term in term_key(f"{owner} {member}").split()
        ))
        terms = ("roadmap", "paragraph", *qualified_doc_terms)
        facets.append(("roadmap paragraph", terms))
        seen.add(terms)
        facet_query = roadmap_paragraph.sub(" ", facet_query)
    if re.search(r"\bbounded\s+input\s+contract\b", query, re.I):
        terms = ("bounded", "input", "contract")
        facets.append(("bounded input contract", terms))
        seen.add(terms)
    covered_cases = re.compile(
        r"\bwhat\s+cases?\s+(?:do|does)\s+(?:they|it|these|those)\s+cover\b",
        re.I,
    )
    if covered_cases.search(query):
        terms = ("covered", "cases")
        facets.append(("covered cases", terms))
        seen.add(terms)
        facet_query = covered_cases.sub(" ", facet_query)
    qualified = _qualified_query_symbols(query)
    qualified_owners = {owner.casefold() for owner, _member in qualified}
    raw_identifiers = {
        raw.casefold(): raw
        for raw in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", query)
    }
    for owner, member in qualified:
        terms = tuple(term_key(f"{owner} {member}").split())
        if terms and terms not in seen:
            facets.append((f"{owner}::{member}", terms))
            seen.add(terms)
    for identifier in explicit_query_identifiers(query):
        if identifier.casefold() in qualified_owners:
            continue
        display = raw_identifiers.get(identifier.casefold(), identifier)
        terms = tuple(part for part in term_key(display).split() if len(part) >= 2)
        if terms and terms not in seen:
            facets.append((display, terms))
            seen.add(terms)
    identifiers = explicit_query_identifiers(query)
    identifier_terms = {
        part
        for identifier in identifiers
        for part in term_key(identifier.replace("-", "_")).split()
        if len(part) >= 2
    }
    intent_terms = {
        "and", "which", "tests", "test", "cover", "covers", "covered", "coverage",
        "run", "how", "does", "do", "measure", "measures", "measured", "report",
        "reports", "show", "shows", "including", "include", "through", "chain",
        "every", "each", "all", "part", "parts", "entire", "whole", "requested", "above",
        "positive", "negative",
        "documentation", "documents", "document", "docs", "doc",
        "say", "says", "said", "under",
        "roadmap", "row", "now", "claim", "claims", "claimed",
        "blast", "radius",
        "api", "explain", "new",
        "capability", "capabilities", "remain", "remains",
        "affected", "affecting", "impact", "impacted",
        "call", "calls", "called", "caller", "callers", "calling",
        "consume", "consumes", "consumed", "consumer", "use", "uses", "used",
        "should", "if", "change", "changes", "changed", "changing", "behavior", "behaviour",
        "evaluate", "evaluates", "evaluated", "evaluating",
        "assess", "assesses", "assessed", "assessing",
        "gate", "gates", "gated", "gating",
        "direct", "directly", "transitive",
        "validate", "validates", "validated", "validating", "validation",
        "identify", "identifies", "identified", "identifying",
        "exact", "command", "commands",
        "add", "adds", "added", "adding", "after", "before",
        "behavioral", "focus", "focused", "minimal", "runnable", "return", "returns",
        "own", "step", "steps", "according", "md",
        "then",
        "it", "its", "they", "them", "their", "these", "those",
        "have", "has", "had",
        "cargo",
        "where", "what", "why", "who", "when", "is", "are", "was", "were",
        "the", "a", "an", "from", "into", "flow", "flows",
        "nonexistent", "missing", "implemented", "implements",
    }
    for clause in re.split(
        r"\s*(?:,|;|\band\b|\bplus\b|\bwhich\b)\s*",
        facet_query,
        flags=re.I,
    ):
        for identifier in identifiers:
            clause = re.sub(rf"\b{re.escape(identifier)}\b", " ", clause, flags=re.I)
        for owner, member in qualified:
            clause = re.sub(
                rf"\b{re.escape(owner)}\s*::\s*{re.escape(member)}\b",
                " ",
                clause,
                flags=re.I,
            )
        terms = tuple(
            term for term in plan_terms(clause)
            if term not in intent_terms and term not in identifier_terms
        )
        meaningful_single = len(terms) == 1 and len(terms[0]) >= 4
        if (meaningful_single or 2 <= len(terms) <= 6) and terms not in seen:
            facets.append((" ".join(terms), terms))
            seen.add(terms)
    return tuple(facets[:12])

def facet_search_queries(label: str, terms: tuple[str, ...]) -> tuple[str, ...]:
    """Bounded relaxed searches let prose facets reach compound code symbols."""
    queries = [label]
    if len(terms) >= 3:
        queries.extend(
            " ".join(terms[index : index + 2])
            for index in range(len(terms) - 1)
        )
    return tuple(dict.fromkeys(query for query in queries if query.strip()))

def _facet_node_text(node: object) -> str:
    return term_key(" ".join((
        str(getattr(node, "label", "")),
        str(getattr(node, "kind", "")),
        str(getattr(node, "path", "")),
        str(getattr(node, "summary", "")),
        " ".join(getattr(node, "facts", ()) or ()),
    )))

def _symbol_identity_terms(node: object) -> set[str]:
    """Owner-aware terms for same-file candidate coherence."""
    return set(term_key(" ".join((
        str(getattr(node, "id", "")),
        str(getattr(node, "label", "")),
        str(getattr(node, "summary", "")),
    ))).split())

def facet_coverage(
    graph: Graph,
    nodes: set[str],
    facets: tuple[tuple[str, tuple[str, ...]], ...],
    *,
    roots: tuple[str, ...] = (),
) -> dict[str, object]:
    fulfilled: list[dict[str, object]] = []
    unfulfilled: list[str] = []
    for label, terms in facets:
        structural_first = _affected_output_contract_facet(terms)
        evidence = (
            _facet_structural_evidence(
                graph,
                nodes,
                terms,
                roots=roots,
            )
            if structural_first
            else [
                node_id for node_id in sorted(nodes)
                if _facet_matches_node(graph.nodes[node_id], terms)
            ]
        )
        if not evidence and not structural_first:
            evidence = _facet_structural_evidence(
                graph,
                nodes,
                terms,
                roots=roots,
            )
        if not evidence and len(_facet_evidence_terms(terms)) >= 3:
            needed = set(_facet_evidence_terms(terms))
            distributed = sorted(
                (
                    (-len(hits), node_id, hits)
                    for node_id in nodes
                    if len(hits := _facet_matched_terms(graph.nodes[node_id], tuple(needed))) >= 2
                ),
            )
            covered: set[str] = set()
            selected: list[str] = []
            for _negative_hits, node_id, hits in distributed:
                if not (hits - covered):
                    continue
                selected.append(node_id)
                covered.update(hits)
                if covered >= needed or len(selected) >= 3:
                    break
            if covered >= needed:
                evidence = selected
        if evidence:
            fulfilled.append({"facet": label, "evidence": evidence[:5]})
        else:
            unfulfilled.append(label)
    return {
        "fulfilled": fulfilled,
        "unfulfilled": unfulfilled,
        "coverage_ratio": round(len(fulfilled) / max(1, len(facets)), 4),
        "warning": "unfulfilled query facets" if unfulfilled else "",
    }

def _facet_structural_evidence(
    graph: Graph,
    nodes: set[str],
    terms: tuple[str, ...],
    *,
    roots: tuple[str, ...],
) -> list[str]:
    """Credit relationship facets from selected topology, not only node text."""
    if not roots:
        return []
    targets = set(roots)
    targets.update(
        node_id
        for node_id in nodes
        if graph.nodes[node_id].parent in targets
    )
    targets.update(
        edge.target
        for edge in graph.edges
        if edge.active
        and edge.type == "contains"
        and edge.source in targets
        and edge.target in nodes
    )
    relation_edges = [
        edge
        for edge in graph.edges
        if edge.active
        and edge.source in nodes
        and edge.target in targets
        and edge.type in {"calls", "references", "tests", "registers"}
    ]
    forms = {
        form
        for term in terms
        for form in _facet_term_forms(term)
    }
    if forms & {"result", "results", "return", "returns", "outcome"}:
        return sorted({
            edge.target
            for edge in graph.edges
            if edge.active
            and edge.type == "returns"
            and edge.source in nodes
            and edge.target in nodes
        })
    if forms & {"exercise", "exercises", "exercised"}:
        return sorted({
            edge.source
            for edge in relation_edges
            if _is_test_node(graph.nodes[edge.source])
        })
    if (
        forms & {"case", "cases"}
        and forms & {"cover", "covers", "covered", "coverage"}
    ):
        return sorted({
            edge.source
            for edge in relation_edges
            if _is_test_node(graph.nodes[edge.source])
        })
    if forms & {"register", "registers", "registered", "registration", "registry"}:
        return sorted({
            edge.source
            for edge in relation_edges
            if edge.type == "registers"
            or set(_facet_node_text(graph.nodes[edge.source]).split())
            & {"default", "domain", "register", "registered", "registry"}
        })
    return []

def reserve_facet_matches(
    selected: tuple[Match, ...],
    candidates: tuple[Match, ...],
    facets: tuple[tuple[str, tuple[str, ...]], ...],
    *,
    graph: Graph | None = None,
    prefer_code: bool = False,
    limit: int = 12,
) -> tuple[Match, ...]:
    """Reserve one independently retrieved anchor for every requested facet."""
    reserved = list(selected)
    seen = {match.node.id for match in reserved}
    for _label, terms in facets:
        matching_reserved = [
            match for match in reserved if _facet_matches_node(match.node, terms)
        ]
        if matching_reserved and (
            not prefer_code
            or graph is None
            or any(is_code_like(match.node) for match in matching_reserved)
        ):
            continue
        eligible = [
            match
            for match in candidates
            if match.node.id not in seen and _facet_matches_node(match.node, terms)
        ]
        if (
            not eligible
            and graph is not None
            and set(terms) & {"result", "results", "return", "returns", "outcome"}
        ):
            returned_ids = {
                edge.target
                for edge in graph.edges
                if edge.active and edge.type == "returns" and edge.source in seen
            }
            eligible = [
                match
                for match in candidates
                if match.node.id in returned_ids and match.node.id not in seen
            ]
        code_eligible = [match for match in eligible if is_code_like(match.node)]
        needs_distributed_code = prefer_code and not code_eligible
        if (not eligible or needs_distributed_code) and len(_facet_evidence_terms(terms)) >= 3:
            needed = set(_facet_evidence_terms(terms))
            covered: set[str] = set()
            distributed = sorted(
                (
                    (
                        0 if not prefer_code or is_code_like(match.node) else 1,
                        -len(hits),
                        -match.score,
                        match.node.id,
                        match,
                        hits,
                    )
                    for match in candidates
                    if match.node.id not in seen
                    if len(hits := _facet_matched_terms(match.node, tuple(needed))) >= 2
                ),
                key=lambda item: item[:4],
            )
            for _kind_rank, _hit_rank, _score_rank, _node_id, match, hits in distributed:
                if not (hits - covered):
                    continue
                reserved.append(match)
                seen.add(match.node.id)
                covered.update(hits)
                if covered >= needed or len(reserved) >= limit:
                    break
            if covered >= needed:
                continue
        pool = code_eligible if prefer_code and code_eligible else eligible
        connected_ids: set[str] = set()
        adjacency: dict[str, set[str]] = {}
        if graph is not None and seen:
            for edge in graph.edges:
                if not edge.active or edge.type not in STRUCTURAL_RELATIONS:
                    continue
                adjacency.setdefault(edge.source, set()).add(edge.target)
                adjacency.setdefault(edge.target, set()).add(edge.source)
                if edge.source in seen:
                    connected_ids.add(edge.target)
                if edge.target in seen:
                    connected_ids.add(edge.source)

        def connection_rank(match: Match) -> int:
            node_id = match.node.id
            if node_id in connected_ids:
                return 2
            return int(any(
                neighbor in connected_ids
                for neighbor in adjacency.get(node_id, ())
            ))

        candidate = max(
            pool,
            key=lambda match: (
                connection_rank(match),
                match.score,
                match.node.id,
            ),
            default=None,
        )
        if candidate is not None:
            reserved.append(candidate)
            seen.add(candidate.node.id)
        if len(reserved) >= limit:
            break
    return tuple(reserved[:limit])

_FACET_PROCESS_TERMS = {
    "discovery", "equivalence", "rationalization", "implementation", "implementations",
    "measurement", "measurements",
    "anchoring", "calibrated", "calibration", "consistency", "query", "readiness",
    "reconciliation", "selection", "specific",
}

def _facet_evidence_terms(terms: tuple[str, ...]) -> tuple[str, ...]:
    """Keep a facet's domain terms while treating process nouns as intent."""
    reduced = tuple(term for term in terms if term not in _FACET_PROCESS_TERMS)
    return reduced or terms

def _facet_term_forms(term: str) -> set[str]:
    forms = {term_key(term)}
    aliases = {
        "sync": {"synchronization", "synchronize", "synchronized", "syncing"},
        "synchronization": {"sync", "synchronize", "synchronized", "syncing"},
        "synchronize": {"sync", "synchronization", "synchronized", "syncing"},
        "synchronized": {"sync", "synchronization", "synchronize", "syncing"},
        "anchoring": {"anchor", "anchored"},
        "consistency": {"consistent"},
        "deduplication": {
            "dedup", "deduplicate", "deduplicated", "duplicate", "duplicates",
            "unique", "once",
        },
        "equality": {"equal", "equals", "exact", "exactly"},
        "readiness": {"ready"},
        "reconciliation": {"reconcile", "reconciled"},
        "unproved": {"unproven", "prove", "proved", "proof"},
        "export": {"exports", "exported", "public", "pub"},
        "result": {"result", "results", "return", "returns", "outcome"},
        "verification": {"verify", "verified", "verifies", "verification"},
        "unsupported": {
            "absent", "missing", "unsupported", "unimplemented",
        },
    }
    forms.update(aliases.get(term, ()))
    if term.endswith("ies") and len(term) > 4:
        forms.add(term[:-3] + "y")
    elif term.endswith("ing") and len(term) > 5:
        stem = term[:-3]
        forms.add(stem)
        if len(stem) >= 2 and stem[-1] == stem[-2]:
            forms.add(stem[:-1])
        forms.add(stem + "e")
    elif term.endswith("ed") and len(term) > 4:
        stem = term[:-2]
        forms.update((stem, stem + "e"))
    elif term.endswith("s") and not term.endswith("ss") and len(term) > 3:
        forms.add(term[:-1])
    else:
        forms.add(term + "s")
    return {form for form in forms if form}

def _facet_evidence_queries(terms: tuple[str, ...]) -> tuple[tuple[str, ...], ...]:
    base = _facet_evidence_terms(terms)
    queries = [base]
    term_set = set(base)
    if "verified" in term_set and term_set & {"source", "application", "applications"}:
        queries.extend((
            ("preview", "fixes"),
            ("is", "fixable"),
            ("successful", "verified", "application"),
            ("verified", "application"),
        ))
    if "rejection" in term_set and term_set & {"diagnostic", "diagnostics"}:
        queries.extend((("refactor", "rejection"), ("rejection",), ("diagnostic",)))
    if "yield" in term_set:
        queries.extend((("promotable", "candidate"), ("promotable", "candidates")))
    if term_set & {"metric", "metrics"} and term_set & {"enforce", "enforces", "enforced"}:
        queries.extend((("min",), ("max",), ("threshold",), ("evaluate",)))
    if "unsafe" in term_set and "path" in term_set:
        queries.extend((("unsafe", "path"), ("parent", "traversal"), ("rejects", "parent", "traversal")))
    if term_set & {"running", "run"} and term_set & {"loaded", "load", "cases", "case"}:
        queries.extend((("load", "run"), ("loaded", "case"), ("loads", "cases")))
    if term_set & {"abstain", "abstention"} and term_set & {"case", "cases"}:
        queries.extend((
            ("no", "solution"),
            ("returns", "none"),
            ("dominant", "degenerate"),
        ))
    if "unsupported" in term_set:
        queries.extend((("remain", "absent"), ("absent",), ("missing",)))
    if "self" in term_set and term_set & {"verification", "verified", "verify"}:
        queries.extend((("verify",), ("verified",), ("verifies",)))
    return tuple(dict.fromkeys(queries))

def _facet_matches_node(node: object, terms: tuple[str, ...]) -> bool:
    if _bounded_input_contract_match(_facet_node_text(node), terms):
        return True
    token_list = re.findall(r"[a-z0-9]+", _facet_node_text(node))
    tokens = set(token_list)
    compact = "".join(token_list)
    return any(
        all(
            tokens & (forms := _facet_term_forms(term))
            or any(len(form) >= 5 and form in compact for form in forms)
            for term in query_terms
        )
        for query_terms in _facet_evidence_queries(terms)
    )

def _facet_matched_terms(node: object, terms: tuple[str, ...]) -> set[str]:
    return _facet_matched_text_terms(_facet_node_text(node), terms)

def _facet_label_matched_terms(node: object, terms: tuple[str, ...]) -> set[str]:
    """Return facet hits from symbol identity, excluding summary/body context."""
    return _facet_matched_text_terms(
        term_key(str(getattr(node, "label", ""))),
        terms,
    )

def _facet_matched_text_terms(text: str, terms: tuple[str, ...]) -> set[str]:
    if _bounded_input_contract_match(text, terms):
        return set(terms)
    token_list = re.findall(r"[a-z0-9]+", text)
    tokens = set(token_list)
    compact = "".join(token_list)
    return {
        term
        for term in terms
        if (
            tokens & (forms := _facet_term_forms(term))
            or any(len(form) >= 5 and form in compact for form in forms)
        )
    }

def _bounded_input_contract_match(text: str, terms: tuple[str, ...]) -> bool:
    """Recognize an explicit numeric input bound as contract evidence."""
    normalized_terms = {term_key(term) for term in terms}
    if not {"bounded", "input", "contract"} <= normalized_terms:
        return False
    normalized = term_key(text)
    has_bound = bool(re.search(
        r"\b(?:up to|at most|no more than|maximum(?: of)?)\s+\d+\b"
        r"|\b\d+\s*[x×✕]\s*\d+\b",
        normalized,
    ))
    has_input_shape = bool(re.search(
        r"\b(?:input|inputs|domain|domains|point|points|item|items|"
        r"element|elements|length|size|arity|game|games|player|players|"
        r"matrix|matrices)\b",
        normalized,
    ))
    return has_bound and has_input_shape

_AFFECTED_OUTPUT_TERMS = {
    "affected", "all", "behavioral", "cargo", "case", "cases", "command", "commands",
    "cover", "covered", "covering", "coverage", "covers", "direct", "exact", "exercise",
    "exercised", "exercises", "focused", "minimal", "return", "runnable", "run",
    "running", "runs", "smallest", "test", "tests", "transitive",
}

def _affected_output_contract_facet(terms: tuple[str, ...]) -> bool:
    normalized = set(term_key(" ".join(terms)).split())
    return bool(normalized) and normalized <= _AFFECTED_OUTPUT_TERMS

def reconcile_affected_output_facets(metadata: dict[str, object]) -> tuple[str, ...]:
    """Fulfill output-contract facets from the affected-test receipt itself."""
    coverage = metadata.get("facet_coverage")
    affected = metadata.get("affected_tests")
    if not isinstance(coverage, dict) or not isinstance(affected, dict):
        return ()
    direct = [item for item in affected.get("direct", ()) if isinstance(item, dict)]
    transitive = [item for item in affected.get("transitive", ()) if isinstance(item, dict)]
    commands = [str(item) for item in affected.get("commands", ()) if item]
    command_selection = affected.get("command_selection", {})
    fulfilled = list(coverage.get("fulfilled", ()))
    remaining: list[str] = []
    repaired: list[str] = []
    for raw_label in coverage.get("unfulfilled", ()):
        label = str(raw_label)
        terms = set(term_key(label).split())
        if not terms or terms - _AFFECTED_OUTPUT_TERMS:
            remaining.append(label)
            continue
        evidence: list[str] = []
        requires_all_direct = bool(
            {"all", "direct", "test"} <= terms
            or {"all", "direct", "tests"} <= terms
        )
        selected_command_complete = bool(commands) and (
            not requires_all_direct
            or not isinstance(command_selection, dict)
            or (
                not command_selection.get("uncovered_roots", ())
                and not command_selection.get("uncovered_direct_tests", ())
            )
        )
        if (
            terms & {"cargo", "command", "commands", "runnable", "run", "runs"}
            and selected_command_complete
        ):
            evidence = [f"affected_tests.command:{command}" for command in commands[:5]]
        elif "direct" in terms and direct:
            evidence = [f"affected_tests.direct:{item.get('id', '')}" for item in direct[:5]]
        elif "transitive" in terms and transitive:
            evidence = [f"affected_tests.transitive:{item.get('id', '')}" for item in transitive[:5]]
        elif terms & {"affected", "behavioral", "test", "tests"} and (direct or transitive):
            evidence = [
                f"affected_tests.test:{item.get('id', '')}"
                for item in (*direct, *transitive)[:5]
            ]
        if evidence:
            fulfilled.append({
                "facet": label,
                "evidence": evidence,
                "source": "affected_tests_receipt",
            })
            repaired.append(label)
        else:
            remaining.append(label)
    total = len(fulfilled) + len(remaining)
    coverage.update({
        "fulfilled": fulfilled,
        "unfulfilled": remaining,
        "coverage_ratio": round(len(fulfilled) / max(1, total), 4),
        "warning": "unfulfilled query facets" if remaining else "",
    })
    return tuple(repaired)
