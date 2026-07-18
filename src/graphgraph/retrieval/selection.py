import math
from collections import Counter
from heapq import heappop, heappush
from typing import Dict, Iterator, List, Set, Tuple

from ..graph.core import Edge, Graph
from ..planning.token_cost import packet_marginal_costs


def build_bfs_tree(
    graph: Graph,
    starts: Tuple[str, ...],
    candidates: Set[str],
    edges: List[Edge] | None = None,
) -> Dict[str, List[str]]:
    """Build a BFS spanning forest rooted at starts, restricted to candidates.

    Returns a mapping parent -> [children].
    """
    tree: Dict[str, List[str]] = {nid: [] for nid in candidates}
    visited = set(starts)
    queue = list(starts)

    # Pre-build adjacency for fast lookup
    if edges is None:
        outgoing = graph.outgoing()
        incoming = graph.incoming()
    else:
        outgoing: Dict[str, List[Edge]] = {}
        incoming: Dict[str, List[Edge]] = {}
        for edge in edges:
            outgoing.setdefault(edge.source, []).append(edge)
            incoming.setdefault(edge.target, []).append(edge)

    head = 0
    while head < len(queue):
        curr = queue[head]
        head += 1

        # Check both outgoing and incoming edges for reachability
        edges = outgoing.get(curr, []) + incoming.get(curr, [])
        for edge in edges:
            neighbor = edge.target if edge.source == curr else edge.source
            if neighbor in candidates and neighbor not in visited:
                visited.add(neighbor)
                # setdefault, not tree[curr]: curr can be a start node that
                # isn't itself in candidates (e.g. an inactive/out-of-scope
                # anchor after graph.expand() drops it), so it may not have
                # been pre-seeded as a key by the dict comprehension above.
                tree.setdefault(curr, []).append(neighbor)
                queue.append(neighbor)

    return tree


