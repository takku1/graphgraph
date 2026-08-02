"""Typed, auditable evidence obligations for exact structural queries."""

from __future__ import annotations

import re
from heapq import heappop, heappush

from ..graph.core import Edge
from ..graph.ontology import provenance_confidence

_CALL_TERMS = frozenset({"call", "calls", "called", "caller", "calling"})
_REFERENCE_TERMS = frozenset({"reference", "references", "referenced"})
_IMPLEMENTATION_TERMS = frozenset({"implement", "implements", "implemented", "implementor", "implementors"})
_TEST_TERMS = frozenset({"test", "tests", "tested", "verifies"})
_DEPENDENCY_TERMS = frozenset({"depend", "depends", "dependent", "dependents", "used", "users"})
_REVERSE_RELATION_FAMILIES = (
    ("calls", _CALL_TERMS, frozenset({"calls"})),
    ("implements", _IMPLEMENTATION_TERMS, frozenset({"implements"})),
    ("references", _REFERENCE_TERMS, frozenset({"references"})),
    ("tests", _TEST_TERMS, frozenset({"tests", "calls", "references"})),
    (
        "dependencies",
        _DEPENDENCY_TERMS,
        frozenset({"calls", "imports", "imports_from", "references", "uses"}),
    ),
)
_PATH_RELATIONS = frozenset(
    {
        "calls",
        "observed_calls",
        "imports",
        "imports_from",
        "reads",
        "writes",
        "implements",
        "uses",
        "references",
        "contains",
    }
)

_PATH_RELATION_COST = {
    "observed_calls": 0.8,
    "calls": 1.0,
    "implements": 1.4,
    "imports": 1.6,
    "imports_from": 1.6,
    "reads": 1.8,
    "writes": 1.8,
    "uses": 2.0,
    "references": 2.2,
    "contains": 2.5,
}


def minimal_evidence_connector(
    nodes: set[str],
    edges: list[Edge],
    evidence_groups: tuple[tuple[str, ...], ...],
) -> tuple[set[str], list[Edge], dict[str, object]] | None:
    """Return a deterministic minimum directed connector for facet evidence.

    Expanded packets intentionally favor recall.  A path query needs the
    opposite final objective: retain a compact proof connecting one witness
    for every requested entity.  The groups are tiny (facet evidence is capped
    at five), so evaluating every possible root is bounded and auditable.

    A result is returned only when one root reaches every non-empty evidence
    group through trusted structural relations.  Otherwise retrieval keeps the
    original recall-oriented packet and its existing abstention behavior.
    """
    groups = tuple(
        tuple(dict.fromkeys(node_id for node_id in group if node_id in nodes))
        for group in evidence_groups
        if any(node_id in nodes for node_id in group)
    )
    if len(groups) < 2:
        return None

    usable_edges = [
        edge
        for edge in edges
        if edge.active and edge.source in nodes and edge.target in nodes and edge.type in _PATH_RELATIONS
    ]
    outgoing: dict[str, list[Edge]] = {}
    for edge in usable_edges:
        outgoing.setdefault(edge.source, []).append(edge)
    for bucket in outgoing.values():
        bucket.sort(key=lambda edge: (edge.target, edge.type, -edge.confidence, edge.provenance))

    roots = tuple(dict.fromkeys(node_id for group in groups for node_id in group))
    best: tuple[tuple[float, int, tuple[str, ...]], set[str], list[Edge], str] | None = None
    for root in roots:
        distances, previous = _minimum_path_tree(root, outgoing)
        chosen_targets: list[str] = []
        chosen_edges: dict[tuple[str, str, str], Edge] = {}
        total_cost = 0.0
        reachable = True
        for group in groups:
            candidates = [node_id for node_id in group if node_id in distances]
            if not candidates:
                reachable = False
                break
            target = min(candidates, key=lambda node_id: (distances[node_id], node_id))
            chosen_targets.append(target)
            total_cost += distances[target]
            cursor = target
            while cursor != root:
                edge = previous.get(cursor)
                if edge is None:
                    reachable = False
                    break
                chosen_edges[(edge.source, edge.target, edge.type)] = edge
                cursor = edge.source
            if not reachable:
                break
        if not reachable or not chosen_edges:
            continue
        connector_nodes = {root, *chosen_targets}
        for edge in chosen_edges.values():
            connector_nodes.update((edge.source, edge.target))
        score = (round(total_cost, 8), len(connector_nodes), tuple(sorted(connector_nodes)))
        candidate = (score, connector_nodes, list(chosen_edges.values()), root)
        if best is None or candidate[0] < best[0]:
            best = candidate

    if best is None:
        return None
    _score, connector_nodes, connector_edges, root = best
    connector_edges.sort(key=lambda edge: (edge.source, edge.target, edge.type))
    return connector_nodes, connector_edges, {
        "policy": "minimum_directed_facet_connector_v1",
        "root": root,
        "facet_groups": len(groups),
        "nodes": len(connector_nodes),
        "edges": len(connector_edges),
    }


