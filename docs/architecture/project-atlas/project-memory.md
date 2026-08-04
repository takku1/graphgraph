# AI-Native Project Memory Architecture

Status: accepted logical architecture with promoted GGB4 physical base. Direct
scanner-owned `FileDelta` emission remains future update-path work.

## Decision

GraphGraph should not make the persistent bytes "LLM-readable." An LLM cannot
efficiently inspect a database file, whether it is JSON, SQLite, or a custom
binary. The useful separation is:

1. a compact, exact, updateable machine store;
2. a typed retrieval algebra over that store;
3. a deterministic, token-budgeted AI interchange representation with source
   locations, provenance, freshness, and completeness receipts.

Any agent can understand the project quickly by using the public algebra and
receiving the interchange representation. It need not know the physical byte
layout. This lets the storage layer become aggressively binary without binding
GraphGraph to one model, tokenizer, embedding provider, or agent framework.

The recommended shape is therefore a compiled project-memory artifact with an
immutable packed base, small transactional deltas, relation-specific forward
and reverse adjacency, and derived views that are invalidated by revision. GGB4
is now the canonical physical source of truth.

## What "understanding a project" requires

Fast file search is necessary but not sufficient. A useful machine orientation
model must answer five different kinds of question:

| Facet | Examples | Required evidence |
| --- | --- | --- |
| Topology | What exists and where? | repository tree, ownership, containment |
| Behavior | What calls/uses/returns what? | typed code relations with confidence |
| Intent | Why does this exist? | docs, tests, names, commit/change evidence |
| Change | What can this edit affect? | forward/reverse dependencies and test links |
| Trust | Is this answer current and complete? | revision, extractor coverage, provenance receipts |

These are heterogeneous facts. Collapsing them into text chunks or one vector
loses exact identity and topology; retaining only syntax loses intent. The store
should preserve exact facts and expose several derived retrieval views rather
than force one representation to do every job.

## Logical architecture

```text
source files, docs, tests, manifests, VCS deltas, optional runtime traces
                              |
                       typed FileDelta
                              v
  +---------------- evidence plane ----------------+
  | identities | spans | facts | provenance | receipts |
  +------------------------------------------------+
              | deterministic derivation + invalidation
              v
  +--------------- derived-view plane -----------------+
  | exact names | lexical postings | CSR/CSC relations |
  | ownership | affected tests | atlas | optional vectors |
  +----------------------------------------------------+
                              |
                   typed retrieval algebra
                              v
  +--------------- AI interchange plane ---------------+
  | orient | search | expand | retrieve | explain       |
  | compact packets + stable IDs + evidence receipts    |
  +----------------------------------------------------+
```

### Evidence plane

The evidence plane stores lossless, model-independent claims:

- stable semantic entity ID and store-local numeric ID;
- entity type, path, byte/line span, parent, signature, and source revision;
- typed edges such as `contains`, `imports`, `calls`, `inherits`, `returns`,
  `tests`, `documents`, and `derived_from`;
- normalized frontend facts and unresolved/ambiguous obligations;
- evidence origin, extraction method, confidence, and validity interval;
- coverage and freshness receipts.

Summaries and embeddings are derived evidence, never replacements for source
facts. Every derived item records its algorithm/schema identity and input
revision so a reader can reject a stale view instead of silently mixing eras.

### Derived-view plane

Different queries deserve different physical views:

- exact qualified-name and path indexes for point resolution;
- relation-partitioned CSR/CSC spans for callers, callees, imports, ownership,
  and bounded traversals;
- file-to-owned-record maps for local invalidation and deletion;
- lexical postings for names, paths, signatures, docs, and tests;
- optional quantized semantic vectors as a candidate generator, never as an
  authority for identity or completeness;
- atlas/community summaries for coarse orientation;
- affected-test and blast-radius views backed by explicit evidence paths.

Each view is disposable. The base facts plus derivation version are sufficient
to rebuild it, and a view is readable only when its revision matches the query's
snapshot.

### AI interchange plane

The public interface is a small retrieval algebra rather than raw database
access:

```text
manifest()                         -> schema, capabilities, revision, coverage
orient(scope, budget)              -> project atlas and entry points
search(terms, kinds, scope)        -> stable candidate identities
expand(ids, relations, dir, hops)  -> bounded typed subgraph
retrieve(ids, detail)              -> fold, preview, or exact source spans
explain(ids_or_path)               -> evidence paths and derivation receipts
diff(rev_a, rev_b, scope)          -> changed facts and invalidated views
```