def tree_knapsack_context_partition(
    graph: Graph,
    starts: Tuple[str, ...],
    candidates: Set[str],
    node_values: Dict[str, float],
    max_token_budget: int,
    *,
    edges: List[Edge] | None = None,
    packet: str = "gg",
    max_nodes: int | None = None,
    include_orphans: bool = True,
) -> Set[str]:
    """Selects an optimal connected subgraph of candidates using Tree Knapsack DP.

    Values are node relevance scores (PPR/lexical).
    Weights are estimated token footprints bucketed into discrete sizes.
    Ensures connectivity: a node is only selected if its parent in the BFS forest
    is also selected, guaranteeing reachability back to anchor roots.
    """
    if not candidates:
        return set()

    # 1. Estimate packet-aware weights. Edge rows dominate gg cost, so
    # share each incident edge's measured marginal cost across its endpoints.
    candidate_edges = edges if edges is not None else graph.edges
    raw_weights = packet_node_costs(
        graph,
        candidates,
        candidate_edges,
        packet=packet,
        token_budget=max_token_budget,
        max_nodes=max_nodes,
    )

    bucket_size = max(1.0, max_token_budget / 128.0)
    weights = {nid: max(1, int(math.ceil(cost / bucket_size))) for nid, cost in raw_weights.items()}
    max_weight = max(1, int(math.floor(max_token_budget / bucket_size)))

    # 2. Build BFS forest structure
    tree = build_bfs_tree(graph, starts, candidates, candidate_edges)

    # 3. Post-order DFS traversal to compute DP tables
    # dp[u][w] represents the maximum value in the subtree of u using weight at most w,
    # UNDER THE CONDITION that u ITSELF is selected.
    dp: Dict[str, List[float]] = {}

    # Keep track of traversal order
    post_order: List[str] = []
    visited_dfs = set()

    def dfs(root: str) -> None:
        # Iterative post-order traversal (explicit stack of (node, child
        # iterator) frames) rather than function recursion: a long
        # dependency chain -- plausible in a 2000-node graph -- can exceed
        # Python's default recursion limit (~1000) and crash with
        # RecursionError.
        visited_dfs.add(root)
        stack: List[Tuple[str, Iterator[str]]] = [(root, iter(tree.get(root, [])))]
        while stack:
            node, children_iter = stack[-1]
            advanced = False
            for child in children_iter:
                if child not in visited_dfs:
                    visited_dfs.add(child)
                    stack.append((child, iter(tree.get(child, []))))
                    advanced = True
                    break
            if not advanced:
                post_order.append(node)
                stack.pop()

    for s in starts:
        if s in candidates and s not in visited_dfs:
            dfs(s)

    # Also visit any orphan candidates not reachable from starts. Record each
    # one as its own root *before* recursing -- dfs() marks the whole subtree
    # visited immediately, so deriving "was this an orphan root" from
    # visited_dfs afterward (as opposed to recording it up front) always
    # comes back empty, silently making every disconnected component
    # unselectable even though its DP table gets computed.
    orphan_roots: List[str] = []
    if include_orphans:
        for nid in candidates:
            if nid not in visited_dfs:
                orphan_roots.append(nid)
                dfs(nid)

    # Run DP bottom-up
    for u in post_order:
        w_u = weights[u]
        val_u = node_values.get(u, 0.0)

        # Initialize DP table for u:
        # If weight is less than w_u, we cannot select u, so value is 0.
        # If weight is >= w_u, the base value is val_u.
        table = [0.0] * (max_weight + 1)
        for w in range(w_u, max_weight + 1):
            table[w] = val_u

        # Merge children tables
        for v in tree.get(u, []):
            if v not in dp:
                continue
            child_table = dp[v]

            # Temporary table for the merge
            next_table = list(table)
            # Standard knapsack merge: merge child_table into next_table.
            # Because u must be selected, the child can only be allocated weight up to (w - w_u).
            for w in range(w_u, max_weight + 1):
                best = table[w]
                # Child can take some weight w_c, leaving w - w_c for parent subtree
                for w_c in range(1, w - w_u + 1):
                    val_c = child_table[w_c]
                    if val_c > 0:
                        best = max(best, table[w - w_c] + val_c)
                next_table[w] = best
            table = next_table

        dp[u] = table

    # 4. Backtracking to extract the selected nodes
    # For a forest, we create a dummy root node connecting all trees.
    # But since starts are the roots, we can run a simple knapsack over the start roots.
    roots = list(starts) + orphan_roots
    roots = [r for r in roots if r in dp]

    # Knapsack over roots
    root_dp = [0.0] * (max_weight + 1)
    # parent_choice[root_idx][w] = w_root allocated to this root
    choices: List[Dict[int, int]] = []

    for r in roots:
        r_table = dp[r]
        next_root_dp = list(root_dp)
        choice_dict = {}
        for w in range(max_weight + 1):
            best_val = root_dp[w]
            best_w_c = 0
            for w_c in range(w + 1):
                if r_table[w_c] > 0 or w_c == 0:
                    val = root_dp[w - w_c] + r_table[w_c]
                    if val > best_val:
                        best_val = val
                        best_w_c = w_c
            next_root_dp[w] = best_val
            choice_dict[w] = best_w_c
        root_dp = next_root_dp
        choices.append(choice_dict)

    # Backtrack root allocations
    selected: Set[str] = set()
    curr_w = max_weight

    for i in range(len(roots) - 1, -1, -1):
        r = roots[i]
        allocated_w = choices[i].get(curr_w, 0)
        if allocated_w > 0:
            # Backtrack into the subtree of r
            subtree_backtrack(r, allocated_w, tree, weights, dp, selected)
            curr_w -= allocated_w

    # Ensure all start nodes are always included
    for s in starts:
        if s in candidates:
            selected.add(s)

    return selected


def connected_greedy_context_partition(
    graph: Graph,
    starts: Tuple[str, ...],
    candidates: Set[str],
    node_values: Dict[str, float],
    max_token_budget: int,
    *,
    edges: List[Edge] | None = None,
    packet: str = "gg",
    max_nodes: int | None = None,
    include_orphans: bool = False,
) -> Set[str]:
    """Select a connected forest by marginal value per estimated token."""
    if not candidates:
        return set()
    candidate_edges = edges if edges is not None else graph.edges
    costs = packet_node_costs(
        graph,
        candidates,
        candidate_edges,
        packet=packet,
        token_budget=max_token_budget,
        max_nodes=max_nodes,
    )
    tree = build_bfs_tree(graph, starts, candidates, candidate_edges)
    roots = [start for start in starts if start in candidates]
    if include_orphans:
        children = {child for values in tree.values() for child in values}
        roots.extend(sorted(node_id for node_id in candidates if node_id not in children and node_id not in roots))

    selected = set(roots)
    spent = sum(costs[node_id] for node_id in roots)
    frontier: list[tuple[float, str]] = []

    def offer(node_id: str) -> None:
        cost = costs[node_id]
        ratio = node_values.get(node_id, 0.0) / max(cost, 1e-9)
        heappush(frontier, (-ratio, node_id))

    for root in roots:
        for child in tree.get(root, ()):
            offer(child)

    while frontier:
        _negative_ratio, node_id = heappop(frontier)
        if node_id in selected:
            continue
        if max_nodes is not None and len(selected) >= max_nodes:
            break
        cost = costs[node_id]
        if spent + cost > max_token_budget:
            continue
        selected.add(node_id)
        spent += cost
        for child in tree.get(node_id, ()):
            offer(child)
    return selected


