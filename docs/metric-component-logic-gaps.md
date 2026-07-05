# Context Graph: Metric, Component, and Logic Gaps

This document identifies outstanding gaps in evaluation metrics, architectural components, and traversal logic for GraphGraph's codebase context graph runtime. These gaps represent the next major areas of development and research required to achieve comprehensive validation and optimization.

---

## 1. Metric Gaps

While GraphGraph currently evaluates basic node/edge recall, token counts, and basic QA accuracy, several critical evaluation dimensions remain unaddressed:

### A. Rank-Aware Retrieval Quality (MRR & NDCG)
* **Gap:** Current retrieval evaluation treats node containment as binary (recalled vs not recalled). It does not evaluate the *position* of the target nodes.
* **Why it matters:** LLMs suffer from "Lost in the Middle" attention degradation. If a critical node is positioned deep inside a large context packet, the model's reasoning accuracy drops.
* **Target Metric:**
  * **MRR (Mean Reciprocal Rank):** Evaluates if the top-scoring nodes from spreading activation contain the target evidence.
  * **NDCG@K (Normalized Discounted Cumulative Gain):** Evaluates if the ranking of nodes in the serialized prompt matches their topological relevance.

### B. Functional Downstream Correctness (Pass@K)
* **Gap:** The model reasoning benchmark evaluates a mock QA extraction task (asking the model to list node IDs in strict JSON). There is no automated loop to verify that the retrieved context actually enables the model to write correct code edits.
* **Why it matters:** A context format could achieve 100% node recall on paper, but confuse the model during code generation due to missing type signatures, macro dependencies, or verbose noise.
* **Target Metric:** **Pass@1 / Pass@K** rate on code-modification benchmarks (e.g., Locus, SWE-bench) where the generated code is compiled and run against target test suites.

### C. LLM-as-a-Judge Evaluation
* **Gap:** The codebase lacks validation for semantic quality indicators such as hallucination rates or answer relevance.
* **Why it matters:** Pure string matching cannot detect when the LLM generates syntactically correct code that references nonexistent API methods or libraries (faithfulness/groundedness violation).
* **Target Metric:** Evaluator LLM scores (1–5 scale) assessing **Faithfulness / Groundedness** and **Answer Relevance**.

---

## 2. Component Gaps

The following architectural components are currently missing or require significant engineering to support production-scale codebases:

### A. Garbage Collection (GC) for Incremental updates
* **Gap:** The incremental update path (`manifest.py` and `io.py`) supports adding and updating modified files, but does not cleanly prune deleted symbols, refactored variables, or dead references.
* **Impact:** Over time, the graph suffers from **graph drift**, accumulating orphan nodes and stale edges that pollute retrieval and increase token waste.
* **Target Component:** A graph pruning/garbage collection utility that sweeps the database to ensure strict integrity with the active git branch.

### B. OOP Hierarchy & Dynamic Import Resolution in Scanners
* **Gap:** The Tree-Sitter front-ends capture function definitions and call edges, but miss:
  * **Inheritance structures** (`implements`, `subclass_of`, `extends`).
  * **Dynamic imports** (e.g., `import()` in TS/JS, or dynamic `importlib` resolutions in Python).
  * **Macro/Metaprogramming expansions** (e.g., Rust macro invocations).
* **Impact:** Traversal logic is blind to call paths that route through interfaces, traits, or dynamic dependency injection.

### C. Token-Window Budget Calibration
* **Gap:** The dynamic budget estimator relies on a token proxy coefficient. While calibrated within 1.5% for current formats, it is pessimistic about dense subgraphs, leading to over-pruning.
* **Impact:** GraphGraph may prematurely truncate peripheral node contexts even when the prompt window has ample room.

---

## 3. Logic & Traversal Gaps

The retrieval and planning algorithms contain several structural limitations:

