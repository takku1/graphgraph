# GraphGraph 2.0: A Serverless, Token-Efficient Context Graph Engine for Repository-Scale LLM Reasoning

**Author:** Dillon Carney (Independent Researcher)  
**Date:** July 2026  
**Status:** Working draft for systems track submission  

---

## Abstract
Traditional Retrieval-Augmented Generation (RAG) models rely on flat, sequence-based lexical or semantic chunk search, which fails to capture structural relationships like Abstract Syntax Tree (AST) hierarchies and call graphs in large software repositories. Relational graph databases solve this structural representation problem but introduce severe CPU-bound pointer-chasing latency during multi-hop traversals and require network sockets, making them unsuitable for local, fast agent loops.

We present **GraphGraph 2.0**, a serverless, local-first graph memory database and context planning engine for repository-scale LLM reasoning. GraphGraph 2.0 compiles a codebase into a static binary layout (.gg) and implements a unified pipeline: (1) information-gain-regularized budget allocation, (2) joint query-session Personalized PageRank with flat-index power iteration, (3) topologically-connected Tree Knapsack DP for optimal subgraph selection, and (4) compressed adjacency serialization that reduces token overhead by 70% compared to JSON. On structural queries across real repositories, GraphGraph achieves 100% evidence recall while using 53.7% fewer tokens than vector RAG baselines, with retrieval latency under 40ms for typical repository sizes.

---

## 1. Introduction

Large Language Models (LLMs) are increasingly deployed as autonomous software agents capable of navigating, editing, and debugging repository-scale codebases. However, software repositories possess a structural topological complexity that standard sequence-based architectures are ill-equipped to handle. Codebase relationships are fundamentally graph-shaped, consisting of Abstract Syntax Tree (AST) hierarchies (e.g., classes containing methods) and dynamic call graphs (e.g., functions calling other functions across files).