def packet_node_costs(
    graph: Graph,
    candidates: Set[str],
    candidate_edges: List[Edge],
    *,
    packet: str,
    token_budget: int,
    max_nodes: int | None,
) -> Dict[str, float]:
    """Estimate each candidate's packet contribution, including shared edges."""
    incidence: Counter[str] = Counter()
    for edge in candidate_edges:
        if edge.source in candidates and edge.target in candidates:
            incidence[edge.source] += 1
            incidence[edge.target] += 1

    node_cost, edge_cost = packet_marginal_costs(packet)
    node_floor = token_budget / max(1, max_nodes) if max_nodes else 0.0
    costs: Dict[str, float] = {}
    for node_id in candidates:
        node = graph.nodes[node_id]
        label_cost = max(node_cost, len(node.label) / 4.0)
        metadata_cost = 0.0
        if packet in {"gg_hybrid", "hybrid", "doc_summary"}:
            metadata_cost = len(node.summary or "") / 4.0 + sum(len(fact) / 4.0 for fact in node.facts)
        costs[node_id] = max(1.0, node_floor, label_cost + metadata_cost + incidence[node_id] * edge_cost / 2.0)
    return costs


def subtree_backtrack(
    u: str,
    allocated_w: int,
    tree: Dict[str, List[str]],
    weights: Dict[str, int],
    dp: Dict[str, List[float]],
    selected: Set[str],
):
    """Reconstructs the selected nodes in the subtree of u.

    Iterative (explicit worklist of pending (node, allocated_w) pairs)
    rather than recursive: a long dependency chain -- plausible in a
    2000-node graph -- can exceed Python's default recursion limit
    (~1000) and crash with RecursionError. Each node's own DP-state
    reconstruction is unchanged (it was already loop-based); only the
    descent into children is converted from a recursive call to a stack
    push processed by the same loop.
    """
    work: List[Tuple[str, int]] = [(u, allocated_w)]
    while work:
        node, node_allocated_w = work.pop()
        selected.add(node)
        w_node = weights[node]
        remaining_w = node_allocated_w - w_node
        if remaining_w <= 0:
            continue

        children = tree.get(node, [])
        if not children:
            continue

        # Standard DP backtrack over children merges
        # We rebuild the state sequence to see which child took how much weight.
        # dp_states[i][w] = value of merging first i children using weight w.
        dp_states = []
        curr_state = [0.0] * (remaining_w + 1)

        # Base state: node alone (0 child value)
        dp_states.append(list(curr_state))

        for child in children:
            if child not in dp:
                continue
            c_table = dp[child]
            next_state = list(curr_state)
            for w in range(remaining_w + 1):
                best = curr_state[w]
                for w_c in range(w + 1):
                    if c_table[w_c] > 0 or w_c == 0:
                        val = curr_state[w - w_c] + c_table[w_c]
                        if val > best:
                            best = val
                next_state[w] = best
            curr_state = next_state
            dp_states.append(list(curr_state))

        # Reconstruct backwards
        curr_w = remaining_w
        for idx in range(len(children) - 1, -1, -1):
            child = children[idx]
            if child not in dp:
                continue

            c_table = dp[child]
            prev_state = dp_states[idx]

            # Find which w_c was used
            best_w_c = 0
            for w_c in range(curr_w + 1):
                if c_table[w_c] > 0 or w_c == 0:
                    val = prev_state[curr_w - w_c] + c_table[w_c]
                    if abs(val - curr_state[curr_w]) < 1e-5:
                        best_w_c = w_c
                        break

            if best_w_c > 0:
                work.append((child, best_w_c))
                curr_w -= best_w_c

            curr_state = prev_state