### A. Central Node Saturation (`hub_blast`)
* **Gap:** When expanding outward from a highly connected hub (such as a shared utility file, registry, or config block), a 2-hop BFS traversal quickly saturates the maximum node budget, evicting peripheral leaf nodes that contain the target answer evidence.
* **Why it matters:** Central registries cause retrieval noise to bleed into unrelated subsystems.
* **Target Logic:** Implement hub-penalty heuristics during Spreading Activation to throttle activation decay on high-degree nodes.

### B. Weak-Edge and Doc-Code Pairing Heuristics
* **Gap:** The connection between documentation (`docs/`) and code (`src/`) relies on weak string-alias mentions, which frequently fail if doc syntax does not match code symbol casing.
* **Why it matters:** Abstract conceptual queries fail to locate relevant implementation code if the bridging "explains" edge is missing.
* **Target Logic:** Integrate hybrid semantic-vector retrieval to dynamically bridge doc-to-code edges during query expansion.

---

## 4. Realism & Sandbox Testing Gaps (Testing Against Real Things)

To transition GraphGraph from a local evaluation suite to a robust production system, the testing framework must validate against real-world systems, tokenizers, developer behaviors, and execution data:

### A. Codebase Scale & Language Diversity
* **Gap:** Current tests run against relatively small local codebases. A production system must handle massive multi-million-line monorepos and polyglot codebases (e.g., TS + Rust, Python + C++ bindings).
* **Impact:** High-node graphs stress-test SQLite database join performance, memory consumption of traversal algorithms, and dynamic prompt budget estimators.
* **Target Testing:** Benchmark retrieval latency, memory spikes, and index-build speeds against large open-source monorepos (e.g., Kubernetes, VS Code, Chromium).

### B. Real Developer Query Distributions
* **Gap:** Evaluation tasks are synthetically generated from existing graph structures or manually crafted. They do not represent the messy, incomplete, and conversational style of real developer queries.
* **Impact:** Real queries contain spelling mistakes, generic terminology, and conversational overhead, which can degrade lexical anchor matching.
* **Target Testing:** Build a query log dataset harvested from actual IDE chat sessions (from Cursor, VS Code extension logs, or CLI tool command histories).

### C. actual Provider Tokenization Vocabularies
* **Gap:** Current token counts are estimated using generic character-regex rules or local `tiktoken` defaults. Different model APIs (Gemini, Anthropic, OpenAI, Llama) use wildly different BPE/SentencePiece vocabularies.
* **Impact:** Tokenization boundaries affect how numeric node IDs (`gg_max`) and lexical keys (`gg_lex`) are chunked. If a model tokenizes `N00142` into three separate tokens (`N`, `001`, `42`), the attention overhead and cost increase.
* **Target Testing:** Run the token preflight check and optimization algorithms using actual provider-specific tokenizers (e.g., Anthropic's tiktoken variant, Google's Gemini tokenizer).

### D. Multi-Turn Session & State Testing
* **Gap:** Benchmarks evaluate single-turn queries. In real developer workflows, a user interacts with the codebase over a multi-turn chat session.
* **Impact:** Single-turn testing fails to evaluate how the context graph manages conversation history. Sending the same code nodes repeatedly wastes tokens, while failing to retrieve newly referenced dependencies breaks context continuity.
* **Target Testing:** Design multi-turn evaluation tasks that measure context accumulation, delta retrieval, and historical decay across a 5-to-10 turn conversation.

### E. Profiling & Dynamic Execution Integration
* **Gap:** The static code graph maps all *possible* dependencies, treating rarely-used utility code and hot execution paths with similar structural weights.
* **Impact:** Retrieval becomes polluted with boilerplate setup paths rather than the core business logic executed during the target task.
* **Target Testing:** Ingest real-world code coverage and execution profiles (e.g., Python `coverage.py`, Go `pprof`, `OpenTelemetry` call traces) to dynamically boost edge weights based on real-world execution paths.

---

## 5. Architectural & System Interoperability Gaps

