# Packed exact-relation cold path

**Date:** 2026-08-08  
**Scope:** GGB4 exact callers/callees only  
**Repository:** GraphGraph self-graph after a full non-incremental Tree-sitter +
docs scan

## Question

Why did one exact relation query still spend tens of milliseconds inside
GraphGraph when the requested result was one small adjacency slice?

The accepted GGB4 design called for point lookup plus contiguous forward or
reverse adjacency. The implementation loaded only relation-related sections,
but then decoded all 30k identity strings, materialized every active
`RelationNode` and every `RelationCall`, and constructed complete incoming and
outgoing dictionaries. It was section-selective I/O followed by whole-view
materialization.

## Change

New GGB4 writes add five derived hot-path sections while retaining the
full-fidelity sections and the legacy `CALL` reader contract:

- `IDOF`: offsets into the identity string dictionary;
- `XIDX`: sorted stable 64-bit hashes for exact IDs, normalized labels, and
  normalized paths, with collision verification against stored values;
- `COFF`: outgoing CSR-style call offsets over source-sorted `CALL` rows;
- `CIN0`: target-sorted call rows;
- `CIOF`: incoming CSC-style call offsets.

The packed reader retains raw checked section buffers, binary-searches `XIDX`,
decodes only matching/returned node fields, and visits only the selected call
span. Older GGB4 files fall back to the compatibility materialized view;
applicable deltas still force the existing full-fidelity path.

## Correctness gates

- Packed saved queries are byte-for-byte data-equivalent to resident
  `query_relations` across callers, callees, filters, limits, details, freshness,
  qualified names, and misses.
- A regression test replaces the compatibility view loader with a throwing
  sentinel and proves new stores do not invoke it.
- Existing selective-corruption, full-load fidelity, legacy migration, delta
  fallback, and atomic-write tests pass.
- Focused command:
  `python -m pytest tests/test_sectioned_storage.py tests/test_query_compiler.py -q`
  — 20 passed.

## Measurement

Graph after rebuild:

- 15,402 nodes;
- 57,924 edges;
- 7,549 deduplicated call rows;
- 9,714,696-byte GGB4 file.

In-process A/B, nine repetitions on the same file with OS cache warm but a new
reader each repetition:

| Reader | min | p50 | p95 |
| --- | ---: | ---: | ---: |
| Compatibility materialized relation view | 54.674 ms | 57.083 ms | 67.098 ms |
| Packed index/span reader | 3.559 ms | 3.810 ms | 5.288 ms |

The packed path is **15.0x faster at p50** for this query.

Fresh console-script subprocess, nine repetitions:

| Path | min | p50 | max/p95 sample |
| --- | ---: | ---: | ---: |
| `graphgraph relations retrieve_context --direction callers` | 219.8 ms | 226.5 ms | 245.1 ms |

Before the packed change, a comparable seven-run sample measured about 280.4
ms p50, and the relation receipt attributed 57.132 ms inside GraphGraph. After
the change the receipt attributed 4.382 ms. The subprocess samples were taken
at different moments and are sensitive to Windows process/antivirus scheduling,
so the in-process paired A/B is the stronger engine measurement.

## Interpretation

The result validates the architecture's packed point-lookup direction and
falsifies the assumption that merely separating file sections is sufficient.
Object materialization was the dominant engine term. The remaining fresh-CLI
floor is primarily Python/process startup, so interactive agents should still
use the resident MCP/compiler transport.

This does **not** close latency/scale invariance. Required follow-up includes
small/medium/large repository strata, cold filesystem cache where feasible,
non-call exact operators, broad retrieval phases, update locality, and resident
p95 gates.
