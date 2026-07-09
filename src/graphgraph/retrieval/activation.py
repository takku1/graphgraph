from __future__ import annotations

import json
from pathlib import Path

from ..graph.core import Edge, Graph


class ActivationStateCache:
    """Saves and loads node activation state across turns in .graphgraph/activation_state.json."""

    def __init__(self, cache_path: Path | None = None):
        self.cache_path = cache_path or Path(".graphgraph") / "activation_state.json"

    def load(self) -> dict[str, float]:
        if not self.cache_path.exists():
            return {}
        try:
            return json.loads(self.cache_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def save(self, state: dict[str, float]) -> None:
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
        except Exception:
            pass


def spreading_activation(
    graph: Graph,
    starts: list[str],
    max_nodes: int = 120,
    alpha: float = 0.6,
    steps: int = 2,
    decay: float = 0.6,
    previous_activation: dict[str, float] | None = None,
) -> tuple[set[str], list[Edge]]:
    """Spreads relevance scores starting from initial anchors through AST/Doc edges.

    Integrates temporal decay from previous turns to capture conversational context.
    """
    activation: dict[str, float] = {}

    # 1. Apply conversational decay to previous activation state.
    # Must check node.active, not just membership: the cache persists across
    # turns in .graphgraph/activation_state.json, and the graph can mutate
    # between turns (a file gets deleted/merged and its node is soft-deleted
    # via expire_node). Without this check a since-expired node's cached
    # energy gets reinjected and the node can resurface in selected_nodes
    # below even though it's no longer live -- the same soft-delete leak
    # search_nodes had before it started filtering on .active.
    if previous_activation:
        for node_id, score in previous_activation.items():
            if node_id in graph.nodes and graph.nodes[node_id].active:
                activation[node_id] = score * decay

    # 2. Inject query-start energy (injection = 1.0)
    for start in starts:
        if start in graph.nodes and graph.nodes[start].active:
            activation[start] = activation.get(start, 0.0) + 1.0

    # 3. Spread activation through outgoing and incoming edges
    inc = graph.incoming()
    outg = graph.outgoing()

    for step in range(steps):
        next_activation = dict(activation)
        for node_id, energy in activation.items():
            if energy <= 0.01:
                continue

            neighbors = []
            if node_id in outg:
                neighbors.extend(
                    e.target for e in outg[node_id]
                    if e.active and e.target in graph.nodes and graph.nodes[e.target].active
                )
            if node_id in inc:
                neighbors.extend(
                    e.source for e in inc[node_id]
                    if e.active and e.source in graph.nodes and graph.nodes[e.source].active
                )

            if neighbors:
                # Distribute alpha fraction of current energy to neighbors
                spread_energy = (alpha * energy) / len(neighbors)
                for neighbor in neighbors:
                    next_activation[neighbor] = next_activation.get(neighbor, 0.0) + spread_energy

        # 4. Marginal-utility early stopping: a greedy cutoff, not a value function or
        # MDP formalism -- stop spreading once the new energy per estimated token spent
        # falls below the convergence threshold.
        new_nodes = {nid: score for nid, score in next_activation.items() if nid not in activation}
        total_new_energy = sum(new_nodes.values())
        # Estimate token cost of new nodes (roughly 8.0 tokens per node)
        estimated_new_tokens = len(new_nodes) * 8.0
        if estimated_new_tokens > 0:
            marginal_utility = total_new_energy / estimated_new_tokens
            # If the expected marginal utility falls below our convergence threshold, stop early
            if marginal_utility < 0.005:
                break

        activation = next_activation

    # 4. Sort and select the top max_nodes by score
    sorted_nodes = sorted(activation.items(), key=lambda x: x[1], reverse=True)
    selected_nodes = {nid for nid, score in sorted_nodes[:max_nodes] if nid in graph.nodes and graph.nodes[nid].active}

    # 5. Extract interconnecting edges
    selected_edges = []
    for edge in graph.edges:
        if edge.active and edge.source in selected_nodes and edge.target in selected_nodes:
            selected_edges.append(edge)

    # Save active state to cache for next turns
    # Filter to save only nodes with significant energy
    save_state = {nid: score for nid, score in sorted_nodes[:200] if score > 0.05 and nid in graph.nodes}
    ActivationStateCache().save(save_state)

    return selected_nodes, selected_edges