def _minimum_path_tree(
    root: str,
    outgoing: dict[str, list[Edge]],
) -> tuple[dict[str, float], dict[str, Edge]]:
    distances = {root: 0.0}
    previous: dict[str, Edge] = {}
    frontier: list[tuple[float, str]] = [(0.0, root)]
    while frontier:
        cost, node_id = heappop(frontier)
        if cost > distances.get(node_id, float("inf")):
            continue
        for edge in outgoing.get(node_id, ()):
            reliability = max(0.05, edge.confidence * provenance_confidence(edge.provenance))
            step = _PATH_RELATION_COST[edge.type] / reliability
            candidate = cost + step
            current = distances.get(edge.target, float("inf"))
            tie_key = (edge.source, edge.type, edge.target)
            prior = previous.get(edge.target)
            prior_key = (prior.source, prior.type, prior.target) if prior is not None else ("~", "~", "~")
            if candidate < current or (abs(candidate - current) < 1e-12 and tie_key < prior_key):
                distances[edge.target] = candidate
                previous[edge.target] = edge
                heappush(frontier, (candidate, edge.target))
    return distances, previous


def relationship_obligation_coverage(
    query_class: str,
    starts: tuple[str, ...],
    edges: list[Edge],
    query_terms: tuple[str, ...],
    query: str = "",
) -> dict[str, object] | None:
    """Measure whether a relationship question contains relationship proof.

    Lexical hits and containment are useful orientation, but they cannot prove
    callers, callees, references, or paths.  This compiles the query class and
    intent vocabulary into a small typed obligation, then counts only edges
    with the required direction and relation family.
    """
    terms = set(query_terms)
    start_set = set(starts)
    direction = ""
    family = ""
    relations: frozenset[str] = frozenset()

    if query_class == "reverse_lookup":
        direction = "incoming"
        explicit_implementation_lookup = bool(
            re.search(
                r"\b(?:what|which|who)\b.{0,48}\bimplements?\b|\bimplemented\s+by\b|\bimplementors?\b",
                query,
                flags=re.I,
            )
        )
        family, relations = next(
            (
                (name, candidates)
                for name, vocabulary, candidates in _REVERSE_RELATION_FAMILIES
                if terms & vocabulary and (name != "implements" or explicit_implementation_lookup)
            ),
            ("relationships", frozenset().union(*(item[2] for item in _REVERSE_RELATION_FAMILIES))),
        )
        evidence = [
            edge
            for edge in edges
            if edge.active and edge.target in start_set and edge.source != edge.target and edge.type in relations
        ]
    elif query_class == "direct_lookup" and terms & _CALL_TERMS:
        direction = "outgoing"
        family = "calls"
        relations = frozenset({"calls"})
        evidence = [
            edge
            for edge in edges
            if edge.active and edge.source in start_set and edge.source != edge.target and edge.type in relations
        ]
    elif query_class == "multi_hop_path":
        direction = "path"
        family = "calls" if terms & _CALL_TERMS else "structural_path"
        relations = frozenset({"calls"}) if family == "calls" else _PATH_RELATIONS
        evidence = [edge for edge in edges if edge.active and edge.type in relations]
    else:
        return None

    return {
        "kind": "relationship",
        "family": family,
        "direction": direction,
        "relations": sorted(relations),
        "required": 1,
        "proven": int(bool(evidence)),
        "ratio": 1.0 if evidence else 0.0,
        "evidence_edges": len(evidence),
        "status": "proven" if evidence else "unresolved",
    }


