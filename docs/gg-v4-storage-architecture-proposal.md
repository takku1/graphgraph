# `.gg` v4 Incremental Store: Architecture Proposal

Status: experimental design, not a format commitment.  GGB3 remains the native
store until a candidate passes the workload and migration gates below.

## Decision summary

Do not replace `.gg` with a generic database by assumption.  Preserve the
serverless compiled-artifact model and run a four-way tournament:

1. current GGB3 plus JSON delta sidecar;
2. sectioned GGB4 plus binary write-ahead delta segments;
3. indexed SQLite/WAL;
4. current store plus a narrow persistent relation-index sidecar.

The likely design is an immutable, sectioned base with small append-only binary
deltas and derived relation indices.  It matches a workload dominated by
read-only exact adjacency and bounded traversals while allowing cheap local
updates.  SQLite becomes preferable if ad-hoc predicates, concurrent
transactions, or secondary-index maintenance dominate in measurement.

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

## Candidate D: narrow persistent relation index

The smallest experiment is a sidecar containing:

- exact qualified-symbol to numeric-node candidates;
- forward and reverse relation-coded adjacency;
- node label/path/line/kind columns needed by the relation micro-IR;
- base and delta revision fingerprints.

This can make cold one-hop queries independent of full GGB3 loading without a
format migration.  It is the preferred first prototype because it tests the
main storage hypothesis with low blast radius and a trivial rollback.

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

### Operational

- no daemon and no network requirement;
- works on supported Windows/Linux filesystems and in sandboxes;
- bounded compaction latency with an explicit interruption story;
- old stores remain readable through migration, never guessed in place;
- doctor/status exposes base revision, delta depth, index revisions, and repair
  actions.

## Recommended implementation order

1. Build the storage workload harness and capture GGB3 profiles.
2. Make the scanner emit `FileDelta`; compare it against full graph diffs without
   changing persistence.
3. Prototype Candidate D, the relation-index sidecar.
4. Prototype section-directory reads and binary deltas as an experimental GGB4.
5. Implement the indexed SQLite control with the same logical API.
6. Run correctness, crash, cold/warm, update-scaling, and footprint tournaments.
7. Promote only the smallest candidate that materially reduces end-to-end
   navigation cost.  If Candidate D wins, do not migrate the base format.

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

