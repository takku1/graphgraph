# Comparative Analysis: Maximizing Context Graph Efficiency

This report presents a direct comparison of **traditional baselines** (Full Corpus, keyword BM25 RAG, and standard JSON graphs) against **our optimized configurations** (GG-LL and GG-SA Semantic Arrow) using real data gathered from the `graphgraph` benchmark suite on a codebase of 1,200 files/symbols (`medium_sparse`).

---

## 1. Head-to-Head Strategy Comparison (`medium_sparse`)

| Strategy | Type | Avg Tokens | Node Recall | Edge Recall | Irrelevant Ratio | Cost per 1M Queries | Token Reduction vs. Naive |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **`full_markdown`** | Naive Full Corpus | 89,591.0 | 1.000 | 1.000 | 0.996 | $13,438.65 | 1.0x (Floor) |
| **`bm25_markdown`** | Traditional RAG | 76.5 | 0.393 | 0.167 | 0.146 | $11.48 | 1,171.1x (Lossy) |
| **`graph_json` (estimated)** | Standard Graph | ~600.0 | 1.000 | 1.000 | 0.625 | $90.00 | ~150x |
| **`graph_2hop` (compact)** | Compressed Graph | 328.2 | 1.000 | 1.000 | 0.625 | $49.23 | 272.9x |
| **`graph_2hop_sql`** | SQL Table Graph | 354.3 | 1.000 | 1.000 | 0.625 | $53.15 | 252.8x |
| **`graph_2hop_semantic_arrow` (GG-SA)** | Attention-Aligned | **217.8** | **1.000** | **1.000** | **0.625** | **$32.67** | **411.3x** |
| **`graph_2hop_lowlevel` (GG-LL)** | Numeric Index | **195.8** | **1.000** | **1.000** | **0.625** | **$29.37** | **457.5x** |
| **`graph_2hop_gg_max` (GG-MAX)** | Mathematical Floor | **135.5** | **1.000** | **1.000** | **0.625** | **$20.33** | **661.2x** |

---

## 2. Key Insights from the Data

### A. The Failure of Keyword RAG (`bm25_markdown`)
Traditional vector/keyword RAG is incredibly cheap (**76.5 tokens**), but it is **highly lossy** for codebase structures. It fails to recover dependencies and blast radiuses:
*   **Node Recall is only 39.3%**.
*   **Edge Recall is only 16.7%**.
If a developer asks "What is the impact of changing the Database module?", BM25 only fetches text files containing the word "Database", missing the call chains completely.

### B. Graph RAG Solves Recall, but Standard Layouts Bloat
Constructing a 2-hop traversal solves the recall problem completely (**100% node and edge recall**). However, standard JSON or GraphML formats introduce massive token bloat:
*   Standard JSON repeats long string labels in edge definitions and uses verbose syntax.
*   Pretty-printed JSON for a 200-node graph takes **9,478 tokens** (relative overhead of **6.67x** compared to our sparse array floor).

### C. Maximizing Context: GG-LL vs. GG-SA
We pushed our system to the limit by creating two custom layouts that linearize the retrieved graph:

1.  **GG-LL (Numeric Index Floor - `graph_2hop_lowlevel`)**:
    *   *Tokens*: **195.8**.
    *   *Mechanism*: Compresses nodes and relations into numeric indices (`N1`, `1`) and outputs a CSV-like edge table (`N1,N2,1,0.94`).
    *   *Tradeoff*: Best token floor, but requires the LLM to perform attention hops to lookup what `N1` and `1` mean.
2.  **GG-SA (Semantic Arrow - `graph_2hop_semantic_arrow`)**:
    *   *Tokens*: **217.8** (only 11% more than GG-LL).
    *   *Mechanism*: Puts relationship verbs inline as directed arrows (`N1 -calls-> N2`).
    *   *Advantage*: Removes lookup overhead completely. The relationship verb (`calls`) is situated directly between the subject and object, matching the LLM's natural SVO language pre-training.

### D. The Mathematical Ceiling: GG-MAX (GG-MAX)
By mapping global node IDs (`N00001`) to local, sequentially assigned integers (`1`, `2`, `3`) starting from 1 for each query packet and stripping syntax markup (like XML tags and commas), we guarantee that node references consume exactly 1 token each.
*   **2-Hop GG-MAX (`graph_2hop_gg_max`)**:
    *   *Tokens*: **135.5** (30.8% reduction compared to GG-LL, and 37.8% reduction compared to GG-SA).
    *   *Mechanism*: Sequential local integer mapping, space-separated records (`src tgt rel wt`), no XML delimiters.
    *   *Advantage*: Reaches the absolute token floor for structural graph representation.
*   **1-Hop GG-MAX (`graph_1hop_gg_max`)**:
    *   *Tokens*: **56.7** (new Pareto frontier champion, beating `semantic_arrow`'s 74.5 tokens by 23.9%).

For **1-hop queries**, `semantic_arrow` actually **beats lowlevel** because it completely eliminates the header mapping section:
*   `graph_1hop_semantic_arrow`: **74.5 tokens** (Pareto Frontier Winner).
*   `graph_1hop_lowlevel`: **81.8 tokens**.

---

## 3. Visual Representation of Layout Architectures

```mermaid
graph TD
    subgraph Raw Source (Noisy, Verbose)
        A["Markdown Files (89.5k tokens)"]
    end

    subgraph Standard Graph RAG (Redundant)
        B["JSON / Graphify Schema (600+ tokens)"]
        B1["NODE AuthService [src=auth.py]"]
        B2["EDGE AuthService --contains--> TokenGen"]
    end

    subgraph GG-LL (Numeric Floor)
        C["GG-LL Index (195 tokens)"]
        C1["Map: 1:calls, N1:AuthService"]
        C2["Edges: N1,N2,1"]
    end

    subgraph GG-SA (Attention-Aligned)
        D["GG-SA Arrow (217 tokens)"]
        D1["Nodes: N1: AuthService"]
        D2["Edges: N1 -calls-> N2"]
    end

    A --> B
    B --> C
    B --> D
```

---

## 4. Next Steps for Pushing the System Further

To push the context graph to its absolute limits, we should address the remaining gaps:

1.  **Live Prompt Caching Optimization**:
    Place the static node lookup dictionary in the developer prefix so that it stays in the LLM's prompt cache. This reduces the *active billing token footprint* of a 2-hop packet down to **~100 tokens** per query, as the cached prefix is charged at a 90% discount.
2.  **Hybrid Fact Injection (GG-Hybrid)**:
    Pure topology graphs miss textual context (e.g. details of *how* a function behaves). We should implement an adaptive strategy where nodes identified as "critical hotspots" have their facts/summaries appended inline, while standard nodes remain topology-only.
3.  **Integrate Semantic Arrows into the indexing pipeline**:
    Port the `@nodes` / `@edges` `semantic_arrow` renderer directly into `graphify` so that live agents receive this optimized format instead of verbose node/edge text.