The rendered `#gg` packet is an AI intermediate representation, not the storage
format. It should remain deterministic, dictionary-code repeated relations and
identities, preserve direction and source coordinates, and conclude with a
machine-checkable receipt. JSON remains available as a verbose interoperability
format; compact `gg` is selected only when it is identity-safe and actually uses
fewer measured tokens.

## Candidate physical format

The promoted sectioned GGB4 format is self-describing at the section level but
is not intended for manual editing:

```text
superblock
  magic, schema, feature bits, repository UUID, revision
  extractor identity, section-directory offset, whole-store checksum

schema
  entity kinds, relation kinds, column descriptors, derivation identities

strings
  deduplicated UTF-8 blocks + offsets + exact candidate index

entities
  column blocks: semantic ID, label, kind, path, span, parent, validity

facts_and_evidence
  typed payloads, provenance, confidence, source span, unresolved status

adjacency[relation]
  forward offsets/targets and reverse offsets/sources, numeric IDs

indices
  qualified names, paths, ownership, lexical postings, optional vector refs

views
  atlas, summaries, affected tests, relation cardinalities, coverage receipts

directory_and_checksums
  offset, encoded length, decoded count, codec, checksum per section
```

Sections can be read independently. Numeric IDs make adjacency compact; stable
semantic string IDs remain the external contract. Compression is selected per
section only when decompression plus I/O beats the uncompressed control. Memory
mapping is limited to immutable sections and is benchmarked against ordinary
buffered reads rather than assumed to be faster.

## Update architecture

The scanner should emit a `FileDelta` directly. Recovering a tiny edit by
comparing two fully materialized graphs is the wrong asymptotic algorithm.

```text
FileDelta = {
  file identity and old/new content revision,
  owned additions/removals/tombstones,
  changed binding and type-fact keys,
  new unresolved obligations,
  affected derived-view keys,
  frontend coverage delta
}
```

Committed deltas use a typed append-only segment with base revision,
transaction ID, record count, payload checksum, resulting revision, and commit
trailer. Readers accept only a continuous chain of complete committed segments.
Compaction merges levels when measured future replay and fragmentation cost
exceeds rewrite cost; record count alone is a safety ceiling, not the optimizer.

For a view (v), invalidation follows the dependency graph from changed base
keys (\Delta K). Non-recursive joins use affected-key recomputation. Recursive
views use semi-naive or differential maintenance only where benchmarks justify
their memory cost.

## Replace guessed constants with measured policies

Correctness constraints are absolute: exact equivalence, revision matching,
crash atomicity, and complete evidence receipts do not become trade-offs.
Performance decisions use workload equations.

For candidate (c) over a horizon of queries (Q) and updates (U):

\[
J(c)=\sum_{q\in Q}w_q[L_0(q)-L_c(q)]
     -\sum_{u\in U}w_u C_c(u)
     -\lambda_B\Delta B_c-\lambda_R R_c.
\]

Promote only when a preregistered confidence bound for (J(c)) is positive and
all correctness constraints pass. Here (L) is end-to-end latency by cold/warm
state, (C) is update/compaction cost, (\Delta B) is additional persistent
and peak memory, and (R) is an explicit operational-risk score.

The read/update break-even point is measured, not guessed:

\[
Q^*=\frac{C_{build,c}}{L_0-L_c}.
\]

Update locality is a scaling property rather than a `100 ms` magic number. Fit

\[
T_{update}(N,\Delta)=\alpha+\beta\Delta+\gamma N
\]

across repository and edit sizes. A truly incremental candidate has negligible
(\gamma) within the confidence interval. A fast full rebuild remains (O(N))
and is not mislabeled incremental merely because one repository is small.

Context selection is a constrained utility problem. For token budget (B), pick
evidence set (S) maximizing relevance, facet coverage, path continuity, and
trust while penalizing redundancy:

\[
\max_{S:\sum t_i\le B}
\left(\sum_{i\in S}r_i+\lambda C(S)+\mu P(S)+\nu T(S)-\rho D(S)\right).
\]

When measured utility is approximately monotone submodular, use a marginal
utility-per-token greedy policy and report the achieved facets. Otherwise use a
bounded beam/knapsack planner. Budgets, hop depths, and candidate counts remain
explicit resource/SLO settings; they are never presented as universal constants.

## Measured canonical GGB4 result

