# Extensible Context Compiler for an LLM-Native General Context Graph

Status: research finding; proposed architecture, not yet promoted to a system decision

Review date: 2026-08-08

Implementation note (2026-08-08): the production vocabulary is now
`ContextCompiler`, `CompileRequest`, and `CompileOutcome`; compiler-pass
execution is centralized and the old runtime/factory and duplicate CLI pass
loop have been removed. Historical current-state passages below intentionally
describe the pre-migration implementation. The ordered production frontier is
`OW-Q09-A…F` in [`docs/open-work.md`](../open-work.md).

## 1. Decision summary

GraphGraph should become a deep `ContextCompiler` Module whose public Interface expresses only the semantic result a caller needs and the resource/freshness constraints under which it must be produced. Callers should not select an ordered list of passes, invoke routing and retrieval stages, choose caches, or coordinate packet formats.

Internally, compilation should be a typed artifact DAG assembled from declarative pass contracts. Built-in behavior and third-party extensions should use the same pass Interface. Evidence providers, language frontends, source projections, and packet targets should remain extensible through narrow Adapters; they should not become alternate orchestration paths.

The central architectural rule is:

> One canonical semantic graph IR, many typed producers and target encoders, one compiler-owned schedule.

This produces greater Depth and Leverage than the retired `GraphProgram`
controls. It also improves Locality: pass execution, cache validity, graph
mutation, target selection, validation, and receipts live in one compiler
Module rather than being repeated across runtime and transport paths.

## 2. Current architecture and concrete seams

### 2.1 Compiler and runtime

The current compiler is concentrated in [`src/graphgraph/platform/compiler.py`](../../src/graphgraph/platform/compiler.py):

- `CompilerPassSpec` now atomically declares version, required/product/preserved
  artifacts, capabilities, determinism, cache scope, request parameters, and a
  static cost model. `platform/artifacts.py` binds deterministic reuse to
  component revisions plus content digests and rebases explicitly preserved
  artifacts on a hit.
- `COMPILER_PASSES` is a closed tuple containing `evidence`, `inference`, and `hierarchy`.
- `CompileRequest` still exposes optional pass ordering plus scopes, traversal
  budgets, anchor limits, representation choice, and representation budget.
- `ContextCompiler.compile` owns pass execution, query routing, context
  planning, exact lookup, budget shaping, graph retrieval, refinement, target
  rendering, validation, and receipt construction.
- `CompileOutcome` exposes `graph`, `route`, `plan`, and `retrieval`; these are
  useful internal results but still reveal Implementation choices to advanced
  callers.

The public `CompilerDriver` is now the deep project-level Interface. The
advanced `ContextCompiler` seam intentionally remains more explicit, but a
derived scheduler should eventually remove caller-selected pass ordering.

### 2.2 Evidence

[`src/graphgraph/platform/contracts.py`](../../src/graphgraph/platform/contracts.py) defines the strongest existing extension Seam:

- `EvidenceProvider` declares identity, version, capabilities, incrementality, and `collect(graph, paths)`.
- `EvidenceBatch` contains graph nodes, graph edges, and a `CapabilityReceipt`.
- `ProviderRegistry` invokes providers and merges results.
- `StructuralEvidenceProvider` and `PythonAstEvidenceProvider` are built-ins.

[`src/graphgraph/platform/evidence_store.py`](../../src/graphgraph/platform/evidence_store.py) persists versioned provider batches per source path in JSON or SQLite. It already contains useful conservation and freshness behavior, but merging is split between the store and `ProviderRegistry`, and providers are coupled to a mutable `Graph` rather than typed immutable inputs and a `GraphDelta` output.

[`src/graphgraph/platform/cpg.py`](../../src/graphgraph/platform/cpg.py) adds multi-language CPG evidence. OW-Q09-B removed its independent query-time parse: it now consumes the scanner's content-addressed `SyntaxIR` for an unchanged `SourceIR` revision and reports compiled/reused artifact counts.

### 2.3 Frontends

[`src/graphgraph/scanner/source_ir.py`](../../src/graphgraph/scanner/source_ir.py) defines the canonical versioned `SourceIR` and cached `SyntaxIR`; [`src/graphgraph/scanner/frontends/model.py`](../../src/graphgraph/scanner/frontends/model.py) defines `FrontendCapability`, `ExtractionResult`, and the `Extractor` protocol. [`src/graphgraph/scanner/frontends/extractors.py`](../../src/graphgraph/scanner/frontends/extractors.py) contains regex and Tree-sitter extraction.