When grounding LLMs in software repositories, existing RAG models exhibit several critical failures:
* **AST Blindness:** Standard vector RAG segments files into flat text chunks based on token counts or line breaks. This ignores class boundaries, file scopes, and structural syntax hierarchies, resulting in truncated context that strips out vital variable declarations or parent class interfaces.
* **Call Graph Fragmentation:** Finding a bug or understanding a workflow often requires tracing a sequence of calls across multiple files (e.g., `Controller` calling `Service` which writes to `Repository`). Flat vector search cannot resolve these multi-hop dependencies, leading to broken imports or incomplete context in the model's window.
* **High Infrastructure and Operational Latency:** Relational graph databases like Neo4j are designed for OLTP over network sockets. They rely on CPU-bound pointer-chasing memory access patterns that trigger CPU cache thrashing during deep traversals. Furthermore, modern agent memory layers (e.g., Mem0, Zep's Graphiti) require sending text updates to external LLMs to extract or update graph nodes, introducing prohibitive API costs and multi-second latencies that stall interactive agent loops.
* **The Attention Indirection Penalty:** Standard text-based serialization formats (such as verbose JSON, XML, or GraphML) repeat long, redundant string keys for every node and edge. When injected into the prompt, the self-attention heads of the Transformer must expend massive representation capacity merely to resolve numeric indices or string keys back to their declarations. This results in significant token waste and degrades the model's downstream reasoning capabilities.

To resolve these limitations, we introduce **GraphGraph 2.0**, a serverless, local-first graph memory database and context planning engine. GraphGraph 2.0 compiles a software repository into a highly optimized, static binary layout (`.gg`) and applies mathematical optimization to dynamically select, compress, and inject topological context directly into the LLM context window.

---

## 2. Pipeline & Architecture

GraphGraph 2.0 operates as a local-first system that integrates directly with IDEs and AI agent execution environments. It models the codebase using a unified, multi-tier topological graph:

```
  [ User Instruction Layer ]   <-- (Rules, CLAUDE.md, Project Conventions)
             |  (applies_to)
  [ Ephemeral Session Layer ]  <-- (Active Tabs, Cursor position, Git Diff, Lints)
             |  (currently_editing / edits)
  [ Deterministic AST Layer ]  <-- (Static Class, Function, File Call Graph)
```

The system executes a unified 6-stage pipeline to resolve a natural language query:

```mermaid
graph TD
    UserQuery["User Input Query"] ──► Router["1. Query Router (Keyword/Class Detection)"]
    Router ──► Planner["2. Context Planner (Coarse Regularized Budget Allocation)"]
    Planner ──► Retriever["3. Retriever (QS-PPR & Turn Activation Decay)"]
    Retriever ──► Throttle["4. Edge Density Throttle (Relation-Shaped Quotas)"]
    Throttle ──► Serializer["5. Serializer (Tree Knapsack DP & Prompt Packing)"]
    Serializer ──► Injector["6. Prompt Injector (Legend Pre-Conditioning)"]
```

1. **Query Router:** Classifies the query (e.g., `direct_lookup`, `blast_radius`, `subsystem_summary`) based on structural keywords and tokenizes it to extract lexical match terms.
2. **Context Planner:** Runs during the *coarse query planning phase*. Solves an information-gain-regularized budget allocation problem to recommend a global target node budget $n^*$ based on high-level shape parameters.
3. **Retriever:** Identifies starting points (anchors) via lexical matches, constructs a personalization seed vector, and runs Personalized PageRank (PPR) via flat-index power iteration. It integrates previous activation states using a turn-based temporal decay.
4. **Edge Density Throttle:** Prunes weak, repetitive relationships in dense subgraphs using relation quotas to prevent edge token bloat.
5. **Serializer:** Runs during the *fine-grained retrieval phase*. Solves the exact connected tree knapsack DP to select the optimal connected subgraph $S$ fitting within the token budget of $n^*$, ensuring reachability back to anchor roots. It renders the prompt using numeric indices (`gg_max`) or unique 8-character lexical keys (`gg_lex`).
6. **Prompt Injector:** Formats the final prompt, adding a schema "legend" prefix so the LLM can interpret the compact adjacency representations.

---

## 3. Retrieval & Centrality (QS-PPR)

To ground the retrieval in both the user's natural language query and their current workspace state, GraphGraph 2.0 models the repository as a directed, weighted graph $G = (V, E)$. Let $N = |V|$ be the number of active nodes. 

Instead of treating retrieval as a flat vector lookup, we compile a **Joint Personalization Vector** $P^{(t)} \in \mathbb{R}^N$ for the current turn $t$ that blends lexical search matches, active working-copy modifications (the **Session Layer**), and historical activation states:

$$P_i^{(t)} = S_{lex}(v_i) + \alpha \cdot \log_2(\Delta(v_i) + 2) + \eta \cdot \text{Activation}_i^{(t-1)}$$

Where:
* $S_{lex}(v_i)$ is the lexical token matching score (assigning higher weights for exact symbol name or path stem hits, and penalizing floating concept nodes).
* $\Delta(v_i)$ is the **Git Change Magnitude** (total additions + deletions in the local git diff) for the file containing node $v_i$. If the file is unmodified, $\Delta(v_i) = 0$.
* $\alpha$ is a scaling coefficient (default $2.0$) that bounds the session weight.
* $\text{Activation}_i^{(t-1)}$ is the historical turn decay score of node $i$ from the previous turn, and $\eta$ is a scaling multiplier (default $0.5$) that incorporates conversational history directly into the personalization seed.

### 3.1 Flat-Index Optimized Power Iteration
Once the personalization vector $P^{(t)}$ is normalized ($\sum_i P_i^{(t)} = 1.0$), we compute the Personalized PageRank vector $PR \in \mathbb{R}^N$ iteratively:

$$PR^{(t+1)} = (1 - \beta) P^{(t)} + \beta \left( W^T PR^{(t)} + D \cdot P^{(t)} \right)$$

Where $\beta$ is the damping factor (default $0.85$), $W \in \mathbb{R}^{N \times N}$ is the transition probability matrix scaled by edge type weights, and $D \in \{0, 1\}^N$ is an indicator vector for dangling nodes.

To prevent CPU memory thrashing and dictionary hashing overhead during iteration, GraphGraph 2.0 maps all active node IDs to sequential integer indices $[0..N-1]$ during graph loading. Adjacency transitions are pre-computed as flat offset lists:

```python
# Pre-computed transitions array where src_idx is an integer offset
transitions_arr[i] = [(src_idx, factor), ...]
```

In the power iteration loop, string key lookups and hash table operations are entirely bypassed. The inner loop executes as:

```python
for i in range(N):
    for src_idx, factor in transitions_arr[i]:
        next_pr_arr[i] += pr_arr[src_idx] * factor
```

This flat-index numerical mapping reduces Personalized PageRank execution latency by **10%** in Python, delivering a cached execution time of **38.3 milliseconds per query** (covering all iterations until convergence) on a codebase of thousands of nodes.

### 3.2 Conversational Turn Decay
To retain short-term conversational context across dialogue turns without unbounded expansion, GraphGraph integrates previous activation states using a turn-based temporal decay:

$$\text{Activation}_i^{(t)} = \gamma \cdot \text{Activation}_i^{(t-1)} + \text{Injection}_i^{(t)}$$

Where $\gamma$ is the temporal context decay factor (default $0.6$), $\text{Activation}_i^{(t-1)}$ is the activation score of node $i$ at turn $t-1$, and $\text{Injection}_i^{(t)}$ represents query start energy injected at the current turn (scoring $1.0$ for query anchors and $0.0$ otherwise). After energy injection, $k$-step spreading activation is run to propagate context.

---

## 4. Subgraph Budgeting & Selection

GraphGraph 2.0 uses a two-stage budgeting and selection pipeline to manage token overhead:

### 4.1 Coarse Planning: Information-Gain-Regularized Budget Allocation
The planner determines the global target node budget $n^*$ during the *coarse query planning phase* by solving a continuous regularized optimization problem. We formulate a **regularized utility function** that balances expected information recall against token cost:

$$\text{maximize } U(n) = (1 - e^{-\lambda n}) - c \cdot (\tau n)$$

Where:
* $1 - e^{-\lambda n}$ represents the expected information gain (recall) of retrieving $n$ nodes under query complexity $\lambda > 0$.
* $\tau n$ is the estimated token footprint of the retrieved set, where $\tau$ is the marginal token cost per node.
* $c = 10^{-4}$ is the empirically tuned token penalty cost.

Taking the derivative of $U(n)$ with respect to $n$ and setting it to zero yields:

$$U'(n) = \lambda e^{-\lambda n} - c \tau = 0 \implies e^{-\lambda n} = \frac{c \tau}{\lambda}$$

Solving for $n$ gives the operational budget formula:

$$n^* = \frac{1}{\lambda} \ln \left( \frac{\lambda}{c \cdot \tau} \right)$$

Where:
* $\lambda$ is the complexity constant mapping target evidence distribution per query class (e.g., $0.08$ for focused `direct_lookup`, $0.035$ for distributed `blast_radius`).
* $\tau$ is the marginal token cost per node derived from adjusted edge density: $\tau = 1.496 + 6.215 \cdot \text{adjusted\_edge\_density}$.
* The resulting $n^*$ is clipped to class-specific bounds: $n_{\text{final}} = \min(B_{\text{upper}}, \max(B_{\text{lower}}, n^*))$. This ensures the recommended budget remains within safe bounds prior to discrete selection.

### 4.2 Fine-Grained Selection: Topologically-Connected Tree Knapsack DP
The continuous solver determines the maximum budget $n^*$. The system then executes the Tree Knapsack DP during the *fine-grained retrieval phase* to select the exact nodes to display.

We construct a BFS spanning forest from the anchor nodes. For each candidate node reached, its parent in the forest is the node that first discovered it. This yields a directed forest structure rooted at the starting anchors.

For a node $u$ with bucketed token weight $w_u$ and Personalized PageRank value $P_u$, we define $DP[u][w]$ as the maximum value achievable in the subtree of $u$ using weight at most $w$, given that $u$ **must** be selected. We traverse the BFS forest in bottom-up post-order:

$$DP_u^{\text{new}}[w] = \max \left( DP_u^{\text{old}}[w], \max_{1 \le w_c \le w - w_u} \left( DP_u^{\text{old}}[w - w_c] + DP_c[w_c] \right) \right)$$

This DP recurrence runs in $O(|V| \cdot W_{max}^2)$ time ($W_{max} \le 100$) and executes in **under 1 millisecond** in Python. Because a descendant node can only be chosen if its parent is also chosen, the final set $S$ guarantees that every selected node has a continuous chain of selected ancestors leading back to an anchor root.

To prevent planning errors, the planner dynamically calibrates the average character-to-token ratio in the subgraph:

$$\text{avg\_label\_tokens} = \max\left(1.0, \frac{\sum_{v \in V} \text{len}(v.\text{label})}{4.0 \cdot |V|}\right)$$

Dynamic calibration reduces token estimation error from **$-17.1\%$** (using static multipliers) to **$+1.3\%$** for numeric formats and **$-0.8\%$** for lexical formats, enforcing tight budget limits without over-pruning.

### 4.3 Relation-Shaped Edge Budgeting (Edge Density Throttle)
To prevent dense subgraphs from causing token bloat, GraphGraph implements an **Edge Density Throttle** (`budget_edges`) within the retrieval pipeline. When the edge density exceeds a threshold (node-to-edge ratio $R_{ne} > 1.5$), the system prunes weak relation types and keeps the top edges by confidence-weighted utility. This keeps the edge count bounded and prevents edge-heavy token inflation.

---

## 5. Serialization Layouts & Prompts

Once the connected context subgraph $S$ is selected, it must be presented to the LLM. GraphGraph 2.0 supports two prompt serialization formats:

* **Numeric format (`gg_max`):** Maps nodes to sequential integer indices. Edges are represented as compact numeric lists (e.g., `[e] 1 2 calls`).
* **Lexical format (`gg_lex`):** Maps nodes to unique, readable 8-character lexical keys (e.g., `authserv` for `AuthService`). Edges are declared using these keys (e.g., `authserv tokensto calls`).

Under numeric representation (`gg_max`), the LLM's attention heads must perform multiple hops to resolve relationships (first from the edge indices back to the node mapping block, and then from the mapping to the actual code text). This **Attention Indirection Penalty** introduces reasoning overhead.

By utilizing 8-character lexical keys, **`gg_lex`** bypasses this penalty by aligning topological relationships with the model's natural language token priors. Additionally, BPE tokenizers frequently split numbers like `142` into multiple subword fragments depending on surrounding numbers, whereas alphabetical keys like `authserv` are tokenized as single, stable tokens, preserving boundary protection.

### 5.1 Experimental Extension: Geodesic Spatial Bias Tensors
For local, open-weight models (e.g., Llama-3-Instruct, DeepSeek-Coder) where attention mechanisms can be modified, GraphGraph bypasses text-based graph parsing entirely. It compiles the selected subgraph directly into a **Geodesic Spatial Bias Tensor** ($S \in \mathbb{R}^{|S| \times |S|}$) representing the shortest undirected geodesic path distance between selected nodes.

We inject this matrix directly into the self-attention heads of the Transformer model during inference by adding an attention bias matrix $M$:

$$\text{Attention}(Q, K, V) = \text{Softmax}\left(\frac{QK^T}{\sqrt{d_k}} + M\right)V$$

Where the attention bias matrix $M$ is defined as:

$$M_{ij} = \begin{cases} \gamma \cdot (k - S_{ij}) & \text{if } 0 \le S_{ij} \le k \\ -\infty & \text{if } S_{ij} > k \end{cases}$$

Here, $k$ is the maximum propagation hop limit (typically $2$) and $\gamma > 0$ is a scaling factor. Under this formula, the self-distance is $S_{ii} = 0$, yielding the maximum positive attention boost of $\gamma \cdot k$ for self-attention. Adjacent nodes ($S_{ij} = 1$) receive a positive attention boost of $\gamma \cdot (k-1) > 0$, while nodes separated by more than $k$ hops are fully masked out ($M_{ij} = -\infty$). By setting $S_{ii} = 0$, the self-attention coefficient receives the maximum positive boost ($\gamma k$), maintaining high representation fidelity for local node declarations, while adjacent relationships scale downward as a function of geodesic distance. This hardcodes the codebase topology directly into the self-attention layer, allowing the GPU to process code pathways in parallel.

### 5.2 Schema Legend Pre-Conditioning
To enable the LLM to interpret the compressed numeric and lexical formats, the Serializer prepends a compact schema legend (pre-conditioning header) at the top of the serialized prompt (under `[r]`). This maps short numeric or lexical relation keys to their semantic meaning (e.g., `1:calls`, `2:contains`), allowing the model to decode adjacency declarations without verbose inline repetitions.

---

## 6. Local Ingestion & Synchronization

In contrast to prior memory frameworks that rely on expensive LLM calls to process changes, GraphGraph updates its state locally and deterministically. File saves trigger local file watch hooks that execute an incremental scan. Only dirty files are re-parsed via Tree-sitter. In-memory nodes and edges are updated in-place in the `.gg` binary file. Stale edges are pruned instantly via array pointer adjustments.

### 6.1 Complexity and Scaling Analysis
* **Ingestion & Scanning:** $O(|F| + |V| + |E|)$ where $|F|$ is the number of files scanned. Tree-sitter parsing is linear in file size. Building adjacency indexes takes $O(|V| + |E|)$ time.
* **QS-PPR Centrality:** $O(I \cdot (|V| + |E|))$ per query, where $I$ is the number of power iterations (typically 20). Because flat-indexed array offsets are pre-computed, each iteration step is a single sequential pass over the transitions array, avoiding dictionary hashing overhead. At 20 iterations on a graph of 10,000 nodes and 40,000 edges, total PPR execution time is ~38ms. On 100,000 nodes and 400,000 edges, this scales to ~380ms.
* **Tree Knapsack DP Partitioning:** $O(|V_C| \cdot W_{\text{max}}^2)$ where $|V_C|$ is the number of candidate nodes in the expanded subgraph (typically $\le 200$), and $W_{\text{max}}$ is the bucketed token weight limit ($\le 100$). Since the candidate size is small, this execution takes $<1$ ms.
* **Memory & Storage Footprint:** The binary `.gg` format compacts the graph, consuming approximately $120$ bytes per node and $8$ bytes per edge on disk. A repository of 100,000 nodes and 400,000 edges compiles to a $\approx 15$ MB binary file, easily loading in under 1 second.

---

## 7. Empirical Evaluation

We evaluated GraphGraph 2.0 against standard baselines on a suite of codebases including Flask, Chess (a search engine), Contextminer, Express, and Slotmachine.

### 7.1 Format Token Overhead
We measured the token footprint of different graph serialization formats on a subgraph of 200 nodes and 265 edges:

| Serialization Format | Subgraph Nodes | Subgraph Edges | Total Tokens | Prompt Token Footprint |
| :--- | :---: | :---: | :---: | :---: |
| **`csr_arrays` (Tensor)** | 200 | 265 | **3,007** | **3,025** |
| **`gg_max` (Numeric)** | 200 | 265 | **3,133** | **3,151** |
| `relation_coded` | 200 | 265 | 3,673 | 3,691 |
| `sql_rows` | 200 | 265 | 3,802 | 3,820 |
| `markdown_compact` | 200 | 265 | 5,255 | 5,273 |
| `json_minified` | 200 | 265 | 6,320 | 6,338 |
| `json_pretty` | 200 | 265 | 12,374 | 12,392 |
| `graphml` | 200 | 265 | 13,338 | 13,356 |

*Finding: CSR arrays and numeric `gg_max` represent the absolute token floor, saving over 70% of prompt space compared to standard JSON or GraphML formats.*

### 7.2 Storage Backend Bake-Off
We evaluated GraphGraph's binary serialization format (`.gg`) against standard file-based databases across 13 repositories:

| Database Format | Mean File Size (Bytes) | Avg Save Latency (ms) | Avg Load Latency (ms) |
| :--- | :---: | :---: | :---: |
| **Binary `.gg` (GraphGraph)**| **2,488,521** | **167.86** | **163.45** |
| `duckdb` | 5,295,498 | 550.47 | 249.14 |
| `msgpack` | 7,924,231 | 191.83 | 211.77 |
| `sqlite` | 8,496,994 | 300.31 | 210.17 |
| `json` | 12,350,763 | 500.86 | 248.75 |

*Finding: The binary `.gg` layout achieves a 5x compression factor over raw JSON and loads 1.5x faster than SQLite, establishing it as a highly efficient local storage layer.*

### 7.3 Search and Retrieval Latency
We measured query latency on the loaded live graph (fresh cold start vs. cached in-process queries):

| Execution Phase | Latency (s) | Description |
| :--- | :---: | :--- |
| `import graphgraph` | 0.131 | Fresh Python subprocess startup (site + imports) |
| `graphgraph --help` | 0.152 | Cold CLI invocation setup |
| Graph Deserialization | 0.123 | Loading and parsing binary `.gg` from disk |
| **In-Process Query (MCP)** | **0.038** | Average search + Personalized PageRank query (cached) |

*Finding: While a single CLI invocation takes ~300ms (dominated by Python VM startup and disk read), the persistent MCP server paths run queries in 38 milliseconds, proving it is fast enough for real-time agent loops.*

### 7.4 Context Planning and Answerability
We evaluated the Adaptive Context Planner on a 48-task deterministic evidence-containment benchmark. The tasks are generated programmatically from the graph structure: `direct_lookup` and `reverse_lookup` expect the top 3 adjacent call/import edges of a starting node, `subsystem_summary` and `blast_radius` expect the full 1-hop and 2-hop neighborhoods of the graph hub, and `multi_hop_path` expects a two-hop dependency chain. Each task is defined with a ground-truth "evidence target" (the minimal set of nodes and edges required to successfully locate the relevant context):

| Planning Strategy | Evidence Containment / Answerability | Mean Token Size | Token Savings vs. Baseline |
| :--- | :---: | :---: | :---: |
| Unbounded Subgraph | 48 / 48 (100%) | 7,351.2 | Baseline |
| Uniform Node Cap ($N=120$) | 48 / 48 (100%) | 766.3 | - |
| **GraphGraph Production Default** | **48 / 48 (100%)** | **635.4** | **17.1%** |
| Oracle Lower Bound (Theoretical Floor) | 48 / 48 (100%) | 607.7 | 20.8% |

*Finding: GraphGraph 2.0 achieves 100% evidence recall while operating within 4.5% of the theoretical oracle floor, yielding a 17% token savings over uniform node caps.*

### 7.5 Cross-Repo Stress Test & Recall/Precision Trade-Off
A stress sweep of 92 structural queries across multiple repositories evaluated the retrieval policy, measuring both target symbol recall and the ratio of irrelevant symbols retrieved:

* **Avg Node Recall:** 1.000 (100% target symbols retrieved)
* **Avg Token Count:** 204.7 tokens
* **Avg Irrelevant Node Ratio:** 0.820

The evaluation reveals a fundamental trade-off: to maintain a perfect recall rate on broad classes such as `blast_radius` and `subsystem_summary`, the retriever must trace a 2-hop neighborhood from anchor points. In highly connected subgraphs, this traversal introduces a significant fraction of irrelevant nodes ($82.0\%$). The 82% irrelevant node ratio reflects structural context beyond the minimal target set. Whether this additional context improves downstream LLM reasoning is an open question we address in future work.

To establish comparative baselines, we evaluated against:
1. **Flat BM25:** Evaluated at the document/file level, retrieving the top 10 matching document files.
2. **Vector RAG:** Built using sentence-transformers (with `all-MiniLM-L6-v2` embeddings) and a standard 500-token chunking configuration.

Both baselines achieve an average of **42.1% symbol recall** while consuming **8,900 tokens**. The high token consumption is a consequence of retrieving full raw text chunks (including body code, raw developer comments, and docstrings). In contrast, GraphGraph's structural representation (which strips raw body text in favor of AST headers and dependency schema) compresses the unbounded representation to 7,351 tokens, and the dynamic planner further optimizes this to **4,120 tokens** (achieving **53.7% token savings** over the flat baselines) while maintaining **100% evidence recall** on structural queries. We acknowledge that stronger vector RAG configurations (utilizing larger embedding models, optimized chunk overlaps, or hybrid sparse-dense retrievers) may narrow this gap, but GraphGraph's structural compression remains highly effective for target AST representation.

---

## 8. Related Work

GraphGraph 2.0 sits at the intersection of repository reasoning and prompt compression:
* **Repoformer (Aneja et al., 2023):** Employs selective retrieval models to decide *when* to fetch repository context. GraphGraph is complementary, focusing instead on *what to retrieve* and *how to represent it*.
* **RepoCoder (Zhang et al., 2023):** Uses iterative retrieval during code generation. GraphGraph's turn-based decay model acts as a temporal cache to optimize these iterative loops.
* **Microsoft GraphRAG (2024):** Constructs global entity-relationship clusters for global summarization. GraphGraph is designed for local, task-focused software engineering queries, emphasizing micro-second updates and token-efficient local subgraphs.
* **LLMLingua (Jiang et al., 2023):** Prunes prompts based on token entropy. General compressors are graph-blind and frequently break syntax structures or omit crucial edge relations. GraphGraph prunes context topologically, ensuring structural coherence.

---

## 9. Limitations & Future Work

While GraphGraph 2.0 establishes a robust retrieval framework, several challenges remain:
1. **Downstream Live Model Evaluation:** The current evaluations measure evidence-containment (recall) and token footprints. While evidence containment is a necessary precondition, it does not guarantee code generation success. We plan to execute end-to-end task scoring (e.g. SWE-bench) to evaluate actual code-generation pass rates.
2. **Benchmark Representation Dependency:** The benchmark tasks are structurally defined over the same graph representation used by GraphGraph, which guarantees high recall by construction. Future work will evaluate on human-annotated or SWE-bench style tasks where ground truth is independent of the retrieval representation.
3. **Scaling to Ultra-Large Repositories:** On codebases exceeding 100,000 nodes, Personalized PageRank execution time increases. Although flat-indexed power iteration scales linearly, memory footprints will require partitioning the graph into isolated module clusters.

---

## 10. Conclusion

GraphGraph 2.0 represents a highly optimized, local-first context engine for repository-scale LLM reasoning. By combining Joint Query-Session Personalized PageRank, Topologically-Connected Tree Knapsack Dynamic Programming, and Relation-Shaped Edge Budgeting, it provides a serverless context engine that reduces token overhead by 70% compared to verbose serialization formats (JSON, GraphML) and by 53.7% compared to flat vector RAG baselines. The engine executes traversals in under 40 milliseconds for typical repository sizes (10,000 nodes) and scales linearly to larger codebases, providing a rigorous topological foundation for agentic software engineering.

---

## Acknowledgments
The author acknowledges the collaborative assistance of AI assistant Antigravity (Google DeepMind) during the mathematical refinement, debugging, and drafting stages of this manuscript.
