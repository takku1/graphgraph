# GraphGraph Algorithmic & Mathematical Formulations

This document specifies the mathematical formulations and parameters of the algorithms **currently implemented and running** in the `graphgraph` production codebase.

---

## 📈 1. Personalized PageRank (PPR) Centrality

For query-specific lexical matching nodes, GraphGraph runs Personalized PageRank to rank topological centrality. 

### Formulation:
In iteration step $k$ for node $i$, the PageRank score $PR_i^{(k+1)}$ is computed as:

$$PR_i^{(k+1)} = (1 - d) \cdot p_i + d \sum_{j \in in(i)} PR_j^{(k)} \cdot \frac{W_{j,i}}{O_j} + d \left( \sum_{m \in Dangling} PR_m^{(k)} \right) \cdot p_i$$

Where:
* **$d$**: The damping factor (default $0.85$).
* **$p_i$**: The personalization teleportation probability for node $i$.
  * If a query personalization vector is provided: $p_i = \frac{\text{personalization}(i)}{\sum_k \text{personalization}(k)}$.
  * Otherwise, uniform: $p_i = \frac{1}{N}$.
* **$W_{j,i}$**: Edge weight of $j \rightarrow i$ scaled by traversal type: $W_{j,i} = \text{weight} \cdot \text{traversal\_strength}(type_{j,i})$.
* **$O_j$**: Outgoing sum of node $j$: $O_j = \sum_{t \in out(j)} W_{j,t}$.
* **$Dangling$**: The subset of active nodes with no outgoing edges ($O_j = 0$).

---

## 🎛️ 2. Continuous KKT Lagrangian Budget Planner

Determines the optimal node budget $n^*$ to trade off marginal token expansion costs against context relevance.

### Optimization Formulation:
We solve for the stationary point $n^*$ under the continuous Karush-Kuhn-Tucker (KKT) conditions:

$$n^* = \frac{1}{\lambda} \ln \left( \frac{\beta \cdot \lambda}{\alpha \cdot \tau} \right)$$

Where:
* **$\lambda$**: The complexity constant mapping target evidence distribution per query class:
  * `direct_lookup` / `reverse_lookup` $\rightarrow \lambda = 0.08$ (focused targets)
  * `multi_hop_path` $\rightarrow \lambda = 0.05$
  * `blast_radius` / `subsystem_summary` $\rightarrow \lambda = 0.035$ (distributed targets)
* **$\tau$**: The marginal token cost per node derived from empirical edge density:
  $$\tau = 1.496 + 6.215 \cdot \text{adjusted\_edge\_density}$$
* **$\beta$**: Target scaling multiplier ($10000.0$).
* **$\alpha$**: Lagrangian multiplier ($1.0$).
* **Bounds enforcement**: The raw $n^*$ is clipped against class-specific bounds:
  $$n_{\text{final}} = \min\left(B_{\text{upper}}, \max\left(B_{\text{lower}}, n^*\right)\right)$$

---

## 📊 3. Relation-Shaped Edge Budgeting

Allocates edge quotas to different relation types in dense subgraphs to prevent repetitive linkages (e.g. `references` or `links` details) from crowding out structural context.

### Quota Allocation:
For a total target limit of weak edges $T$, the quota for relation type $r$ is:

$$\text{quota}_r = \text{floor}\left( T \cdot \frac{\text{weighted}_r}{\sum_k \text{weighted}_k} \right)$$

Where the weight of relation $r$ is a function of its frequency $C_r$ and mean utility:

$$\text{weighted}_r = \sqrt{C_r} \cdot \text{traversal\_strength}(r) \cdot \frac{\sum_{e \in E_r} \text{utility}(e)}{C_r}$$

$$\text{utility}(e) = \text{confidence}(e) \cdot \text{provenance\_confidence}(\text{prov}_e) \cdot \max(0.05, W_e)$$

### Edge Ranking:
Within each relation type, individual edges are selected by ranking their joint utility and endpoint diversity:

$$\text{edge\_utility}(e) = \text{traversal\_strength}(r) \cdot \text{confidence}(e) \cdot \text{weight}(e) \cdot \frac{1}{\sqrt{1 + \text{deg}(u) + \text{deg}(v)}}$$

Where $\text{deg}(u)$ and $\text{deg}(v)$ are the current endpoint degrees in the selected edge list, penalizing repetitive fans.

---

## 🌀 4. Traversal Hub Invalidation & Propagation Decay

To prevent massive structural hub nodes (such as generic framework imports) from flooding the traversal, BFS paths undergo dynamic hub-penalization.

### Path Energy Decay:
At hub node $h$, path propagation energy decays by:

$$\Delta E = \text{resistance} \cdot \sqrt{\text{out\_degree}(h)} \cdot 25.0$$

$$E_{\text{next}} = E_{\text{current}} - \Delta E$$

If $E_{\text{next}} \le 0$, traversal stops along that path.

---

## 🕰️ 5. Conversational Activation Decay

To retain short-term conversational context across dialogue turns without unbounded expansion:

$$\text{Activation}_i^{(t+1)} = \gamma \cdot \text{Activation}_i^{(t)}$$

Where:
* **$\gamma$**: Temporal context decay factor (default $0.6$).
* **$\text{Activation}_i^{(t)}$**: Activation score of node $i$ at turn $t$.