The frontend seam now shares syntax through `SourceIR`, but extractors still emit graph-shaped results directly. Later compiler stages should continue moving normalized symbol facts into typed artifacts rather than introducing another semantic graph.

### 2.4 Packet targets

This seam has now converged on the proposed atomic design.
[`src/graphgraph/packet_targets.py`](../../src/graphgraph/packet_targets.py)
owns the cold-start-safe `TargetSpec` catalog. Each target declares its
capabilities, encoder and validator references, cost model, priority behavior,
detection grammar, endpoint identity projection, and adaptive alternatives.
CLI, MCP, HTTP, renderer dispatch, validation dispatch, and planner cost
surfaces derive from this catalog. The former `packets/formats.py`, renderer
dispatch dictionaries, validator sniff branches, and packet-name copy in
`surface.py` were deleted rather than retained as compatibility registries.

### 2.5 Outer orchestration

[`src/graphgraph/services/compiler_driver.py`](../../src/graphgraph/services/compiler_driver.py)
now owns project lifecycle, whole-response cache identity, compilation,
validation, control, and actionable receipts. `services/context.py` retains only
known-anchor final-packet operations. CLI, MCP, and HTTP are transport Adapters;
the former independent pass loops and `GraphProgram` construction are gone.

## 3. Parallel representations: legitimate projections versus drift risks

The desired representation topology is not “one physical format.” It is one canonical semantic IR with projections that have explicit ownership and loss contracts.

| Representation | Current role | Decision |
|---|---|---|
| In-memory `Graph` | Canonical queryable semantic IR | Keep; make snapshot/revision semantics explicit |
| GGB4 | Native persisted graph | Keep as the primary local store |
| EvidenceStore batches | Provider/source incremental cache | Keep as typed `GraphDelta` cache; never query as an alternate graph |
| Memory, episodes, projects, traces, federation state | Independent source stores | Keep behind source Adapters; project into canonical IR before reasoning |
| Semantic sidecar/index | Candidate-generation acceleration | Keep as a derived analysis indexed by graph revision |
| `SourceIR` / CST / AST | Frontend intermediate facts | Add as a typed compiler artifact; cache per source revision |
| Compact, JSON, Markdown, SVO, hybrid packets | Final target encodings | Keep as lossy targets; never feed them back as canonical IR |

The following parallel representations should be eliminated:

1. Pass names separately encoded in compiler tuples, transport choices, schemas, UI markup, tests, and documentation.
2. Format identity separately encoded in format specifications, renderer dispatch, validator dispatch, priority awareness, and public surface constants.
3. Route and plan state calculated once for caching and again for compilation.
4. Syntax and symbol facts reparsed independently by scanner frontends and evidence providers.
5. A transform-only pass loop separate from ordinary compilation.

## 4. Dependency classification

The compiler should classify dependencies before creating Seams.

### 4.1 In-process

The graph IR, ontology, routing, planning, anchoring, expansion, ranking, connected selection, inference, hierarchy, packet-cost estimation, encoding, validation, and receipt logic are in-process dependencies. Tests should exercise these through the `ContextCompiler` Interface first. Internal pass-level tests are warranted because the pass Interface is also an intentional extension Seam.

### 4.2 Local-substitutable

GGB4 storage, SQLite evidence persistence, the filesystem/source snapshot, Tree-sitter parsers, semantic indexes, and memory/episode/trace/project stores are local-substitutable dependencies. They need controllable test Implementations such as temporary stores, in-memory SQLite, and fixed source snapshots. They should not become caller-facing orchestration controls.

### 4.3 Remote but owned

The default local compiler has no required remote-but-owned dependency. CLI, MCP, and HTTP are Adapters outside the compiler Seam, not dependencies of compilation. If GraphGraph later owns a remote index or model host, define a port and fake Adapter at that time.

### 4.4 True external

Optional embedding/model providers, external language indexers, and third-party plugins are true external dependencies. Mock the narrow ports. Automatic compilation must not initialize a cold true-external dependency unless the requested capability cannot be satisfied locally and policy explicitly permits it.

