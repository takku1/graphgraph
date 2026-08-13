# Correction — OW-AC-03 semantic-store candidate

## Prior decision

REVERT `430a64dbafd871fddeaaeed737997c38be57f554`.

## Negative Pattern

> Removing the lexical-strength and cold-backend vetoes made a current dense
> index reachable, but exposed the existing 53.9 MB JSON/Python-dict index on
> every cold non-exact query. The observed cold query was 10.812 s against the
> 3.000 s hard gate. JSON index loading alone took 4.5335 s. All six admitted
> semantic seeds were prose and the packet remained incomplete/abstained.
> Test-green reachability is not a shippable semantic default unless the index
> representation and category-aware query interface satisfy the cold SLO and
> return implementation evidence.

Do not retry the invalidated approach by restoring either veto, increasing the
global semantic-query multiplier, weakening the latency gate, or forcing
`--source-mode all`.

## Localized repair seam

Deepen `platform/semantic.py::SemanticIndex` into a semantic-store interface
that owns graph/backend compatibility, atomic publication, a memory-mapped
dense representation, legacy/hash compatibility, category-aware top-k, phase
receipts, and exact invalidation. `QuerySourcePlanner` consumes one balanced
result and does not own storage, warmness, multiplier, or kind-partition policy.

## Sampled prototype evidence

Prototype branch `prototype/ow-ac-03-semantic-store`, commit `d49e2b8`:

- 13,377 × 384 float32 vectors: 20.55 MB.
- Memory-map open: 4.2 ms versus 4,533.5 ms JSON decode.
- Cold embed plus vectorized scan: 1,089.1 ms.
- Balanced top-6: three code symbols and three prose nodes although the first
  code symbol was rank 77 globally.

This validates the data shape only. Atomic publication, compatibility, hash-only
installs, end-to-end latency, and retrieval quality remain unverified.
