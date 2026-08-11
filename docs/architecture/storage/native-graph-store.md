> **Academic title:** Native Graph Store Architecture  
> **Legacy name:** gg-v4-storage-architecture-proposal  
> **Subsystem:** [SYSTEM.md](./SYSTEM.md)

# `.gg` v4 Sectioned Store: Accepted Architecture

Status: promoted 2026-08-02. GGB4 is the sole native writer. GGB3/GGB2 remain
read-only migration inputs; standalone SQLite/GGR1 sidecars were removed after
their packed-adjacency behavior moved into the canonical file.

## Decision summary

Use one serverless compiled artifact: a sectioned GGB4 base with shared string
dictionaries, full-fidelity records, per-section checksums, and embedded packed
call adjacency. Keep the crash-safe append-only delta for edit-loop updates and
fall back to full materialization when an unapplied delta exists. Do not maintain
a generic database or duplicate relation sidecar.

## Current store and measured constraint

GGB3 is a full-fidelity, dictionary-coded sequential encoding of nodes, edges,
metadata, facts, and cached PageRank.  `load_graph_binary` reads the entire file
and materializes Python `Graph`, `Node`, and `Edge` objects.  The promoted delta
sidecar is crash-tolerant and append-only, but records JSON payloads and replay
still produces a complete in-memory graph.

The current delta documentation states the important complexity honestly:

- append is \(O(\Delta)\);
- deriving a delta by comparing two materialized graphs is \(O(N)\);
- full validation is \(O(N)\);
- loading is \(\Theta(N)\) because every consumer materializes the graph;
- replay is \(O(E+\Delta)\) per delta record after the single-pass fix.

Therefore the next storage question is not "can appending be faster?" It already
is.  The question is whether exact queries and updates can avoid full graph
materialization, whole-graph diffing, and whole-graph validation.

## Workload model

Measure each candidate against the operations GraphGraph actually performs:

| Operation | Expected frequency | Access shape |
| --- | ---: | --- |
| Exact symbol resolution | Very high | point lookup, small row |
| One-hop callers/callees | Very high | point lookup plus contiguous adjacency |
| Bounded multi-hop traversal | High | sparse neighborhood scans by relation |
| Ranked broad retrieval | Medium | symbol/text index plus selected graph access |
| Whole-repository predicate | Medium | column/filter scan or maintained index |
| One-file update/delete | High in edit loop | small write set, affected-key rejoin |
| Full scan/compaction | Low | sequential bulk write |
| Validation/status | High | metadata and local invariant checks; periodic full scan |
| Temporal snapshot/diff | Low/medium | versioned records and sequential change scan |

Benchmark small, medium, and large repositories and cold, warm, and resident
process states.  A storage choice that improves billion-edge graph workloads
but regresses 10k-node interactive projects is the wrong choice.

## Candidate A: retain GGB3 plus JSON deltas

This is the control and may remain the winner.

Advantages:

- smallest migration and correctness risk;
- proven atomic base rewrite and torn-tail tolerance;
- compact sequential full loads;
- zero new runtime dependency.

Limits:

- no section directory or random record access;
- no persisted forward/reverse adjacency index;
- delta JSON repeats field names and strings;
- exact relation cold path may still pay full materialization;
- writer derives changes from whole graphs rather than scanner-owned deltas.

## Candidate B: sectioned GGB4 with binary delta log

### Base layout

```text
superblock
  magic/version/endian/features
  repository UUID and graph revision
  extractor/schema identities
  section directory: kind, offset, length, count, checksum

dictionary
  block-compressed UTF-8 strings
  offset table and optional hash-to-candidate index

nodes
  stable numeric ID
  column blocks for kind/path/label/summary/facts/provenance/validity

edges_forward
  CSR-like offsets by source, then relation, then target

edges_reverse
  CSC-like offsets by target, then relation, then source

indices
  exact symbol/path index
  relation/cardinality index
  file-to-owned-record index
  optional lexical postings and atlas index

receipts
  frontend coverage, unresolved shapes, exclusions, freshness, validation

checksums
  per-section checksum plus whole-directory checksum
```

