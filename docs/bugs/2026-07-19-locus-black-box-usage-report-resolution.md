# Locus Black-Box Usage Report — Remediation Retest

Date: 2026-07-19

This is a source-informed remediation and fresh black-box retest of
`2026-07-19-locus-black-box-usage-report.md`. The original report remains the
pre-fix observation record.

## Outcome

The six reported correctness failures were reproduced, fixed behind regression
tests, and checked against a newly built 11,021-node / 47,492-edge Locus graph.
The practical rating moves from **5.5/10 to 7.3/10**.

This is not a claim that GraphGraph is fully autonomous or that every retrieved
test is behaviorally affected. The material improvement is at the trust
boundary: bounded output now distinguishes a complete answer from a valid but
truncated slice, and emitted decisions are directly machine-readable.

## Acceptance retest

| Target | Result | Evidence |
| --- | --- | --- |
| `parse_to_ir` returns both real callees | PASS | Packet contains `locus_frontends::formula::parse` and `locus_engine::lift::lift_expr` |
| Eight-node reverse slice reports omission | PASS | 7/8 callers returned; `incomplete`; `omitted_direct_neighbors=1` |
| Exact `normalize_rust` command selects a test | PASS | Cargo ran exactly 1 test and it passed |
| `Expr` returns bounded ranked test candidates | PASS | 12 direct + 12 transitive returned; omitted candidate counts are explicit |
| Plain/JSON document validation agree | PASS | Both validate a 12-row `doc_summary`; JSON now exposes format/node/edge counts |
| Complete caller slice <=500 tokens | PASS | 10 nodes / 9 edges; 374 `cl100k`, 365 `o200k`, 309 proxy tokens |
| Warm exact query <500 ms with cache state | PASS | Persistent cache `hit`; reported query time 344 ms |
| All pipeline stages are returned | PASS | Stages 1 through 8 present in the 12-row document packet |

## Fixes

### Test selection and impact

- Inline Rust Cargo filters now use the exact graph test label rather than
  assuming a module named `tests`.
- Live verification treats exit code 0 plus zero selected tests as failure and
  records the selected-test count.
- Rust functions now receive conservative `references` edges to uniquely named
  types used in constructors, variants, parameters, and return positions.
- Affected-test receipts report omitted direct and transitive candidate counts.
  A capped result is `incomplete`, not silently `answerable`.

### Structural extraction and retrieval

- Rust `module::function(...)` calls retain their qualifier. Resolution scores
  the qualifier against crate/module paths and owner-qualified definitions.
- Single-identifier reverse lookups use the exact-symbol fast path.
- Direct reverse neighbors consume the budget before containment siblings.
- Returned direct neighbors are compared with known graph adjacency; any
  omission sets a truncation receipt and calibrated abstention.
- Relational words such as `call` are treated as query intent, not as entity
  facets requiring a node literally named “call.”

### Documents and validation

- The plain validator now reconstructs wrapped packet input from the exact
  marker line; a preceding blank line can no longer make a populated `[d]`
  packet appear empty.
- Enumerative stage/phase/step questions reserve the complete numbered sibling
  group, including when the anchor is the document file rather than one
  section.
- JSON validation exposes the same packet format and node/edge accounting as
  plain validation.

### LLM control plane and latency

- JSON now includes a fixed-order, self-contained `ggc1` control instruction:
  operation, state, next action, anchor mode, traversal, budget, actual graph
  size, packet cost, and six decision gates.
- Both detailed and compact JSON expose packet characters and proxy-token cost,
  eliminating ad hoc shell/JSON/tokenizer glue for routine decisions.
- Four encodings were benchmarked. Semantic IR was the smallest lossless,
  self-contained candidate. A shorter opcode form was rejected because it
  requires an external codebook.
- Volatile timing/build fields were removed from the persistent response-cache
  key. Receipts now say `cache=hit|miss`; an identical warm Locus query measured
  344 ms for the query phase.

## Recalibrated score

| Aspect | Before | Now | Critical assessment |
| --- | ---: | ---: | --- |
| Installation and availability | 6 | 6 | CLI is solid; project integration detection remains a separate concern |
| Exclusion and scan safety | 8 | 8 | Fresh Locus scan again honored pruning and ignore rules |
| Graph structural integrity | 8 | 8 | Fresh 11,021-node graph validated |
| Extraction quality | 5 | 6.5 | Qualified calls and type references improved; unresolved external/untyped calls remain substantial |
| Exact-symbol retrieval | 7 | 8.5 | Exact reverse slices are smaller and completeness-aware |
| Multi-hop architecture retrieval | 4 | 4.5 | Trust improved, but broad architecture ranking remains noisy |
| Affected-test discovery | 3 | 6.5 | Real candidates and exact commands now exist; `Expr` candidate volume is still overinclusive |
| Documentation retrieval | 4 | 8 | All eight requested stages are grouped and returned |
| Completeness detection | 3 | 8 | Known reverse adjacency and affected-test caps now produce omissions and abstention |
| Validation consistency | 4 | 8 | Plain and JSON share packet accounting |
| Token efficiency | 6 | 8 | Complete caller slice fell from 446 to 374 `cl100k` tokens |
| Query latency | 5 | 7.5 | Warm query phase is 344 ms; total one-shot CLI time was still about 719 ms |
| Receipts and observability | 8 | 9 | Control gates, cost, cache state, validation counts, and omissions are explicit |
| Freshness infrastructure | 7 | 7 | Clear scoped freshness; edit-refresh behavior was not the focus of this retest |
| Implementation trustworthiness | 4 | 6.5 | Safer for bounded implementation context, but source/test verification is still required |

Composite: **110 / 15 = 7.33**, rounded to **7.3/10**.

Practical interpretation:

- Replacement for broad source exploration: **7/10**
- Minimal-token exact-symbol navigator: **8.5/10**
- Autonomous implementation context provider: **6/10**
- Trustworthy test-impact system: **6.5/10**

## Remaining work

1. Improve broad architecture ranking and inferred multi-crate scope before
   expansion; historical audit prose still competes with production entry
   points.
2. Rank type-impact candidates by construction, match, signature, import, and
   transitive-only evidence instead of treating most direct type references
   alike.
3. Attach command-verification receipts to recommended commands when the caller
   explicitly authorizes execution; recommendations are exact by construction
   but unexecuted by default.
4. Reduce one-shot CLI total latency. Persistent response-cache hits meet the
   query-phase target, but graph discovery/load still costs several hundred
   milliseconds per new process.
5. Continue measuring comprehension/recall for evidence packet formats. The
   semantic control IR won deterministic cost gates; that result does not prove
   that an opaque evidence encoding would improve model reasoning.