To integrate with the wider semantic web, external graph databases, and IDE tools, the following interop gaps must be closed:

### A. Graph Database Export/Import (Neo4j, Cypher, GEXF)
* **Gap:** While GraphGraph operates on local JSON/SQLite formats, it lacks standardized connectors to write to or read from enterprise graph databases.
* **Impact:** Developers cannot visualize GraphGraph code structures in tools like Gephi, nor can they query the codebase graph using standard Cypher/SPARQL languages.
* **Target Component:** Export/import modules for Cypher queries, GraphML, and GEXF formats.

### B. Standardized Relation Ontology (JSON-LD / Schema.org)
* **Gap:** The system's edge types (`calls`, `imports`, `defines`) are project-specific strings rather than standardized semantic web URI representations.
* **Impact:** Lack of schema compatibility with external code intelligence representations (like LSIF or Kythe).
* **Target Component:** A JSON-LD serialization serializer mapping GraphGraph nodes/edges to semantic web schemas.

---

## 6. Advanced Algorithmic & Search Gaps

Retrieval performance suffers from semantic mismatch and scaling issues in large workspaces:

### A. Local Vector/Embedding Fallback (Hybrid Search)
* **Gap:** The anchor lookup relies entirely on keyword matching (BM25). If a user queries for "database connections" but the codebase uses the term `SocketPool`, the initial lookup fails.
* **Impact:** Retrieval recall drops to zero when terminology diverges.
* **Target Logic:** Implement a local, lightweight vector database fallback (e.g., using FastEmbed or a local Chroma/Qdrant instance) to generate semantic anchors.

### B. Hierarchical Community Summarization (clustering)
* **Gap:** For broad structural queries (`subsystem_summary`), the retriever pulls individual nodes. In a large repository, this fills the prompt with disjoint code snippets without providing a high-level view.
* **Impact:** LLM fails to comprehend overall module interactions.
* **Target Logic:** Implement community detection algorithms (e.g., Leiden or Louvain clustering) to partition the codebase into hierarchical clusters and pre-compute summary nodes for each cluster.

### C. Graph-to-Text Verbalization vs. Raw Serialization
* **Gap:** The system assumes raw formats like `gg_lex` or `gg_max` are always optimal. It lacks a baseline comparing raw serialization with natural-language graph verbalization (e.g., writing "Class A has a method B which calls C").
* **Impact:** Some models may perform better with structured prose than with adjacency arrays.
* **Target Testing:** An ablation study comparing raw indices against verbalized textual descriptions.

---

## 7. Caching, Security & Deployment Gaps

Operating the context graph in production IDEs introduces specific performance and security concerns:

### A. KV Cache-Alignment Optimization
* **Gap:** Modern LLM providers offer significant discounts for cached prefix tokens. GraphGraph's dynamic serializers do not sort or order nodes and edges to maximize KV cache reuse across subsequent queries in a session.
* **Impact:** Minor code or query changes trigger complete cache invalidation, raising API costs and latency.
* **Target Logic:** Implement a deterministic context ordering algorithm that places stable, high-level structures (configs, index tables) first, and dynamic query-specific nodes last.

### B. PII & Secret Leakage Prevention
* **Gap:** The AST scanner extracts literal strings, comments, and config parameters, which can occasionally contain API keys, passwords, or personal data.
* **Impact:** Sensitive data is serialized and transmitted to external third-party LLM providers.
* **Target Component:** A scanning gate that redacts credentials, secrets, and PII before writing nodes to the graph database.

### C. Real-Time IDE Event Streaming (MCP SSE)
* **Gap:** The MCP server (`mcp_server.py`) operates in request-response mode. There is no push event system.
* **Impact:** In collaborative agent loops, an agent is unaware of concurrent file edits or updates until a manual file rescan is run.
* **Target Component:** Server-Sent Events (SSE) or WebSocket streaming inside the MCP server to broadcast code modification events to listening client agents.