Numeric IDs are store-local and stable until compaction.  Externally visible
semantic IDs remain strings.  A compaction emits an old-to-new numeric ID map
for sidecars and invalidates any index whose schema/revision does not match.

### Read path

- Read the superblock and section directory first.
- For exact relations, load or map only dictionary candidates, symbol index,
  node rows, and the requested forward/reverse adjacency span.
- For broad planning, construct a lazy `GraphView` over column and adjacency
  sections.  Materialize Python objects only for selected nodes/edges.
- Preserve the existing full `Graph` adapter for compatibility and validation.

Memory mapping is a candidate for immutable base sections only.  The CIDR paper
"Are You Sure You Want to Use mmap in Your Database Management System?" warns
against treating `mmap` as a complete buffer manager.  GraphGraph can avoid the
most dangerous case by never mutating mapped pages, keeping writes append-only,
and retaining ordinary buffered I/O as a benchmark control.

### Delta log

Replace JSON delta records with a typed binary segment:

```text
segment header:
  magic, schema version, base revision, transaction ID,
  record count, byte length, checksum

records:
  string intern, node upsert/tombstone, edge upsert/tombstone,
  fact/provenance update, receipt update, index delta

commit trailer:
  transaction ID, resulting revision, checksum
```

Readers accept only complete committed segments whose base/result revision chain
is continuous.  A torn tail is ignored.  Writers serialize through the existing
single-writer lock, append and flush the segment, then atomically publish the
new current revision.  The immutable base remains the last compact checkpoint.

### Direct scanner deltas

Introduce a typed `FileDelta` emitted by extraction:

```text
file identity + old/new content revision
owned node/edge/fact removals
owned node/edge/fact additions
changed binding keys and deferred obligations
affected derived-view keys
frontend coverage delta
```

The writer must not recover this information through `GraphDelta.between` in
the normal path.  Full diff remains an audit oracle used to prove equivalence.

### Incremental derived views

Maintain a dependency/invalidation graph from base facts to:

- receiver/type joins;
- forward/reverse adjacency spans;
- exact symbol/path postings;
- relation counts and completeness telemetry;
- project-atlas communities/labels;
- lexical/semantic sidecars.

Use affected-key rejoin for local relations and semi-naive/differential
maintenance for recursive derived facts.  Differential computation can maintain
recursive graph queries under updates, but published work also documents high
memory cost; it should be a targeted engine for derived views, not automatically
the store's universal execution model.

### Compaction

Replace only fixed record-count thresholds with a measured cost policy:

\[
\text{compact when }\quad
E[C_{replay}(D,q)]\,Q_{horizon}
+ C_{fragmentation}(D)
> C_{rewrite}(N)+C_{migration}(D).
\]

Keep hard safety ceilings for delta bytes, record count, and revision depth.
Compaction writes a complete new base to a sibling temporary file, validates it,
atomically swaps it into place, and retires only deltas included in the published
revision.

## Candidate C: SQLite/WAL

Prototype a normalized schema rather than comparing `.gg` with an unindexed
generic table:

```sql
nodes(id TEXT PRIMARY KEY, numeric_id INTEGER UNIQUE, ...)
edges(source_id, relation_id, target_id, source_location, ...,
      PRIMARY KEY(source_id, relation_id, target_id, source_location))
edge_reverse(target_id, relation_id, source_id, source_location, ...)
file_ownership(path, record_kind, record_id, ...)
strings(id INTEGER PRIMARY KEY, value TEXT UNIQUE)
receipts(key TEXT PRIMARY KEY, value BLOB)
```

Evaluate ordinary integer-rowid layouts and `WITHOUT ROWID` only where composite
keys are genuinely the clustered lookup path.  SQLite's own documentation
recommends measuring this optimization rather than assuming it helps.  WAL
offers concurrent readers with one writer and crash recovery, but introduces
checkpoint behavior and extra files that must fit sandbox and network-filesystem
constraints.

SQLite is favored if:

- `select` grows into varied predicates and aggregations;
- transactional multi-index updates dominate engineering complexity;
- partial reads beat custom section access after process startup is included;
- size and cold relation latency remain within product gates.