The standalone SQLite and GGR1 experiments established that packed numeric
adjacency was useful but duplicate sidecar storage was not. GGB4 incorporates
the winning physical shape into one canonical file: separate identity, detail,
full-edge, PageRank, and exact-call sections with a directory and CRC32 per
section. Exact relations read only identity and call sections; full consumers
retain the compatibility `Graph` adapter.

On the promoted repository snapshot (13,804 nodes, 50,619 edges), 15 matched,
order-alternating fresh-process trials produced:

| Metric | GGB3 | GGB4 |
| --- | ---: | ---: |
| Exact graph/relation fidelity | yes | yes |
| Bytes | 6,801,568 | 7,481,238 |
| Full cold median | 408.059 ms | 416.113 ms |
| Exact-relation cold median | 453.689 ms | 246.339 ms |
| Exact-relation warm median | 10.023 ms | 5.429 ms |
| Paired full-load median ratio, 95% upper bound | — | 1.023x, 1.035x |
| Paired relation median ratio, 95% upper bound | — | 0.543x, 0.557x |

GGB4 passed every preregistered promotion gate. The decision uses a
distribution-free one-sided 95% bound for each paired median ratio, avoiding a
promotion decision based on one small-sample tail outlier. It is now the only
native writer. GGB3/GGB2 remain read-only migration inputs; standalone relation
stores and their revision-coupling machinery were removed. The harness and raw result
are under `benchmarks/context_graph/canonical_storage_tournament.py` and
`benchmarks/context_graph/out/canonical_storage_tournament/`.

## Research implications

- LocAgent represents repositories as heterogeneous file/class/function graphs,
  exposes search/traverse/retrieve operations, and reports that output graph
  format affects localization. This supports separating stored facts from a
  task-shaped AI interchange representation.
- CoSIL's ablations report losses when module-call structure, iterative graph
  search, or pruning is removed. This supports call/import topology plus
  budget-aware iterative expansion rather than one giant context dump.
- BACH bridges mutable adjacency and read-optimized CSR through LSM levels. The
  relevant lesson for GraphGraph is a small mutable delta plus compact immutable
  levels, not adopting a distributed graph database.
- Succinct `k²`-tree work shows that graphs can be navigated while compressed,
  but code graphs are typed, attributed, modest in size, and frequently updated.
  CSR/CSC plus dictionary coding is the simpler control; succinct matrices earn
  adoption only if measured size pressure dominates.
- SQLite's own documentation recommends measuring `WITHOUT ROWID` late rather
  than assuming it helps. The local SQLite result makes the same broader point:
  a robust generic engine may win latency yet lose the actual footprint/update
  objective.

## Current sequence

1. GGB4 base writer, full reader, and exact-relation partial reader: promoted.
2. GGB3/GGB2 readers: migration-only until compatibility policy retires them.
3. Existing append-only delta: retained because it is already crash-safe and
   its append is genuinely proportional to the changed records.
4. Next optimization: emit `FileDelta` from extraction and prove equivalence to
   full diff; fit (\gamma) in the update-scaling model.
5. Extend section-selective reads to atlas/search only when workload evidence
   shows another full-materialization bottleneck.

## Primary sources

- Chen et al., [LocAgent: Graph-Guided LLM Agents for Code
  Localization](https://arxiv.org/abs/2503.09089), 2025.
- Jiang et al., [CoSIL: Software Issue Localization via LLM-Driven Code
  Repository Graph Searching](https://arxiv.org/abs/2503.22424), 2025.
- Miao et al., [BACH: Bridging Adjacency List and CSR Format using
  LSM-Trees](https://www.vldb.org/pvldb/vol18/p1509-miao.pdf), PVLDB 2025.
- Levandoski, Sengupta, and Lomet, [LLAMA: A Cache/Storage Subsystem for Modern
  Hardware](https://www.vldb.org/pvldb/vol6/p877-levandoski.pdf), PVLDB 2013.
- Brisaboa, Ladra, and Navarro, [Compact Representation of Web Graphs with
  Extended Functionality](https://doi.org/10.1016/j.ipm.2013.08.003), 2014.
- Acar, [Self-Adjusting
  Computation](https://www.cs.cmu.edu/~rwh/students/acar.pdf), 2005.
- Szabó, [Incrementalizing Production CodeQL
  Analyses](https://arxiv.org/abs/2308.09660), 2023.
- SQLite, [WITHOUT ROWID](https://www.sqlite.org/withoutrowid.html) and
  [Write-Ahead Logging](https://www.sqlite.org/wal.html), official documentation.