The seam rule is strict: one Adapter represents a hypothetical Seam; two Adapters establish a real one. Do not introduce storage, queue, or workflow abstractions merely in anticipation of a second Implementation.

## 5. Proposed public Interface

The public Module should be small:

```python
class ContextCompiler:
    @classmethod
    def open(
        cls,
        project: ProjectRef,
        *,
        extensions: ExtensionPolicy = ExtensionPolicy.installed(),
    ) -> "ContextCompiler": ...

    def compile(self, request: CompileRequest) -> CompileOutcome: ...
```

`open` discovers and validates the available catalog once, loads only cheap metadata, and returns a resident compiler. `compile` accepts semantic intent and constraints, derives a pipeline, and returns a complete or explicitly partial outcome.

```python
@dataclass(frozen=True)
class CompileRequest:
    query: str
    goal: QueryGoal = QueryGoal.AUTO
    scope: Scope = Scope.project()
    required_capabilities: frozenset[Capability] = frozenset()
    constraints: CompileConstraints = CompileConstraints()
    target: TargetPreference = TargetPreference.auto()

@dataclass(frozen=True)
class CompileConstraints:
    max_tokens: int | None = None
    max_latency_ms: int | None = None
    max_nodes: int | None = None
    max_edges: int | None = None
    freshness: FreshnessPolicy = FreshnessPolicy.CURRENT_SNAPSHOT
    external_work: ExternalWorkPolicy = ExternalWorkPolicy.LOCAL_ONLY

@dataclass(frozen=True)
class CompileOutcome:
    status: OutcomeStatus  # ANSWERABLE | PARTIAL | ABSTAINED
    packet: bytes
    target: TargetId
    receipt: CompilationReceipt
```

Ordered passes, hop counts, anchor limits, source plans, route objects, graph instances, retrieval internals, cache controls, and alternate-format trials are deliberately absent. They are Implementation decisions derived from the query goal, available capabilities, empirical cost models, and constraints.

Advanced callers that require repeatability can supply a compiler profile or a previously emitted pipeline fingerprint. They still should not own the schedule.

## 6. Internal pass Interface

Built-ins and plugins should implement the same declarative contract:

```python
@dataclass(frozen=True)
class PassSpec:
    id: PassId
    version: str
    consumes: frozenset[ArtifactKey]
    produces: frozenset[ArtifactKey]
    requires: frozenset[AnalysisKey]
    preserves: frozenset[AnalysisKey]
    capabilities: frozenset[Capability]
    purity: Purity                 # PURE | LOCAL_IO | REMOTE
    cache_scope: CacheScope        # NONE | SNAPSHOT | QUERY
    deterministic: bool
    cost: CostModel
    optional: bool = False

class CompilerPass(Protocol):
    spec: PassSpec

    def run(
        self,
        context: PassContext,
        artifacts: ArtifactView,
    ) -> PassResult: ...
```

`PassContext` contains only immutable request data, a source/graph snapshot identifier, remaining budget, cancellation, and internal store/telemetry ports. It does not expose a process-global mutable graph.

`PassResult` contains typed artifacts, an optional `GraphDelta`, precise preserved/invalidated analyses, and a `PassReceipt`. Passes must not mutate an input artifact in place.

LLVM's new pass manager is the right conceptual precedent: a pass declares the IR it runs over, obtains cached analyses from an analysis manager, and reports `PreservedAnalyses`; adaptors connect different IR granularities. This enables precise invalidation rather than flushing every cached analysis after every transform ([LLVM new pass manager](https://llvm.org/docs/NewPassManager.html), [writing a new pass](https://llvm.org/docs/WritingAnLLVMNewPMPass.html)). GraphGraph should borrow the contract, not LLVM's concrete class hierarchy.

### 6.1 Typed artifacts

The initial artifact vocabulary should be:

- `SourceSnapshot`: immutable path/content/hash manifest.
- `SourceIR`: reusable frontend output, including syntax tree and normalized symbol facts.
- `GraphSnapshot`: immutable revision handle to canonical Graph IR.
- `GraphDelta`: additions, updates, removals, provenance, confidence, and conservation counts.
- `QueryIR`: normalized semantic query and operators.
- `RoutePlan`: selected query strategy and required capabilities.
- `AnchorSet`: scored, provenance-bearing seeds.
- `CandidateSubgraph`: retrieved candidates before budget selection.
- `SelectedSubgraph`: connected, budget-accounted graph slice.
- `EncodedPacket`: target bytes plus token/cost accounting.
- `ValidationReport`: structural validity, semantic coverage, answerability, and omissions.