It is rejected if SQL row/index overhead or Python result materialization erases
the gains on the dominant exact-adjacency workload.

## Historical Candidate D: narrow persistent relation index

The smallest experiment is a sidecar containing:

- exact qualified-symbol to numeric-node candidates;
- forward and reverse relation-coded adjacency;
- node label/path/line/kind columns needed by the relation micro-IR;
- base and delta revision fingerprints.

This can make cold one-hop queries independent of full GGB3 loading without a
format migration.  It is the preferred first prototype because it tests the
main storage hypothesis with low blast radius and a trivial rollback.

### Prototype tournament result (2026-08-02)

Two revision-coupled prototypes now exist: a normalized SQLite sidecar and the
custom packed `GGR1` sidecar. On the current 13,383-node/49,343-edge repository
snapshot, both returned byte-for-byte equivalent result objects for the sampled
relation workload and rejected revision mismatches.

| Metric | GGB3 | SQLite | GGR1 |
| --- | ---: | ---: | ---: |
| Cold p95, ten-query workload | 463.354 ms | 188.991 ms | 222.433 ms |
| Warm median | 8.360 ms | 17.029 ms | 2.891 ms |
| Combined/control storage | 1.000x | 2.468x | 1.322x |
| Full sidecar rebuild p95 | n/a | 282.643 ms | 121.789 ms |

Neither standalone sidecar was promoted. Their result selected the physical
idea—dictionary-coded numeric adjacency—which was then embedded into GGB4 so it
does not duplicate canonical identities or require cross-file revision coupling.

The broader logical/physical design and formulas replacing guessed policy
constants are in [AI-Native Project Memory
Architecture](../project-atlas/project-memory.md).

### Canonical GGB4 promotion result

The final tournament used 15 matched, order-alternating cold trials on the same
13,804-node/50,619-edge logical graph for both formats. Promotion uses a
distribution-free, one-sided 95% confidence bound for the paired median ratio;
the reported p95 remains descriptive and is not treated as a stable estimator
from a small sample:

| Metric | GGB3 | GGB4 |
| --- | ---: | ---: |
| Full fidelity | yes | yes |
| Bytes | 6,801,568 | 7,481,238 |
| Full cold median | 408.059 ms | 416.113 ms |
| Exact-relation cold median | 453.689 ms | 246.339 ms |
| Exact-relation warm median | 10.023 ms | 5.429 ms |
| Paired full-load median ratio, 95% upper bound | — | 1.023x, 1.035x |
| Paired relation median ratio, 95% upper bound | — | 0.543x, 0.557x |

GGB4 passed exact fidelity, <=1.15x footprint, a <=1.05x upper confidence bound
for full-load regression, and a <0.75x upper confidence bound for direct-relation
cold time. The reproducible harness is
`benchmarks/context_graph/canonical_storage_tournament.py`.

## Validation model

Incremental validation must preserve, not weaken, the current safety contract.

### Commit-time local checks

- revision chain and checksums;
- unique semantic IDs and valid numeric IDs;
- edge endpoints exist after the transaction;
- ownership deletes cannot remove another file's evidence;
- touched adjacency/index entries equal the committed record set;
- frontend and manifest revisions advance transactionally.

### Periodic/full checks

- complete forward/reverse adjacency equivalence;
- full graph structural validation;
- derived-view recomputation equivalence;
- full-scan versus incremental logical equality;
- orphaned string/index/ownership records;
- compaction and migration round trips.

Completeness-required queries must refuse strong claims if the store reports an
unvalidated revision or an index/base mismatch.

## Crash and concurrency matrix

Inject failure after every persistence boundary:

1. before segment append;
2. during header, payload, and trailer writes;
3. after flush but before revision publication;
4. during manifest publication;
5. during compaction base write;
6. after base swap but before delta retirement;
7. while a reader holds the previous revision;
8. during process termination on Windows and Linux.

After restart, the visible state must be exactly the old revision or the new
revision—never a mixture.  Readers should use immutable revision snapshots;
same-store writes remain serialized unless a real multi-writer requirement is
demonstrated.

## Tournament gates

### Correctness