def exact_path_obligation_closure(
    starts: tuple[str, ...],
    nodes: set[str],
    edges: list[Edge],
    query_terms: tuple[str, ...],
) -> tuple[dict[str, object], float]:
    """Prove exact endpoint and directed-path obligations in a selected packet.

    Path reliability is the widest-path value: maximize the minimum effective
    edge confidence along the proof.  Unlike multiplying confidences, this does
    not mechanically punish a longer, fully structural call chain; unlike a
    plain reachability bit, it still preserves the weakest evidence source in
    the final calibrated confidence.
    """
    relation = "calls" if set(query_terms) & _CALL_TERMS else ""
    obligations: list[dict[str, object]] = [
        {
            "kind": "entity",
            "target": node_id,
            "status": "proven" if node_id in nodes else "unresolved",
        }
        for node_id in starts
    ]
    path_reliabilities: list[float] = []
    for target in starts[1:]:
        reliability = _widest_path_reliability(
            starts[0],
            target,
            nodes,
            edges,
            relation=relation,
        )
        path_reliabilities.append(reliability)
        obligation: dict[str, object] = {
            "kind": "path",
            "source": starts[0],
            "target": target,
            "status": "proven" if reliability > 0.0 else "unresolved",
        }
        if relation:
            obligation["relation"] = relation
        # Keep the serialized contract in a stable field order.
        obligations.append(
            {key: obligation[key] for key in ("kind", "relation", "source", "target", "status") if key in obligation}
        )

    proven = sum(obligation["status"] == "proven" for obligation in obligations)
    required = len(obligations)
    ratio = proven / max(1, required)
    ledger = {
        "required": required,
        "proven": proven,
        "ratio": round(ratio, 4),
        "obligations": obligations,
    }
    if ratio == 1.0:
        weakest_path = min(path_reliabilities, default=1.0)
        confidence = 0.9 + 0.1 * weakest_path
    else:
        confidence = min(0.89, ratio * 0.89)
    return ledger, round(confidence, 4)


def _widest_path_reliability(
    source: str,
    target: str,
    nodes: set[str],
    edges: list[Edge],
    *,
    relation: str,
) -> float:
    """Return the maximum bottleneck confidence of a directed selected path."""
    if source not in nodes or target not in nodes:
        return 0.0
    outgoing: dict[str, list[tuple[str, float]]] = {}
    for edge in edges:
        if edge.active and edge.source in nodes and edge.target in nodes and (not relation or edge.type == relation):
            effective = edge.confidence * provenance_confidence(edge.provenance)
            outgoing.setdefault(edge.source, []).append((edge.target, effective))

    best = {source: 1.0}
    frontier = [(-1.0, source)]
    while frontier:
        negative_reliability, node_id = heappop(frontier)
        reliability = -negative_reliability
        if reliability < best.get(node_id, 0.0):
            continue
        if node_id == target:
            return reliability
        for neighbor, edge_reliability in outgoing.get(node_id, ()):
            candidate = min(reliability, edge_reliability)
            if candidate > best.get(neighbor, 0.0):
                best[neighbor] = candidate
                heappush(frontier, (-candidate, neighbor))
    return 0.0
