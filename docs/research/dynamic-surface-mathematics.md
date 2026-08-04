# Mathematical Framework: Dynamic Spreading Activation & Budget Throttling

This document formalizes the mathematics behind GraphGraph's dynamic context retrieval, edge density throttling, and conversation-decay caching.

---

## 1. Spreading Activation Model with Conservation & Retention

To model context relevance as a fluid field over the codebase graph $G = (V, E)$, we define a discrete-time spreading activation process. Let $A^{(t)} \in \mathbb{R}^{|V|}$ be the activation state vector at propagation step $t$.

### A. Initialization & Injection
Let $V_{\text{init}} \subset V$ be the set of query anchors discovered via lexical/semantic lookup. The initial activation vector $A^{(0)}$ is defined as:

$$A_v^{(0)} = A_{\text{prior}, v} \cdot \gamma + I_v$$

Where:
*   $\gamma \in [0, 1]$ is the **conversational decay coefficient** (default $\gamma = 0.6$).
*   $A_{\text{prior}} \in \mathbb{R}^{|V|}$ is the activation state vector from the previous turn.
*   $I \in \mathbb{R}^{|V|}$ is the **query energy injection vector**:
    $$I_v = \begin{cases} 1.0 & \text{if } v \in V_{\text{init}} \\ 0.0 & \text{otherwise} \end{cases}$$

### B. Propagation Step (Transition Dynamics)
At each step $t \rightarrow t+1$, active nodes distribute a fraction of their energy to their immediate neighborhood. We define the transition step as:

$$A_u^{(t+1)} = A_u^{(t)} + \sum_{v \in \mathcal{N}(u)} \frac{\alpha \cdot A_v^{(t)}}{d_{\text{out}}(v)}$$

Where:
*   $\alpha \in [0, 1]$ is the **propagation coefficient** (default $\alpha = 0.6$).
*   $\mathcal{N}(u)$ is the set of neighboring nodes connected to $u$ (both incoming and outgoing).
*   $d_{\text{out}}(v) = |\mathcal{N}(v)|$ is the degree of node $v$.

### C. Convergence & Boundary
The propagation is run for a fixed number of steps $k$ (typically $k=2$). The final relevance score $S_v$ for sorting is:

$$S_v = A_v^{(k)}$$

This formulation naturally resolves multi-path intersections: if a node $u$ is referenced by multiple active call paths, its activation score compounds additively, reflecting its high centrality in the queried context.

---

## 2. Edge Density Throttling

To prevent token window explosion in dense subgraphs (e.g., highly connected algebraic rule systems or e-graphs), the system calculates the **Node-to-Edge Ratio** ($R_{ne}$) of the expanded subgraph:

$$R_{ne} = \frac{|E_{\text{sub}}|}{|V_{\text{sub}}|}$$

Let $B_{\text{target}}$ be the target node budget (e.g., $B_{\text{target}} = 120$). The **effective node budget** $B_{\text{eff}}$ is defined as:

$$B_{\text{eff}} = \max\left(B_{\text{min}}, \min\left(B_{\text{target}}, \left\lfloor B_{\text{target}} \cdot \Phi(R_{ne}) \right\rfloor\right)\right)$$

Where the throttle function $\Phi(R_{ne})$ is defined as:

$$\Phi(R_{ne}) = \begin{cases} 1.0 & \text{if } R_{ne} \le 1.5 \\ \max\left(0.4, \frac{1.5}{R_{ne}}\right) & \text{if } R_{ne} > 1.5 \end{cases}$$

And $B_{\text{min}} = 25$ is the absolute safety floor to prevent excessive pruning.

### Performance Impact:
*   **Sparse Subgraphs ($R_{ne} \le 1.5$)**: $\Phi(R_{ne}) = 1.0 \implies B_{\text{eff}} = B_{\text{target}}$. The budget remains at its maximum limit, allowing full deep lookups.
*   **Dense Subgraphs ($R_{ne} = 3.0$)**: $\Phi(R_{ne}) = 0.5 \implies B_{\text{eff}} = 0.5 \cdot 120 = 60$. The budget is scaled down to 60 nodes, successfully containing the quadratic edge token growth.

---

## 3. Caching and Prefix Alignment

Spreading Activation's smooth energy propagation (§1) gives locally stable top-ranked nodes *for the query it was run on* — consecutive turns of the same conversation tend to keep the same top nodes near the top:

$$\text{Prefix}(S) \approx \text{Prefix}(S_{\text{prior}})$$

This is a property of Mechanism B (spreading activation) only; it says nothing about the separately-branched Personalized PageRank retrieval path (Mechanism A), since the two are selected by an exclusive branch and never combined (see `docs/arxiv_paper_graphgraph_2.0.md` §3).

The system's actual prompt-prefix-caching aid, **`render_stable_skeleton`** (`src/graphgraph/services/context.py`), is unrelated to either retrieval mechanism above: it renders the top-N nodes by **plain, unpersonalized, query-independent PageRank** (`graph.pagerank()`), so the same prefix is produced regardless of the current query or conversation turn. That query-independence — not spreading activation's stability — is what makes the prefix cacheable.

We do not currently have a benchmark measuring the resulting prompt-prefix cache hit rate against an LLM provider's prefix-caching discount, so no percentage savings figure is claimed here. If this is worth quantifying, it needs a dedicated benchmark comparing rendered-packet prefixes across consecutive queries against a real provider's cache-hit accounting.