Artifacts should be data, not miniature managers. Only the compiler scheduler and artifact store coordinate them.

### 6.2 Scheduling

An immutable `PassCatalog` is assembled at `ContextCompiler.open`. Given the requested final artifact, required capabilities, available source facts, and constraints, the scheduler derives a DAG from `consumes`, `produces`, and `requires`.

Pipeline construction must reject:

- a required artifact or capability with no producer;
- dependency cycles;
- multiple non-merge producers for the same artifact;
- a pass whose purity violates `external_work` policy;
- a target without both encoder and validator.

Independent deterministic passes may run concurrently. Multiple `GraphDelta` producers merge only through one deterministic reducer with stable ordering and explicit conflict rules. No plugin controls scheduling directly.

## 7. Extension Seams and Adapters

### 7.1 Pass discovery

Use Python packaging entry points for installed pass discovery. Entry points are the standardized mechanism by which installed distributions advertise named objects to a host ([PyPA entry points specification](https://packaging.python.org/en/latest/specifications/entry-points/)). A `graphgraph.passes` group can expose a cheap manifest loader; the actual pass imports lazily only when its capability is selected.

Discovery is not execution. Each discovered pass is validated into the immutable catalog before it can participate in scheduling.

For untrusted or independently deployed passes, an optional out-of-process Adapter may use Protocol Buffers. Proto3 additions can be wire-safe and unknown fields are preserved, making it appropriate for versioned artifact envelopes ([Protocol Buffers proto3 guide](https://protobuf.dev/programming-guides/proto3/)). In-process Python objects should remain the fast default.

### 7.2 Existing evidence providers

Introduce an `EvidenceProviderAdapter` that maps the current `EvidenceProvider.collect` contract to a pass consuming `SourceSnapshot` or `SourceIR` and producing `GraphDelta`. Preserve provider identity, version, capabilities, incrementality, per-source caching, and `CapabilityReceipt` conservation.

This is a migration Adapter, not a second permanent orchestration system. Native providers should eventually implement the pass contract directly.

### 7.3 Frontends and SCIP

Keep regex and Tree-sitter frontends. Tree-sitter explicitly supports incremental parsing by editing an old tree and supplying it when parsing the new source, allowing unchanged structure to be reused ([Tree-sitter incremental parsing](https://tree-sitter.github.io/tree-sitter/using-parsers/3-advanced-parsing.html)). GraphGraph should persist or retain the prior tree/`SourceIR` per source revision and make the CPG pass consume it rather than reparse source at query time.

Add SCIP as an optional `FrontendAdapter` for languages with high-quality indexers. SCIP is a language-agnostic Protocol Buffers index format for definitions, references, implementations, documentation, and symbol relationships, with multiple language indexers ([SCIP repository and specification](https://github.com/scip-code/scip)). SCIP should enrich GraphGraph's canonical IR; it should not replace the IR and does not by itself supply control/data-flow semantics.

The original Code Property Graph work demonstrates the value of combining syntax, control flow, and program dependence into one queryable graph rather than maintaining isolated views ([Yamaguchi et al., IEEE S&P 2014](https://conferences.computer.org/sp/pdfs/sp/2014/4686a590.pdf)). That supports GraphGraph's unified IR direction, while leaving language-specific extraction replaceable.

### 7.4 Target encoders

Replace the parallel packet registries with one atomic descriptor:

```python
@dataclass(frozen=True)
class TargetSpec:
    id: TargetId
    version: str
    media_type: str
    capabilities: frozenset[TargetCapability]
    estimate: CostEstimator
    encode: TargetEncoder
    validate: TargetValidator
```

The CLI choices, MCP/HTTP schema, UI options, public constants, and documentation should be generated from the validated target catalog. A target cannot be advertised unless it can estimate, encode, and validate.

### 7.5 Source projections

Memory, episodes, federation, traces, and project state should be source Adapters that produce ordinary `GraphDelta` artifacts with stable identifiers and provenance. Query planning may require their capabilities, but should not query each source through a bespoke side channel.

### 7.6 Transport Adapters

CLI, MCP, and HTTP should parse a `CompileRequest`, call `ContextCompiler.compile`, and serialize `CompileOutcome`. They should not build pass lists, route queries, plan retrieval, select caches, or build extra semantic receipts.

## 8. Required invariants

1. **Canonical semantics:** exactly one queryable semantic Graph IR exists for a project snapshot. Provider stores, semantic indexes, and packets are derived artifacts.
2. **Snapshot isolation:** every compile observes one immutable source/graph revision. Mixed-revision packets are invalid.
3. **Stable identity:** node and edge identity, ontology, provenance, and confidence survive storage and target conversion according to declared loss rules.
4. **Delta-only mutation:** passes propose `GraphDelta`; the compiler validates and commits through one reducer.
5. **Ledger conservation:** for every producer, `emitted = accepted + duplicate + rejected + truncated`.
6. **Referential integrity:** accepted edges have accepted endpoints in the base snapshot or same committed delta.
7. **Determinism:** equal snapshot, request, catalog fingerprint, and constraints yield equal selected graph, packet, and semantic receipt, excluding explicitly marked telemetry fields.
8. **Declared effects:** every consumed/produced artifact and invalidated analysis must match `PassSpec`.
9. **Unique production:** a non-merge artifact has one producer in a derived pipeline.
10. **Explicit loss:** truncation, unavailable capability, stale evidence, fallback, and confidence degradation appear in the receipt; none are silent.
11. **Target integrity:** every emitted target is validated by the validator registered in the same `TargetSpec`.
12. **Evidence precedence:** lower-confidence inferred or model-derived evidence cannot overwrite structural evidence; conflicts remain provenance-bearing alternatives or are resolved by a declared rule.
13. **Budget monotonicity:** increasing a budget cannot remove previously selected higher-priority evidence unless a documented global optimization changes the connected solution; such change must be reproducible.
14. **Cold-external exclusion:** automatic local compilation never initializes a remote model, embedding runtime, or optional external indexer without policy authorization.
15. **Receipt completeness:** each pass records version, input fingerprints, elapsed time, cache state, output counts, omissions, warnings, and preserved/invalidated analyses.

## 9. Error model

Configuration and contract failures are exceptions:

- `InvalidRequest`: malformed or contradictory intent/constraints.
- `UnsatisfiedPipeline`: no legal producer chain for a required capability or target.
- `PipelineCycle`: artifact dependency cycle.
- `AmbiguousProducer`: multiple non-merge producers.
- `PassContractViolation`: undeclared artifact access/output, invalid preservation claim, or illegal mutation.
- `PassExecutionError(pass_id, retryable, cause)`: pass failed after its contract was accepted.
- `InvalidIR`: graph/delta ontology or referential-integrity failure.
- `StaleSnapshot`: inputs changed and policy forbids a stale result.
- `InvalidTarget`: target descriptor, encoding, or validation failure.
- `PluginLoadError`: an explicitly required extension could not load or validate.

Expected insufficiency is data:

- token, latency, node, or edge budget exhaustion normally yields `PARTIAL` or `ABSTAINED` with an omission receipt;
- optional plugin failure yields a warning and an alternate legal pipeline when one exists;
- missing evidence yields an answerability/coverage result, not an exception;
- `ABSTAINED` is a valid `CompileOutcome`, not thrown control flow.

## 10. Performance model

### 10.1 Cold-start decomposition

“Cold start” must not be one aggregate number. Measure at least:

1. process creation and Python bootstrap;
2. imports;
3. extension metadata discovery;
4. compiler catalog validation and pipeline derivation;
5. project/source freshness discovery;
6. graph header/index load;
7. required GGB4 section reads;
8. source projection and evidence cache lookup;
9. optional frontend parsing or incremental update;
10. query normalization, routing, and analysis;
11. anchoring and exact-index lookup;
12. expansion and candidate retrieval;
13. connected selection and budget optimization;
14. target estimate/encode;
15. validation and receipt serialization.

The existing optimization agenda already calls for separating process startup, graph load, search, expansion, selection, rendering, and validation. The legacy manuscript measured roughly 131 ms for `import graphgraph`, 152 ms for `--help`, 123 ms for graph deserialization, 38 ms for an in-process query, and roughly 300 ms end-to-end CLI latency. These are historical phase clues, not current acceptance numbers ([legacy measurements](manuscript-graphgraph-2.md)).

The current native-store study is more relevant: on a 13,804-node/50,619-edge fixture, GGB4 exact-relation cold median was 246.339 ms versus 453.689 ms for GGB3, and warm median was 5.429 ms versus 10.023 ms ([native graph store measurements](../architecture/storage/native-graph-store.md)). Full-load cold medians were close, 416.113 ms for GGB4 and 408.059 ms for GGB3. Therefore the compiler should preserve section-selective exact lanes rather than force full materialization.

Graph databases also distinguish empty-page-cache startup from warm operation. Neo4j documents that its page cache starts empty and warms on demand or through profile-based preloading ([Neo4j disk and page-cache guidance](https://neo4j.com/docs/operations-manual/current/performance/disks-ram-and-other-tips/)). A server graph database does not remove cold start; it moves it and adds deployment/runtime costs.

### 10.2 Required optimizations

- Keep a resident compiler for MCP/HTTP; treat CLI process startup as a separately optimized path.
- Discover entry-point metadata at `open`, but import extension code only when its capabilities enter a selected pipeline.
- Cache pipeline derivations by catalog fingerprint, goal class, capability set, and policy.
- Cache analyses using `(analysis id, analysis version, graph revision, request fingerprint, relevant artifact hashes)` and invalidate them from pass preservation declarations.
- Load only GGB4 sections consumed by the selected passes; exact operators should compile to a specialized legal pipeline, not bypass semantics.
- Parse or update each source once. Cache `SourceIR` and Tree-sitter trees by content hash; eliminate query-time CPG reparsing.
- Apply per-file incremental `GraphDelta` values and merge deterministically.
- Run independent local deterministic providers concurrently within a bounded pool.
- Estimate plausible target costs before encoding; encode only the selected target unless validation failure requires a declared fallback.
- Move final packet caching inside the compiler so cache keys derive from the actual pipeline and artifact fingerprints, eliminating duplicate pre-routing in `render_query_context`.
- Record phase timings and cache hits in receipts so optimization targets are empirical.

SQLite remains appropriate for provider batches. WAL permits readers and a writer to proceed concurrently through a shared-memory WAL index, but checkpoint policy matters because reader cost rises with WAL size ([SQLite WAL documentation](https://www.sqlite.org/wal.html)). Memory-mapped reads may reduce copy and allocation overhead in suitable environments but have portability and failure-mode tradeoffs ([SQLite memory-mapped I/O](https://www.sqlite.org/mmap.html)). Both should be measured under GraphGraph's workload rather than enabled from analogy alone.

## 11. Retrieval research and tournament candidates

The compiler pass architecture allows retrieval strategies to compete without becoming public orchestration controls.

Microsoft GraphRAG distinguishes local, global, and DRIFT search. Its global method is explicitly resource-intensive and uses map-reduce over community reports; local search combines graph and text context around query-related entities ([GraphRAG query overview](https://microsoft.github.io/graphrag/query/overview/)). Its Knowledge Model separates workflows from storage abstractions ([GraphRAG index architecture](https://microsoft.github.io/graphrag/index/architecture/)). GraphGraph should borrow the query-class idea, but should not import global summarization as the default path for code navigation.

G-Retriever formulates bounded, connected graph retrieval as a prize-collecting Steiner tree problem before generation ([G-Retriever](https://arxiv.org/abs/2402.07630)). This is directly comparable to GraphGraph's connected selection and should enter a matched-budget research tournament as a selection pass.

HippoRAG uses Personalized PageRank over an associative graph and reports lower cost and latency than iterative retrieval on its evaluated knowledge tasks ([HippoRAG](https://arxiv.org/abs/2405.14831)). GraphGraph already uses graph ranking primitives, so the reusable idea is query-dependent restart and memory-style association, not the full system. Its published gains are hypotheses for GraphGraph workloads, not transferable acceptance evidence.

Tournament acceptance should compare answerability, semantic coverage, connectedness, token cost, p50/p95 latency, cold initialization, and deterministic replay on identical graph snapshots and output budgets.

## 12. Comparable local projects

The local `resources` inventory was inspected by directory name first, then selected primary source was read.

### 12.1 Graphiti

Graphiti's `GraphDriver` supports multiple graph stores behind one driver contract, including Neo4j, FalkorDB, Kuzu, and Neptune ([driver source](https://github.com/getzep/graphiti/blob/106da7b34c63220a7f29cfa83bd64e97e3fbf537/graphiti_core/driver/driver.py)). Its search configuration composes per-scope search methods and rerankers, and its search path computes embeddings only when selected methods require them ([search configuration](https://github.com/getzep/graphiti/blob/106da7b34c63220a7f29cfa83bd64e97e3fbf537/graphiti_core/search/search_config.py), [search implementation](https://github.com/getzep/graphiti/blob/106da7b34c63220a7f29cfa83bd64e97e3fbf537/graphiti_core/search/search.py)).

Reuse the capability-configured search recipe and lazy expensive work. Do not adopt Graphiti as the GraphGraph core: its broad database drivers, temporal knowledge extraction, and model-oriented workflow solve a different problem and would weaken local cold-start control.

### 12.2 codebase-memory-mcp

This project uses SQLite with read-only/query-only connections, WAL-aware snapshots, bulk-write tuning, explicit index rebuilds, and configurable memory mapping ([store source](https://github.com/DeusData/codebase-memory-mcp/blob/d6be58ef9d43c574a2d1b0827ecc1e3c4846f0fe/src/store/store.h)). It buffers graph data before persistence ([graph buffer](https://github.com/DeusData/codebase-memory-mcp/blob/d6be58ef9d43c574a2d1b0827ecc1e3c4846f0fe/src/graph_buffer/graph_buffer.h)) and advances watcher state only after a successful reindex ([watcher source](https://github.com/DeusData/codebase-memory-mcp/blob/d6be58ef9d43c574a2d1b0827ecc1e3c4846f0fe/src/watcher/watcher.c)). Its benchmark spans multiple repositories and many languages, demonstrating useful breadth rather than a directly comparable latency result ([benchmark](https://github.com/DeusData/codebase-memory-mcp/blob/d6be58ef9d43c574a2d1b0827ecc1e3c4846f0fe/docs/BENCHMARK.md)).

Borrow successful-reindex commit semantics, explicit coverage accounting, and SQLite tuning candidates. Do not replace GGB4 without a matched GraphGraph tournament.

### 12.3 PyCG and generic graph stores

PyCG is useful as a compact Python call-graph extractor, but it is not a complete multi-language semantic frontend and should not define the general context graph architecture. Kuzu and Neo4j are credible graph storage Implementations, but GraphGraph already has a measured embedded native store optimized for exact relations. A generic store migration is justified only if it wins end-to-end cold/warm, memory, fidelity, and deployment comparisons—not because its query language is convenient.

## 13. Reuse-versus-build decisions

### Keep and deepen

- Keep GraphGraph's graph ontology and canonical Graph IR.
- Keep GGB4 as the primary embedded store; deepen section-selective loading and revision handles.
- Keep SQLite EvidenceStore persistence; migrate its payload contract to versioned `GraphDelta`.
- Keep Tree-sitter and regex frontends; add incremental `SourceIR` reuse.
- Keep GraphGraph's routing, graph retrieval, connected selection, confidence/provenance, compact packets, validation, and abstention logic as compiler passes or analyses.

### Reuse directly

- PyPA entry points for installed extension discovery.
- SCIP as an optional precise language-frontend interchange Adapter.
- Protocol Buffers only for SCIP and optional out-of-process pass transport.
- Tree-sitter's edit-and-reparse mechanism for incremental syntax artifacts.

### Borrow the design, not the dependency

- LLVM's declarative pass inputs/results and precise analysis preservation.
- Graphiti's capability-selected search and lazy expensive work.
- codebase-memory-mcp's successful-index commit and SQLite tuning experiments.
- G-Retriever's connected optimization and GraphRAG's query classes as tournament entrants.

### Reject for the core

- A generic workflow framework. The compiler's artifact DAG is domain-specific and needs precise cache/invalidation semantics.
- Neo4j, Graphiti, or another graph server as the default store. This would sacrifice embedded deployment and move rather than remove cold-start costs.
- PyCG as a general frontend.
- A second semantic graph for model-derived knowledge.
- A permanent compatibility layer that lets every transport continue supplying ordered pass names.

## 14. Migration plan

### Stage 0: establish acceptance gates

Freeze representative compile outputs and add phase-level cold/warm benchmarks. Cover exact operators, general semantic queries, stale source refresh, multi-source projection, partial budgets, and validation failure. Record current catalog/format duplication as architecture tests that are expected to disappear.

### Stage 1: introduce the internal pass model

Extend the implemented `CompilerPassSpec`, component artifact fingerprints, and
analysis cache into a typed artifact DAG with a deterministic `GraphDelta`
reducer. Evidence, inference, and hierarchy already cross the one pass catalog;
no compatibility orchestration layer remains.

### Stage 2: compile the current runtime pipeline

Move source planning, routing, planning, anchoring, retrieval, refinement, selection, rendering, and validation behind pass/analysis contracts. Remove the string `if/elif` dispatcher. Translate legacy `passes` values to required capabilities during deprecation; do not preserve arbitrary caller ordering as permanent semantics.

### Stage 3: deepen the public Module

Introduce `ContextCompiler.open/compile` and `CompileRequest/CompileOutcome`. Move cache-key derivation and semantic receipt assembly into the compiler. Reduce `render_query_context`, CLI, MCP, and HTTP to transport Adapters.

### Stage 4: unify packet targets

Create `TargetSpec` and derive advertised surface, schemas, UI choices, encoding, validation, and cost selection from one catalog. Delete the parallel format registries and replace their tests with target-contract tests.

### Stage 5: unify parsing and precise frontends

Make scanner frontends produce cached `SourceIR`; make CPG/evidence passes consume it. Introduce Tree-sitter incremental updates. Add SCIP as an optional Adapter where its indexers outperform native extraction on fidelity and incremental cost.

### Stage 6: precise caching and lazy loading

Implement analysis preservation/invalidation, pipeline fingerprints, per-file deltas, lazy plugin import, and section-selective GGB4 views. Re-run phase-level gates after each change.

### Stage 7: replace, then remove

The legacy CLI transform loop, parallel target registries, duplicated
pre-routing, `GraphProgram`, and compatibility facades are removed. After a
derived scheduler replaces the remaining `CompileRequest.passes` control,
replace ordered-pass tests with:

- public Interface behavior tests;
- pass contract and invalidation tests;
- extension Adapter compatibility tests;
- deterministic scheduling/merge tests;
- target atomicity tests;
- receipt conservation tests;
- cold/warm phase gates.

Do not layer indefinitely. Compatibility is a temporary Adapter with a removal criterion.

## 15. Tradeoffs

The artifact DAG and contracts add up-front type and catalog machinery. That cost is justified because there are already several real pass-like stages, provider Implementations, frontend Implementations, packet targets, and transports. The Seam is no longer hypothetical.

A fully dynamic pass graph can make failures harder to understand. Counter this with an immutable compiled-pipeline fingerprint and a machine-oriented receipt containing chosen producers, artifact hashes, preserved analyses, costs, cache states, and omissions. Human narrative is optional; exact identifiers and compact structured receipts are primary.

Plugin freedom can harm determinism and latency. Catalog validation, purity declarations, capability negotiation, lazy import, explicit external-work policy, and contract enforcement constrain that risk.

Persisting `SourceIR` and analysis artifacts uses more disk. It should be bounded by content-addressed deduplication, per-artifact value measurements, and eviction based on recomputation cost. Query-time reparsing is the more expensive default for a resident context compiler.

Finally, a compiler abstraction must not obscure the fast path. Exact lookup remains a specialized derived pipeline with section-selective reads and minimal passes. It gains a receipt and shared invariants, not extra mandatory work.

## 16. Acceptance criteria

The architecture is successful when:

1. adding a pass requires one pass descriptor/Implementation and optional entry point, with no CLI/MCP/HTTP edits;
2. adding a target requires one atomic `TargetSpec`, with transport schemas generated from the catalog;
3. evidence, memory, trace, and frontend facts all enter through typed deltas into one canonical IR;
4. no transport performs routing, planning, pass dispatch, or cache-key derivation;
5. a compile is reproducible from snapshot, request, catalog fingerprint, and constraints;
6. every partial result explains omissions and conserved counts;
7. no optional external dependency is initialized on an unrelated cold path;
8. frontend parsing is reused across graph construction and evidence enrichment;
9. current exact-relation warm performance is preserved and cold phase costs are attributable;
10. legacy orchestration and parallel registries are removed, not merely wrapped forever.
