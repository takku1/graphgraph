# Architectural Comparison: GraphGraph vs. Neo4j

We analyzed the core storage, layout, and traversal design patterns of **Neo4j** (derived from a local Neo4j checkout and native store specs) and compared them to **GraphGraph**'s database engine.

---

## 1. Storage Layout & Memory Locality

| Database / Engine | Primary Layout | Adjacency Strategy | Focus |
| :--- | :--- | :--- | :--- |
| **Neo4j** (Native Engine) | **Fixed-size Records / Block Format** | Double-linked Pointer lists | High-write OLTP concurrency |
| **GraphGraph** (`.gg` GGB4) | **Sectioned string tables and numeric relation records** | Selective relation sections plus resident adjacency maps | High-read compiled project context |

### Neo4j: Pointer Chasing & Data Locality
* **Historical Record Format**: Neo4j traditionally uses fixed-size record blocks (e.g., 9 bytes per Node, 34 bytes per Relationship). Since records are fixed-size, the physical address of Node `N` on disk is calculated in constant time via simple multiplication: `offset = N * NodeSize`.
* **Pointer Chasing**: Relationships are stored as linked lists. Traversal involves jumping across memory addresses to follow relationship pointers.
* **The Block Format Evolution**: Modern Neo4j versions introduce the **Block Format**, which groups related nodes, properties, and relationships into the same physical cache lines/pages. This minimizes the latency of pointer chasing across arbitrary memory spaces by maximizing cache locality.

### GraphGraph: Sectioned numeric adjacency
* **Selective records**: GGB4 separates identity, complete edge, and exact-call records. A caller/callee query reads only the directory and relevant identity/relation sections.
* **Resident maps**: Stored numeric endpoints are compiled into incoming/outgoing maps after a selective load. General graph traversal still uses the Python `Graph`; GraphGraph does not claim universal on-disk CSR execution.

---

## 2. Index-Free Adjacency (IFA)

Both databases leverage **Index-Free Adjacency (IFA)** to execute traversals, but they solve different scalability problems:

* **Neo4j's IFA**: Ensures that traversing a relation does not require a global index lookup (like a relational B-Tree join). The time complexity of traversing from node $A$ to node $B$ is $O(1)$, independent of the total graph size.
* **GraphGraph's bounded adjacency**: Exact call records use numeric endpoint pairs and resident maps, avoiding a full edge-table load for that operation. Broader retrieval materializes the graph and should not be described as index-free on-disk adjacency.

---

## 3. Query Semantics & Traversal Goals

* **Neo4j (Cypher & Path Matching)**:
  * Designed to match arbitrary graph patterns (e.g. `MATCH (a)-[:CALLS]->(b)`) using a cost-based query planner.
  * Focuses on returning exact records, paths, or aggregates.
* **GraphGraph (Topological LLM-Grounding)**:
  * Designed for **context maximization**. It does not parse Cypher queries; instead, it uses a hybrid retrieval model (lexical matching + personalized PageRank + Energy Decay).
  * The final target is to compress a multi-hop traversal graph into a token-optimal payload (`gg_max`) that fits into an LLM's context window.

---

## 4. Key Insights for GraphGraph
1. **Locality supports GGB4's sections**: Neo4j’s move toward block locality supports grouping data by access pattern. GGB4 applies that principle at project scale by separating hot exact-relation records from cold evidence while retaining one canonical file.
2. **Read-Heavy Static Compaction**: Because codebases are static during a given coding turn, GraphGraph does not need the heavy transactional locking, write logging, or Cypher compiler overhead of Neo4j. This allows it to run serverless, completely in-memory, and output serializations in milliseconds.
