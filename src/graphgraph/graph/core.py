from __future__ import annotations

import hashlib
import heapq
import json
import re
from dataclasses import dataclass, field
from typing import Callable

from .ontology import provenance_confidence, traversal_strength

_LINE_RE = re.compile(r"\bL(\d+)\b")


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

    @property
    def line(self) -> int | None:
        """1-based source line this node's definition starts at, if known.

        The scanner encodes this as an "L<N>" token in `summary` at
        extraction time (see scanner/ast.py, scanner/doc.py) rather than as
        its own stored field, so this stays correct for every already-saved
        graph without a schema/format migration. This is the single place
        that convention gets decoded -- callers should always go through
        `node.line`, never re-parse `summary` themselves.
        """
        match = _LINE_RE.search(self.summary or "")
        if not match:
            return None
        try:
            return max(1, int(match.group(1)))
        except ValueError:
            return None

    @property
    def normalized_scope_values(self) -> tuple[str, ...]:
        try:
            return self._normalized_scope_values
        except AttributeError:
            vals = []
            for val in (self.scope, self.path, self.source):
                if val:
                    vals.append(val.replace("\\", "/").strip("/"))
            tup = tuple(vals)
            object.__setattr__(self, "_normalized_scope_values", tup)
            return tup


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

    @property
    def traversal_val(self) -> float:
        try:
            return self._traversal_val
        except AttributeError:
            mult = traversal_strength(self.type)
            conf = self.confidence * provenance_confidence(self.provenance)
            val = self.weight * conf * mult
            object.__setattr__(self, "_traversal_val", val)
            return val


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
    _search_token_cache: tuple[tuple[object, ...], object] | None = field(default=None, init=False, repr=False)
    _search_index_by_id_cache: tuple[tuple[object, ...], dict[str, object]] | None = field(default=None, init=False, repr=False)

    def _edges_by_key(self, key_fn: Callable[[Edge], str]) -> dict[str, list[Edge]]:
        grouped: dict[str, list[Edge]] = {}
        for edge in self.edges:
            if edge.active:
                grouped.setdefault(key_fn(edge), []).append(edge)
        return grouped

    def _cached_edges_by_key(
        self,
        cache_attr: str,
        key_fn: Callable[[Edge], str],
    ) -> dict[str, list[Edge]]:
        cache = getattr(self, cache_attr, None)
        if cache is not None:
            cache_len, grouped = cache
            if cache_len == len(self.edges):
                return grouped
        grouped = self._edges_by_key(key_fn)
        setattr(self, cache_attr, (len(self.edges), grouped))
        return grouped

    def outgoing(self) -> dict[str, list[Edge]]:
        return self._cached_edges_by_key("_outgoing_cache_data", lambda e: e.source)

    def incoming(self) -> dict[str, list[Edge]]:
        return self._cached_edges_by_key("_incoming_cache_data", lambda e: e.target)

    def degree(self) -> dict[str, int]:
        cache = getattr(self, "_degree_cache_data", None)
        if cache is not None:
            cache_len, deg = cache
            if cache_len == len(self.edges):
                return deg
        deg: dict[str, int] = {}
        for edge in self.edges:
            if not edge.active:
                continue
            deg[edge.source] = deg.get(edge.source, 0) + 1
            deg[edge.target] = deg.get(edge.target, 0) + 1
        self._degree_cache_data = (len(self.edges), deg)
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
            return self._pagerank_cache[1]

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

        # Precompute transitions
        transitions = {}
        for target_id in active_nodes:
            incoming_edges = incoming.get(target_id, [])
            valid_incoming = []
            for edge in incoming_edges:
                source_id = edge.source
                if source_id in pr and sum_out[source_id] > 0.0:
                    weight = edge.weight * traversal_strength(edge.type)
                    factor = damping * (weight / sum_out[source_id])
                    valid_incoming.append((source_id, factor))
            transitions[target_id] = valid_incoming

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
                for source_id, factor in transitions[target_id]:
                    next_pr[target_id] += pr[source_id] * factor

            # Check convergence
            err = sum(abs(next_pr[nid] - pr[nid]) for nid in active_nodes)
            pr = next_pr
            if err < tol:
                break

        if cache_key is not None:
            self._pagerank_cache = (cache_key, pr)
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

        nid_to_idx = {nid: i for i, nid in enumerate(active_nodes)}

        # Normalize personalization vector
        total_p = sum(personalization.get(nid, 0.0) for nid in active_nodes)
        if total_p > 0:
            p_arr = [personalization.get(nid, 0.0) / total_p for nid in active_nodes]
        else:
            p_arr = [1.0 / N] * N

        pr_arr = list(p_arr)

        outgoing = self.outgoing()
        incoming = self.incoming()
        
        sum_out_arr = [0.0] * N
        for i, nid in enumerate(active_nodes):
            s = 0.0
            for edge in outgoing.get(nid, []):
                if edge.target in nid_to_idx:
                    s += edge.weight * traversal_strength(edge.type)
            sum_out_arr[i] = s

        dangling_indices = [i for i, val in enumerate(sum_out_arr) if val == 0.0]

        # Precompute transitions using integer indices
        transitions_arr = [[] for _ in range(N)]
        for i, target_id in enumerate(active_nodes):
            incoming_edges = incoming.get(target_id, [])
            valid_incoming = []
            for edge in incoming_edges:
                source_id = edge.source
                src_idx = nid_to_idx.get(source_id)
                if src_idx is not None and sum_out_arr[src_idx] > 0.0:
                    weight = edge.weight * traversal_strength(edge.type)
                    factor = damping * (weight / sum_out_arr[src_idx])
                    valid_incoming.append((src_idx, factor))
            transitions_arr[i] = valid_incoming

        one_minus_damping = 1.0 - damping

        for _ in range(max_iter):
            next_pr_arr = [one_minus_damping * p_val for p_val in p_arr]

            dangling_sum = sum(pr_arr[idx] for idx in dangling_indices)
            dangling_share = damping * dangling_sum
            for i in range(N):
                next_pr_arr[i] += dangling_share * p_arr[i]

            for i in range(N):
                for src_idx, factor in transitions_arr[i]:
                    next_pr_arr[i] += pr_arr[src_idx] * factor

            err = sum(abs(next_val - curr_val) for next_val, curr_val in zip(next_pr_arr, pr_arr))
            pr_arr = next_pr_arr
            if err < tol:
                break

        return {nid: pr_arr[i] for i, nid in enumerate(active_nodes)}

    def localized_personalized_pagerank(
        self,
        personalization: dict[str, float],
        damping: float = 0.85,
        tolerance: float = 1e-4,
        max_nodes: int = 512,
        max_pushes: int = 4096,
    ) -> dict[str, float]:
        """Approximate personalized PageRank with bounded residual pushes.

        Query-time personalization is usually concentrated on a handful of
        lexical and modified-file seeds. A full power iteration touches the
        entire graph for every query; this pushes only residual probability
        reachable from those seeds and stops at explicit work limits.
        """
        active_seeds = {
            node_id: max(0.0, weight)
            for node_id, weight in personalization.items()
            if weight > 0.0 and node_id in self.nodes and self.nodes[node_id].active
        }
        total = sum(active_seeds.values())
        if total <= 0.0:
            return self.pagerank()

        residual = {node_id: weight / total for node_id, weight in active_seeds.items()}
        scores: dict[str, float] = {}
        queue = [(-mass, node_id) for node_id, mass in residual.items()]
        heapq.heapify(queue)
        discovered = set(residual)
        outgoing = self.outgoing()
        pushes = 0

        while queue and pushes < max_pushes:
            _neg_mass, node_id = heapq.heappop(queue)
            mass = residual.pop(node_id, 0.0)
            if mass < tolerance:
                scores[node_id] = scores.get(node_id, 0.0) + mass
                continue
            pushes += 1

            retained = (1.0 - damping) * mass
            scores[node_id] = scores.get(node_id, 0.0) + retained
            distributable = damping * mass
            transitions = [
                (edge.target, edge.weight * traversal_strength(edge.type))
                for edge in outgoing.get(node_id, ())
                if edge.target in self.nodes and self.nodes[edge.target].active
            ]
            denominator = sum(weight for _target, weight in transitions)
            if denominator <= 0.0:
                scores[node_id] += distributable
                continue

            undistributed = 0.0
            for target, weight in transitions:
                share = distributable * weight / denominator
                if target not in discovered and len(discovered) >= max_nodes:
                    undistributed += share
                    continue
                discovered.add(target)
                residual[target] = residual.get(target, 0.0) + share
                if residual[target] >= tolerance:
                    heapq.heappush(queue, (-residual[target], target))
            if undistributed:
                scores[node_id] += undistributed

        for node_id, mass in residual.items():
            scores[node_id] = scores.get(node_id, 0.0) + mass
        score_total = sum(scores.values())
        if score_total > 0.0:
            scores = {node_id: score / score_total for node_id, score in scores.items()}
        return scores

    def _pagerank_cache_key(self, damping: float, max_iter: int, tol: float) -> tuple[object, ...]:
        return damping, max_iter, tol, self.structural_signature()

    def structural_signature(self) -> str:
        """Stable hash of active topology and ranking-relevant edge weights."""
        cache = getattr(self, "_structural_sig_cache", None)
        fingerprint = (
            len(self.nodes),
            len(self.edges),
            sum(hash(nid) for nid in self.nodes),
            sum(hash(e.source) ^ hash(e.target) ^ hash(e.type) for e in self.edges)
        )
        if cache is not None:
            cache_fingerprint, sig = cache
            if cache_fingerprint == fingerprint:
                return sig

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
        sig = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        self._structural_sig_cache = (fingerprint, sig)
        return sig

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
        decay_hubs: bool = False,
        allowed_relations: set[str] | frozenset[str] | None = None,
        priority_bias: dict[str, float] | None = None,
    ) -> tuple[set[str], list[Edge]]:
        if direction not in {"both", "out", "in"}:
            raise ValueError(f"unknown traversal direction: {direction}")
        import math
        outgoing = self.outgoing()
        incoming = self.incoming()
        degrees = self.degree()

        # Pre-normalize scopes
        normalized_scopes = []
        for scope in scopes:
            norm = scope.replace("\\", "/").strip("/")
            normalized_scopes.append((norm, norm + "/"))

        included: set[str] = {
            s for s in starts
            if s in self.nodes and self.nodes[s].active and _node_in_scope(self.nodes[s], normalized_scopes)
        }
        seen_edges: set[tuple[str, str, str]] = set()
        edge_list: list[Edge] = []
        # Hop-0 evidence: edges directly connecting two of the caller's own
        # start nodes. When hops >= 1 these fall out for free (either the
        # `not scores` catch-up branch or the `all_included` filter after
        # each round picks them up), but with hops=0 the loop below never
        # runs at all, so without this pre-pass any edge between two
        # already-included starts is silently dropped even though both
        # endpoints are already selected.
        for nid in included:
            for edge in outgoing.get(nid, []) + incoming.get(nid, []):
                if edge.source in included and edge.target in included:
                    ekey = (edge.source, edge.target, edge.type)
                    if ekey not in seen_edges:
                        seen_edges.add(ekey)
                        edge_list.append(edge)
        frontier = set(included)
        node_energies: dict[str, float] = {s: 100.0 for s in included}

        for _ in range(hops):
            new_edges: list[Edge] = []
            scores: dict[str, float] = {}
            next_energies: dict[str, float] = {}

            for nid in frontier:
                deg = degrees.get(nid, 1)
                deg_penalty = 1.0 / math.sqrt(max(1, deg))
                current_energy = node_energies.get(nid, 100.0)

                if direction == "out":
                    candidate_edges = outgoing.get(nid, [])
                elif direction == "in":
                    candidate_edges = incoming.get(nid, [])
                else:
                    candidate_edges = outgoing.get(nid, []) + incoming.get(nid, [])
                if allowed_relations is not None:
                    gated_edges = [edge for edge in candidate_edges if edge.type in allowed_relations]
                    if gated_edges:
                        candidate_edges = gated_edges
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
                        and _node_in_scope(self.nodes[neighbor], normalized_scopes)
                    ):
                        if decay_hubs:
                            resistance = 1.0 / max(1e-9, edge.traversal_val)
                            degree_drain = 1.0 + math.log10(max(1, deg))
                            decay = resistance * degree_drain * 25.0
                            new_energy = current_energy - decay
                            if new_energy > 0:
                                next_energies[neighbor] = max(next_energies.get(neighbor, 0.0), new_energy)
                                scores[neighbor] = scores.get(neighbor, 0.0) + edge.traversal_val * deg_penalty * (new_energy / 100.0)
                        else:
                            scores[neighbor] = scores.get(neighbor, 0.0) + edge.traversal_val * deg_penalty

            if not scores:
                for edge in new_edges:
                    if edge.source in included and edge.target in included:
                        edge_list.append(edge)
                break

            # Rank candidates by cumulative weighted score (sum, not max), apply budget.
            # An optional priority bias multiplies a candidate's score by
            # (1 + bias): callers supply a normalized query-relevance signal so
            # the budget truncation below keeps the most relevant frontier
            # nodes (e.g. the document sections that answer the query) instead
            # of ranking on graph shape alone. Absent/zero bias is a no-op.
            if priority_bias:
                ranked = sorted(
                    scores,
                    key=lambda nid: scores[nid] * (1.0 + priority_bias.get(nid, 0.0)),
                    reverse=True,
                )
            else:
                ranked = sorted(scores, key=scores.__getitem__, reverse=True)
            if max_nodes is not None:
                available = max_nodes - len(included)
                if available <= 0:
                    # Budget's already spent, so no new node from this round
                    # will be added -- but new_edges may still contain edges
                    # discovered this round between two nodes that were
                    # already included in an earlier round (e.g. a back-edge
                    # found while expanding the frontier). Same catch-up the
                    # `not scores` branch above already does; without it,
                    # breaking here silently drops those intra-subgraph edges
                    # from the packet.
                    for edge in new_edges:
                        if edge.source in included and edge.target in included:
                            edge_list.append(edge)
                    break
                ranked = ranked[:available]

            next_set = set(ranked)
            for neighbor in next_set:
                node_energies[neighbor] = max(node_energies.get(neighbor, 0.0), next_energies.get(neighbor, 0.0))
            all_included = included | next_set

            for edge in new_edges:
                if edge.source in all_included and edge.target in all_included:
                    edge_list.append(edge)

            included = all_included
            frontier = next_set

            if max_nodes is not None and len(included) >= max_nodes:
                break

        return included, edge_list


def _node_in_scope(node: Node, normalized_scopes: list[tuple[str, str]]) -> bool:
    if not normalized_scopes:
        return True
    for norm_val in node.normalized_scope_values:
        for prefix, prefix_slash in normalized_scopes:
            if norm_val == prefix or norm_val.startswith(prefix_slash):
                return True
    return False