- full/incremental logical equivalence on additions, edits, renames, and deletes;
- exact relation results identical across all candidates;
- 100% survival of the crash matrix;
- deterministic rebuild and compaction signatures;
- GGB3 migration and rollback proven on all saved benchmark graphs.

### Performance

- resident one-hop relation below `50 ms` p95 (expected to be much lower);
- cold relation below `200 ms` p95 including process and index opening;
- no-op update below `100 ms` p95;
- one-file update cost grows with affected records, not total corpus size;
- broad query does not regress by more than 5% latency at equal output;
- store plus mandatory indices no more than 1.5x the GGB3 control unless a
  preregistered navigation-utility gain justifies it.

These are preregistered product gates for this tournament, not claims of
universal mathematical constants. Preserve them when interpreting the current
experiment. For subsequent designs, additionally report the amortized
break-even query count
(Q^*=C_{build}/(L_{control}-L_{candidate})), and fit
(T_{update}(N,\Delta)=\alpha+\beta\Delta+\gamma N). Incremental locality
requires negligible measured (\gamma); passing an absolute millisecond gate on
one repository is not enough.

### Operational

- no daemon and no network requirement;
- works on supported Windows/Linux filesystems and in sandboxes;
- bounded compaction latency with an explicit interruption story;
- old stores remain readable through migration, never guessed in place;
- doctor/status exposes base revision, delta depth, index revisions, and repair
  actions.

## Implementation status and remaining work

Completed:

1. GGB3 control, SQLite sidecar, and packed GGR1 prototype tournaments.
2. Sectioned GGB4 full-fidelity writer/reader and packed exact-relation reader.
   New stores embed identity-string offsets, a stable hashed exact-symbol index,
   and forward/reverse call-offset arrays. Exact queries decode only the target
   and returned adjacency span rather than materializing every relation node,
   call object, and adjacency dictionary.
3. Per-section CRCs, atomic writes, legacy GGB3/GGB2 migration reads, and delta
   correctness fallback.
4. CLI, MCP, and unified-query routing through the canonical partial reader.
5. Removal of both standalone sidecar implementations and their duplicate tests.

On the 2026-08-08 self-graph (15,402 nodes / 57,924 edges), the packed reader's
in-process exact caller lookup measured **3.81 ms p50** versus **57.08 ms p50**
for the compatibility relation-view materialization path (15.0x faster). Fresh
CLI subprocess p50 fell from roughly 280 ms to 226.5 ms; Python/process startup
still dominates that transport. See the
[measurement receipt](../../evaluation/graybox-cycles/2026-08-08-packed-relation-cold-path.md).

Remaining: make the scanner emit `FileDelta` directly and fit the update-scaling
model. The existing delta append remains crash-safe and cheap; the remaining
non-local cost is graph diff/validation, not the canonical GGB4 byte layout.

## Primary research basis

- Acar, [Self-Adjusting Computation](https://www.cs.cmu.edu/~rwh/students/acar.pdf),
  dynamic dependence graphs and change propagation.
- Szabó, [Incrementalizing Production CodeQL
  Analyses](https://arxiv.org/abs/2308.09660), 2023.
- Ammar et al., [Optimizing Differentially-Maintained Recursive Queries on
  Dynamic Graphs](https://arxiv.org/abs/2208.00273), 2022.
- Miao et al., [BACH: Bridging Adjacency List and CSR Format using
  LSM-Trees](https://www.vldb.org/pvldb/vol18/p1509-miao.pdf), PVLDB 2025.
- Levandoski, Sengupta, and Lomet, [LLAMA: A Cache/Storage Subsystem for Modern
  Hardware](https://www.vldb.org/pvldb/vol6/p877-levandoski.pdf), PVLDB 2013.
- Crotty et al., [Are You Sure You Want to Use mmap in Your Database Management
  System?](https://vldb.org/cidrdb/2022/are-you-sure-you-want-to-use-mmap-in-your-database-management-system.html),
  CIDR 2022.
- SQLite, [Write-Ahead Logging](https://www.sqlite.org/wal.html) and [WITHOUT
  ROWID](https://www.sqlite.org/withoutrowid.html) official documentation.
