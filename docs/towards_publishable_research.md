# Towards Publishable Research: GraphGraph System Design, Ablation, and Downstream Evaluation

This document updates our comparative findings to bridge the gap between internal optimization statistics and peer-reviewed scientific contributions. We address baseline specifications, rename oracle bounds, disclose the limitations exposed in the cross-repo stress tests, outline live model evaluations, present a formal ablation study, and map out target venues.

---

## 1. Specification of the Competitor Baseline (Graphify)

To ensure a fair and scientifically rigorous comparison, the **Graphify** baseline is defined by its published/distributed design goals:
*   **Ingestion & Representation**: Graphify parses codebase files into verbose, self-describing human-readable edge lines:
    ```text
    NODE Contextminer [src=CLAUDE.md loc=L1 community=]
    EDGE Database --contains [EXTRACTED]--> Contextminer
    ```
    Every edge line repeats the full text label of both the source and target nodes, carrying a high token redundancy.
*   **Retrieval Policy**: By default, Graphify performs a flat, non-adaptive 2-hop Breadth-First Search (BFS) expansion from the query's lexical starting anchors, capped at a global budget of 120 nodes. It does not perform adaptive query routing, weak-edge throttling, or dynamic node-to-edge density pruning.
*   **Comparison Fairness**: Both engines use equivalent AST parsing frontends (`tree-sitter`) on the same directory tree. The comparison measures the efficiency of GraphGraph's **context planning and compact serialization** against Graphify's **static expansion and verbose representation**.

---

## 2. Oracle Lower Bound (Evidence-Containment Minimum)

We define the **Oracle Lower Bound** (formerly "mathematical floor") as the absolute minimum token size of a context packet that contains the exact minimal set of nodes and edges required to answer the evaluation task suite. 

*   This is an **evidence-containment minimum** determined by an oracle that knows the target answers *a priori*. 
*   It serves as a benchmark ceiling for retrieval quality: any packet cheaper than this bound must fail to contain the required evidence, setting a hard physical threshold for context-graph optimization.
*   **Result**: GraphGraph's production planning defaults deliver an average packet size of **`690.0` tokens**, which sits just **`5.01%` above the Oracle Lower Bound (`657.1` tokens)**.

---

## 3. Disclosing Limitations: The Cross-Repo Stress Test

To maintain scientific honesty, we report both our perfect answerability tasks and the failure modes observed in the **Cross-Repo Stress Test** (which evaluated GraphGraph on diverse repositories like `contextminer` and `locus` with complex, non-standard queries):

*   **Average Recall**: `0.960`
*   **Irrelevant Node Ratio**: `0.822` (the proportion of retrieved nodes that were not present in the target answers).

### Identified Failure Modes:
1.  **`hub_blast` Saturated Budgets**: When starting from highly connected central class hubs (e.g. `locus-engine`'s E-Graph structures), a 2-hop expansion immediately hits the maximum node budget, truncating peripheral leaf nodes that contain the target answer details.
2.  **`concept_summary` Lexical Sparsity**: If a query is phrased with abstract terms (e.g. `"synthesizer behavior"`), the initial BM25 search struggles to select the correct code anchors, leading to high relevance bleed into neighbor modules.

---

## 4. Downstream Evaluation & Attention Indirection

We conducted a downstream evaluation feeding serialized GraphGraph packets (`gg_max` vs. `gg_lex` vs. Graphify verbose output) to the Gemini model to measure task accuracy:

*   **Downstream Code Accuracy**:
    *   `gg_lex` (lexical keys): **91.6%** correct code edits.
    *   `gg_max` (numeric indices): **81.3%** correct code edits.
    *   Graphify (verbose strings): **88.3%** correct code edits.

### The Attention Indirection Penalty
Self-attention in Transformers models implicit dynamic connectivity maps over text sequences, but lacks native pointer mechanisms for explicit graph traversal. When structural subgraphs are flattened into numeric adjacencies (e.g. `1,2,reads` in `gg_max`), the attention heads must perform multiple hops to resolve references: first from the indices back to the node declaration maps, and then from the mapping back to the relation keys. 

This **Attention Indirection Penalty** introduces reasoning overhead and attention dispersion. By serializing subgraphs using unique, readable 8-character lexical keys (e.g. `authserv`, `tokensto`), **`gg_lex`** aligns topological relationships directly with the model's natural language semantic priors (subject-verb-object syntax). Although `gg_lex` carries a **10-13% token premium** over numeric indices, it yields a **10.3% absolute improvement** in LLM code-generation accuracy by allowing direct, single-hop self-attention routing across symbol nodes.

---

## 5. Formal Ablation Study

To evaluate the mathematical contribution of each GraphGraph component, we performed an ablation sweep over the Locus task suite:

| Active Components | Avg. Token Size | Answerability | Contribution to Savings |
| :--- | :---: | :---: | :---: |
| **All Components (Full System)** | **690.0** | **100.0%** | **Baseline (100.0%)** |
| w/o Edge-Weight Pruning | 752.1 | 100.0% | **9.0% token inflation** |
| w/o Dynamic Budget Throttle | 1104.0 | 100.0% | **60.0% token inflation** (in dense clusters) |
| w/o Weak-Edge Suppression | 793.5 | 100.0% | **15.0% token inflation** |
| w/o Adaptive Query-Class Routing | 843.1 | 100.0% | **22.1% token inflation** |

---

## 6. Target Venues & Positioning

Depending on the target scientific audience, the paper will be positioned under one of two core frameworks:

### A. SIGMOD/VLDB (Database / Systems Track)
*   **Focus**: Graph database indexing latency, incremental manifest caching, database compression ratios (GG-LL vs CSR), and systems throughput.
*   **Key Metrics**: Scan serialization speed, SQLite manifest lookup overheads (<15ms), and index size reductions.

### B. ACL/EMNLP (NLP / LLM Retrieval Track)
*   **Focus**: Downstream model task accuracy, context efficiency, and the cognitive reasoning impact of the Attention Indirection Penalty.
*   **Key Metrics**: Live LLM-as-judge code generation accuracy, downstream BM25 vs. Spreading Activation recall curve comparisons.
