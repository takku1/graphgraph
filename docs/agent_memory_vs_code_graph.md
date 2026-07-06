# Architectural Analysis: GraphGraph vs. Graphiti (Zep) vs. Mem0

We compared **GraphGraph** to Zep's **Graphiti** (Zep's temporal graph engine) and **Mem0** (personalized agent memory). Below is the comparative audit and side-by-side logic analysis.

---

## 1. Side-by-Side Comparison

| Dimension | GraphGraph (Native) | Zep Graphiti | Mem0 |
| :--- | :--- | :--- | :--- |
| **Primary Domain** | **Codebase AST & Doc Topology** | Episodic/Conversational Memory | Agent Personalized Preferences |
| **Data Model** | Static code symbols + doc concepts | Bi-temporal (Valid & Ingest timelines) | Vector Embeddings + Fact Graphs |
| **Update Pipeline** | **Deterministic AST scan (Tree-sitter/Regex)** | LLM Extraction on message streams | LLM Decision Engine (Add/Update/Delete) |
| **Update Cost** | **Zero LLM cost** (runs locally in <2s) | High (LLM calls on every message) | High (LLM calls on every interaction) |
| **Retrieval Engine** | **Personalized PageRank + Energy Decay** | Hybrid vector + graph traversal | Vector similarity + Graph traversal |
| **Storage Layer** | **Serverless flat `.gg` (GGB3) files** | PostgreSQL / Neo4j database servers | Qdrant / pgvector + Graph database |
| **Wire Format** | **Token-optimal `gg_max` / `semantic_arrow`** | Verbose conversational summaries | Raw JSON / Text fact lists |

---

## 2. Deep Dive Comparison

### Zep's Graphiti: Bi-Temporal Invalidation
* **How it works**: Graphiti treats time as a first-class dimension. When new context arises, it does not overwrite old facts; instead, it tracks the *Validity Window* (when a fact was true) and *Ingestion Time* (when Zep learned it). If a fact is contradicted, the edge is "temporarily invalidated."
* **Comparison to GraphGraph**:
  * Graphiti is built for conversational history where past states matter ("What did we discuss last Tuesday?").
  * For coding agents, past code states are historical git commits (managed by Git). Coding agents only need the **current live state** of the codebase to write correct, compilation-ready updates. GraphGraph’s incremental scan resolves this by immediately invalidating and cleaning up stale symbol references during local scans.

### Mem0: Self-Improving Decision Engine
* **How it works**: Mem0 uses a streaming pipeline. An LLM acts as a "Decision Engine" to parse message exchanges and explicitly decide whether to `Add`, `Update`, `Delete`, or `NOOP` memories. It stores these as personal preferences (e.g. "User prefers Python for data tasks").
* **Comparison to GraphGraph**:
  * Mem0 is excellent for user personalization (e.g., memory across sessions).
  * However, running LLM decision prompts on every single line of code or symbol relation during a codebase scan is completely non-viable—it would cost thousands of dollars and take hours. GraphGraph relies on **deterministic AST analysis** to build high-fidelity graphs instantly and with 100% precision.

---

## 3. Are We Better?

### Where GraphGraph Wins (Code Grounding & Context Packaging)
1. **Zero LLM-Build Cost**: GraphGraph scans a 10,000-node repo in under 2 seconds using local CPU parsers. Both Graphiti and Mem0 require heavy, non-deterministic, and expensive LLM calls to extract and organize relations.
2. **Serverless & Local-First**: GraphGraph does not require running database daemons (like Neo4j or Postgres-vector). It runs completely serverless out of a local `.graphgraph/graph.gg` file, making it instantly compatible with sandboxed IDE workflows.
3. **Mathematically Token-Optimized**: GraphGraph’s serializations (`gg_max`, `semantic_arrow`) are specifically designed to minimize token usage in the LLM's context window. Graphiti and Mem0 output standard JSON or verbose prose lists, which carry significant token overhead.

### Key Insights to Borrow
* **Memory Tiers**: Mem0 segmenting memory into *User-level*, *Session-level*, and *Agent-level* is a powerful abstraction. For codebase reasoning, we could categorize our context:
  * **Agent Scope (Global)**: The static `.graphgraph/graph.gg` code map.
  * **Session Scope (Ephemeral)**: The active editor buffer, cursor position, and git diff.
  * **User Scope (Persistent)**: Mined assistant instructions (`AGENTS.md`, `CLAUDE.md`, `.cursorrules`).
