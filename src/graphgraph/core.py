from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json

from typing import Callable

from .ontology import provenance_confidence, traversal_strength


@dataclass(frozen=True)
class Node:
    id: str
    label: str
    kind: str = "unknown"
    path: str = ""
    summary: str = ""
    facts: tuple[str, ...] = ()
    scope: str = ""
    parent: str = ""
    source: str = ""
    confidence: float = 1.0
    active: bool = True
    created_at: str = ""
    updated_at: str = ""


@dataclass(frozen=True)
class Edge:
    source: str
    target: str
    type: str
    weight: float = 1.0
    confidence: float = 1.0
    provenance: str = "extracted"
    evidence: str = ""
    source_location: str = ""
    valid_from: str = ""
    valid_to: str = ""
    active: bool = True


@dataclass(frozen=True)
class Policy:
    id: str
    kind: str
    priority: str
    applies_to: tuple[str, ...]
    task_tags: tuple[str, ...]
    compact: str
    content: str = ""


@dataclass(frozen=True)
class Query:
    text: str
    query_class: str
    paths: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()


@dataclass
class Graph:
    nodes: dict[str, Node] = field(default_factory=dict)
    edges: list[Edge] = field(default_factory=list)
    metadata: dict[str, str] = field(default_factory=dict)
    _pagerank_cache: tuple[tuple[object, ...], dict[str, float]] | None = field(default=None, init=False, repr=False)
    _search_index_cache: tuple[tuple[object, ...], object] | None = field(default=None, init=False, repr=False)

    def _edges_by_key(self, key_fn: Callable[[Edge], str]) -> dict[str, list[Edge]]:
        grouped: dict[str, list[Edge]] = {}
        for edge in self.edges:
            if edge.active:
                grouped.setdefault(key_fn(edge), []).append(edge)
        return grouped

    def outgoing(self) -> dict[str, list[Edge]]:
        return self._edges_by_key(lambda e: e.source)

    def incoming(self) -> dict[str, list[Edge]]:
        return self._edges_by_key(lambda e: e.target)

    def degree(self) -> dict[str, int]:
        deg: dict[str, int] = {}
        for edge in self.edges:
            if not edge.active:
                continue
            deg[edge.source] = deg.get(edge.source, 0) + 1
            deg[edge.target] = deg.get(edge.target, 0) + 1
        return deg

    def pagerank(
        self,
        damping: float = 0.85,
        max_iter: int = 20,
        tol: float = 1e-4,
        use_cache: bool = True,
    ) -> dict[str, float]:
        cache_key = self._pagerank_cache_key(damping, max_iter, tol) if use_cache else None
        if cache_key is not None and self._pagerank_cache and self._pagerank_cache[0] == cache_key:
            return dict(self._pagerank_cache[1])

        active_nodes = [nid for nid, node in self.nodes.items() if node.active]
        N = len(active_nodes)
        if N == 0:
            return {}

        # Initialize PageRank equally
        pr = {nid: 1.0 / N for nid in active_nodes}
        
        # Pre-calculate active adjacency once. Search uses PageRank as a light
        # centrality prior, so this path needs to stay cheap on large graphs.
        outgoing = self.outgoing()
        incoming = self.incoming()
        sum_out = {}
        for nid in active_nodes:
            s = 0.0
            for edge in outgoing.get(nid, []):
                if edge.target in pr:
                    s += edge.weight * traversal_strength(edge.type)
            sum_out[nid] = s

        dangling_nodes = [nid for nid in active_nodes if sum_out[nid] == 0.0]

        # Power iteration
        for _ in range(max_iter):
            next_pr = {nid: (1.0 - damping) / N for nid in active_nodes}
            
            # Distribute dangling PageRank evenly among all active nodes
            dangling_sum = sum(pr[nid] for nid in dangling_nodes)
            dangling_share = (damping * dangling_sum) / N
            for nid in active_nodes:
                next_pr[nid] += dangling_share

            # Distribute PR along active edges
            for target_id in active_nodes:
                incoming_edges = incoming.get(target_id, [])
                for edge in incoming_edges:
                    source_id = edge.source
                    if source_id in pr and sum_out[source_id] > 0.0:
                        weight = edge.weight * traversal_strength(edge.type)
                        next_pr[target_id] += damping * pr[source_id] * (weight / sum_out[source_id])

            # Check convergence
            err = sum(abs(next_pr[nid] - pr[nid]) for nid in active_nodes)
            pr = next_pr
            if err < tol:
                break

        if cache_key is not None:
            self._pagerank_cache = (cache_key, dict(pr))
        return pr

    def personalized_pagerank(
        self,
        personalization: dict[str, float],
        damping: float = 0.85,
        max_iter: int = 20,
        tol: float = 1e-4,
    ) -> dict[str, float]:
        """Compute Personalized PageRank (PPR) starting from query-specific seed nodes.

        Allows query-contextual centrality ranking to boost topologically close nodes.
        """
        active_nodes = [nid for nid, node in self.nodes.items() if node.active]
        N = len(active_nodes)
        if N == 0:
            return {}

        # Normalize personalization vector
        p = {nid: 0.0 for nid in active_nodes}
        total_p = sum(personalization.get(nid, 0.0) for nid in active_nodes)
        if total_p > 0:
            for nid in active_nodes:
                p[nid] = personalization.get(nid, 0.0) / total_p
        else:
            for nid in active_nodes:
                p[nid] = 1.0 / N

        pr = dict(p)

        outgoing = self.outgoing()
        incoming = self.incoming()
        sum_out = {}
        for nid in active_nodes:
            s = 0.0
            for edge in outgoing.get(nid, []):
                if edge.target in pr:
                    s += edge.weight * traversal_strength(edge.type)
            sum_out[nid] = s

        dangling_nodes = [nid for nid in active_nodes if sum_out[nid] == 0.0]

        for _ in range(max_iter):
            next_pr = {nid: (1.0 - damping) * p[nid] for nid in active_nodes}

            dangling_sum = sum(pr[nid] for nid in dangling_nodes)
            dangling_share = damping * dangling_sum
            for nid in active_nodes:
                next_pr[nid] += dangling_share * p[nid]

            for target_id in active_nodes:
                incoming_edges = incoming.get(target_id, [])
                for edge in incoming_edges:
                    source_id = edge.source
                    if source_id in pr and sum_out[source_id] > 0.0:
                        weight = edge.weight * traversal_strength(edge.type)
                        next_pr[target_id] += damping * pr[source_id] * (weight / sum_out[source_id])

            err = sum(abs(next_pr[nid] - pr[nid]) for nid in active_nodes)
            pr = next_pr
            if err < tol:
                break

        return pr

    def _pagerank_cache_key(self, damping: float, max_iter: int, tol: float) -> tuple[object, ...]:
        return damping, max_iter, tol, self.structural_signature()

    def structural_signature(self) -> str:
        """Stable hash of active topology and ranking-relevant edge weights."""
        payload = {
            "nodes": sorted(nid for nid, node in self.nodes.items() if node.active),
            "edges": sorted(
                (
                    edge.source,
                    edge.target,
                    edge.type,
                    round(edge.weight, 8),
                    round(edge.confidence, 8),
                    edge.provenance,
                )
                for edge in self.edges
                if edge.active
            ),
        }
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def pagerank_cache_payload(self, damping: float = 0.85, max_iter: int = 20, tol: float = 1e-4) -> dict[str, object]:
        scores = self.pagerank(damping=damping, max_iter=max_iter, tol=tol)
        return {
            "algorithm": "pagerank",
            "version": 1,
            "damping": damping,
            "max_iter": max_iter,
            "tol": tol,
            "signature": self.structural_signature(),
            "scores": scores,
        }

    def seed_pagerank_cache(self, payload: dict[str, object]) -> bool:
        if payload.get("algorithm") != "pagerank" or payload.get("version") != 1:
            return False
        try:
            damping = float(payload.get("damping", 0.85))
            max_iter = int(payload.get("max_iter", 20))
            tol = float(payload.get("tol", 1e-4))
            signature = str(payload["signature"])
            raw_scores = payload["scores"]
        except (KeyError, TypeError, ValueError):
            return False
        if signature != self.structural_signature() or not isinstance(raw_scores, dict):
            return False
        scores = {str(node_id): float(score) for node_id, score in raw_scores.items() if str(node_id) in self.nodes}
        self._pagerank_cache = ((damping, max_iter, tol, signature), scores)
        return True

    def expand(
        self,
        starts: list[str],
        hops: int,
        max_nodes: int | None = None,
        scopes: tuple[str, ...] = (),
        direction: str = "both",
    ) -> tuple[set[str], list[Edge]]:
        if direction not in {"both", "out", "in"}:
            raise ValueError(f"unknown traversal direction: {direction}")
        import math
        outgoing = self.outgoing()
        incoming = self.incoming()
        degrees = self.degree()

        included: set[str] = {
            s for s in starts
            if s in self.nodes and self.nodes[s].active and _node_in_scope(self.nodes[s], scopes)
        }
        seen_edges: set[tuple[str, str, str]] = set()
        edge_list: list[Edge] = []
        frontier = set(included)

        for _ in range(hops):
            new_edges: list[Edge] = []
            scores: dict[str, float] = {}

            for nid in frontier:
                deg = degrees.get(nid, 1)
                deg_penalty = 1.0 / math.sqrt(max(1, deg))

                if direction == "out":
                    candidate_edges = outgoing.get(nid, [])
                elif direction == "in":
                    candidate_edges = incoming.get(nid, [])
                else:
                    candidate_edges = outgoing.get(nid, []) + incoming.get(nid, [])
                for edge in candidate_edges:
                    ekey = (edge.source, edge.target, edge.type)
                    if ekey not in seen_edges:
                        new_edges.append(edge)
                        seen_edges.add(ekey)
                    neighbor = edge.target if edge.source == nid else edge.source
                    if (
                        neighbor not in included
                        and neighbor in self.nodes
                        and self.nodes[neighbor].active
                        and _node_in_scope(self.nodes[neighbor], scopes)
                    ):
                        mult = traversal_strength(edge.type)
                        confidence = edge.confidence * provenance_confidence(edge.provenance)
                        scores[neighbor] = scores.get(neighbor, 0.0) + edge.weight * confidence * mult * deg_penalty

            if not scores:
                for edge in new_edges:
                    if edge.source in included and edge.target in included:
                        edge_list.append(edge)
                break

            # Rank candidates by cumulative weighted score (sum, not max), apply budget.
            ranked = sorted(scores, key=scores.__getitem__, reverse=True)
            if max_nodes is not None:
                available = max_nodes - len(included)
                if available <= 0:
                    break
                ranked = ranked[:available]

            next_set = set(ranked)
            all_included = included | next_set

            for edge in new_edges:
                if edge.source in all_included and edge.target in all_included:
                    edge_list.append(edge)

            included = all_included
            frontier = next_set

            if max_nodes is not None and len(included) >= max_nodes:
                break

        return included, edge_list


def _node_in_scope(node: Node, scopes: tuple[str, ...]) -> bool:
    if not scopes:
        return True
    values = (node.scope, node.path, node.source)
    return any(value == scope or value.startswith(scope.rstrip("/") + "/") for scope in scopes for value in values if value)
