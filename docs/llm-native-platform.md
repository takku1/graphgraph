# LLM-native platform

GraphGraph is a low-level context language for LLM agents, not a general graph
database with an LLM added on top. A capability belongs in GraphGraph only when
it compiles to the same typed, evidence-bearing graph IR and the same bounded
packet runtime:

```text
SYNC -> EXTRACT -> NORMALIZE IR -> ANCHOR -> EXPAND -> SELECT -> PACK
```

The graph is the intermediate representation. `gg`, `semantic_arrow`, SQL,
and the other packet formats are target encodings. Retrieval planning is the
optimizer. A validation/continuation/change receipt is the execution result an
agent can inspect without reverse-engineering prose.

## Platform compiler

`GraphProgram` is the common request contract. `GraphRuntime.compile()` applies
bounded graph passes, routes query intent, retrieves the minimum useful
subgraph, emits a compact packet, and validates it. Optional features do not
own separate query engines.

```powershell
graphgraph platform compile "blast radius of session refresh" --pass evidence --pass inference
graphgraph platform capabilities
```

MCP callers use `compile_context`. The result is one JSON envelope containing
the packet and a receipt with passes, anchors, node/edge counts, provider
receipts, source-planner receipts, warnings, and packet validity.

Evidence providers persist versioned, per-source IR in the transactional
`.graphgraph/evidence.db` store. Existing `evidence.json` state is imported
lazily and left intact. Scanner manifest hashes decide which partitions must
be rebuilt, while query anchors prioritize the partitions materialized into a
bounded compilation. Every provider receipt conserves its candidate ledger:

```text
emitted = accepted + duplicate + rejected + truncated
```

The default CPG provider delegates Python to the native AST and normalizes
Tree-sitter CST evidence for JavaScript/TypeScript, Go, Rust, Java, C/C++, C#,
Ruby, PHP, Kotlin, Scala, and Swift. It emits bounded intraprocedural
`reads`, `writes`, `control_flow`, `field_of`, `type_of`, and `returns` edges.
This is not compiler-resolved alias analysis or interprocedural data flow.

## Query-time source planner

Normal `context`, `query`, MCP, compiler, HTTP, and benchmark paths share the
same bounded compiler and source planner. Relevant records from
`.graphgraph/memory.json`, `episodes.jsonl`,
`projects.json`, and `runtime-trace.jsonl` become ordinary nodes and edges.
The local semantic index contributes seed node IDs only when lexical anchoring
is weak, unless `--source-mode all` is requested. Use `--source-mode off` for
structural-only benchmark baselines and repeat `--memory-scope` to opt into
additional memory scopes.

## Twelve capabilities, translated

| Capability | GraphGraph implementation | Low-level output |
| --- | --- | --- |
| Compiler-grade evidence boundary | Persisted `EvidenceProvider` registry; structural and multi-language CPG providers | Typed reads/writes/control/type/test edges with exact merge and truncation receipts |
| Change understanding | `platform change` | Added/removed/changed IR, impacted nodes, breaking relations, stable cursor |
| Agent continuation | `platform continuation` | Deterministic receipt with completed/remaining work, changed paths, validation, and next query |
| Evaluation gates | `platform eval` and enforced `platform benchmark` | Multi-project latency, token, recall, relation, and packet-correctness gates |
| Multi-repo federation | project registry plus `platform federate` | Namespaced nodes, repository roots, and bounded `cross_repo` evidence |
| Semantic fallback | local hashed-vector sidecar | Candidate node IDs and scores; structural retrieval remains authoritative |
| Temporal knowledge | episode log and `platform as-of` | Native `valid_from`/`valid_to`, `records`, and `supersedes` IR |
| Agent/project memory | scoped local memory store | Memory nodes and grounded `remembers` edges |
| Hierarchical summaries | deterministic community pass | Community nodes, extractive facts, and `contains` edges |
| Interop/team operation | JSON/JSONL/GraphML/Cypher export and hardened HTTP service | Portable graph IR and authenticated GET/POST compiler/state APIs |
| Operational UI | `platform serve` | Cached console over status, query, node, topology, memory, episode, trace, and migration APIs |
| Inference/traces/repair | bounded Horn-style rules, runtime trace ingestion, repair compiler | Explicit inferred/observed edges and bounded issue-to-code packets |

## Adapter commands

Run `graphgraph platform --help` for all flags. Core workflows:

```powershell
# Structural change and continuation receipts
graphgraph platform change --before old.gg --after new.gg
graphgraph platform continuation --objective "finish auth repair" --remaining "run integration tests"

# Repository federation and cross-project evaluation
graphgraph platform register api --root ..\api --graph ..\api\.graphgraph\graph.gg
graphgraph platform federate --output .graphgraph\federated.gg
graphgraph platform eval --registry .graphgraph\projects.json --cases acceptance.json
graphgraph platform benchmark --config multi-repo-acceptance.json

# Time, memory, semantics, and evidence
graphgraph platform episode add --id decision-17 --kind decision --summary "Use local token validation"
graphgraph platform as-of 2026-07-01T00:00:00Z --output snapshot.gg
graphgraph platform memory add "Session changes require revocation tests" --related session_node
graphgraph platform semantic "credential revocation" --rebuild
graphgraph platform trace --trace runtime.jsonl --output traced.gg

# Portable outputs and shared operation
graphgraph platform export --output graph.graphml
graphgraph platform serve --port 8765
graphgraph platform serve --host 0.0.0.0 --token $env:GRAPHGRAPH_TOKEN --allow-origin https://client.example
graphgraph platform migrate --directory .graphgraph
graphgraph platform watch --directory .
graphgraph platform hooks --directory .
```

## Guardrails

1. Structural evidence wins over semantic similarity. Semantic results seed
   candidates only; they do not manufacture dependency claims.
2. Inference is bounded, lower-confidence, and carries the rule plus the
   intermediate node in `evidence`.
3. Federation namespaces identities before linking repositories. Shared names
   are weak evidence, not entity equality.
4. Memory and episodes are append-oriented and scope-aware. They become normal
   IR nodes only when projected.
5. HTTP, UI, exports, and watch mode are adapters. None bypass packet planning
   or define a second graph semantics.
6. Every agent-facing compilation ends with a mechanical packet validation
   receipt.
7. Platform state is schema-versioned. Writes use cross-process lock files,
   atomic replacement, and durable flushes; run `platform migrate` before
   moving long-lived state between releases.
8. HTTP binds safely to loopback without authentication. Non-loopback binding
   requires a token and uses exact origin allowlists, bounded bodies, rate
   limits, and restrictive browser security headers.

## Current measured acceptance

- Incremental CPG evidence on the Express graph: 38 source partitions, 380
  evidence nodes, 530 typed edges, 578 ms cached compile.
- Three-repository gate (GraphGraph, Flask, Express): 100% node and relation
  recall, 520.5 ms p95 retrieval latency, 1,291 mean packet tokens, all packets
  valid.
- GraphGraph semantic source planning: 1.54 s cached real-repository context
  query with six semantic seed IDs and a valid packet.
