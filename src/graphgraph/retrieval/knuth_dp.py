import math
from typing import Dict, List, Set, Tuple

from ..graph.core import Graph


def build_bfs_tree(
    graph: Graph,
    starts: Tuple[str, ...],
    candidates: Set[str],
) -> Dict[str, List[str]]:
    """Build a BFS spanning forest rooted at starts, restricted to candidates.
    
    Returns a mapping parent -> [children].
    """
    tree: Dict[str, List[str]] = {nid: [] for nid in candidates}
    visited = set(starts)
    queue = list(starts)
    
    # Pre-build adjacency for fast lookup
    outgoing = graph.outgoing()
    incoming = graph.incoming()
    
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
                tree[curr].append(neighbor)
                queue.append(neighbor)
                
    return tree

def knuth_dp_context_partition(
    graph: Graph,
    starts: Tuple[str, ...],
    candidates: Set[str],
    node_values: Dict[str, float],
    max_token_budget: int,
) -> Set[str]:
    """Selects an optimal connected subgraph of candidates using Tree Knapsack DP.
    
    Values are node relevance scores (PPR/lexical).
    Weights are estimated token footprints bucketed into discrete sizes.
    """
    if not candidates:
        return set()
    
    # 1. Estimate weights (bucketed into integers to keep DP tables small)
    weights: Dict[str, int] = {}
    for nid in candidates:
        node = graph.nodes[nid]
        size = len(node.facts) * 10 + len(node.summary or "")
        # Bucket size: 1 unit = 40 tokens. Minimum weight is 1.
        weights[nid] = max(1, min(20, int(math.ceil(size / 40.0))))
        
    # Bucketed budget
    max_weight = max(1, int(max_token_budget / 40))
    
    # 2. Build BFS forest structure
    tree = build_bfs_tree(graph, starts, candidates)
    
    # 3. Post-order DFS traversal to compute DP tables
    # dp[u][w] represents the maximum value in the subtree of u using weight at most w,
    # UNDER THE CONDITION that u ITSELF is selected.
    dp: Dict[str, List[float]] = {}
    
    # Keep track of traversal order
    post_order: List[str] = []
    visited_dfs = set()
    
    def dfs(u: str):
        visited_dfs.add(u)
        for v in tree.get(u, []):
            if v not in visited_dfs:
                dfs(v)
        post_order.append(u)
        
    for s in starts:
        if s in candidates and s not in visited_dfs:
            dfs(s)
            
    # Also visit any orphan candidates not reachable from starts just in case
    for nid in candidates:
        if nid not in visited_dfs:
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
    roots = list(starts) + [nid for nid in candidates if nid not in visited_dfs]
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

def subtree_backtrack(
    u: str,
    allocated_w: int,
    tree: Dict[str, List[str]],
    weights: Dict[str, int],
    dp: Dict[str, List[float]],
    selected: Set[str],
):
    """Recursively reconstructs the selected nodes in the subtree of u."""
    selected.add(u)
    w_u = weights[u]
    remaining_w = allocated_w - w_u
    if remaining_w <= 0:
        return
        
    children = tree.get(u, [])
    if not children:
        return
        
    # Standard DP backtrack over children merges
    # We rebuild the state sequence to see which child took how much weight.
    # dp_states[i][w] = value of merging first i children using weight w.
    dp_states = []
    curr_state = [0.0] * (remaining_w + 1)
    
    # Base state: u alone (0 child value)
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
            subtree_backtrack(child, best_w_c, tree, weights, dp, selected)
            curr_w -= best_w_c
            
        curr_state = prev_state
