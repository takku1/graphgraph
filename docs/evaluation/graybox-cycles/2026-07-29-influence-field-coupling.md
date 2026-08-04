# The influence field, not the cover formula, is the failing stage

`EXP-GPA-COUPLING` · claim `GPA-FIELD-COUPLING-001` · 2026-07-29

Phase 1 rejected the C1 multiresolution cover formulas on real projects, and
the formula sweeps that followed rejected the whole coefficient family. Both
verdicts assumed the influence field feeding those covers carried mass worth
distributing. It does not.

## What was measured

The hierarchy, tasks, seeds, budgets, and metrics were held fixed at their
Phase 1 values (six tasks per project, damping `0.85`, `max_iter 30`,
`tol 1e-7`). Only the edge coupling used to diffuse the query-conditioned field
was exchanged. A field is called **degenerate** when its median per-task
support fraction falls below `0.10` — fewer than that share of project entities
carry any query-conditioned mass, so no far-field representation has anything
to encode.

| project | coupling | median support | median mass outside top-64 | effective entities | degenerate |
| --- | --- | ---: | ---: | ---: | :---: |
| chess | directed | 0.0221% | 0.000e+00 | 1.0 | **YES** |
| chess | reverse | 25.1827% | 4.748e-01 | 197.4 | no |
| chess | symmetric | 98.9369% | 6.247e-01 | 464.6 | no |
| express | directed | 0.0291% | 0.000e+00 | 1.0 | **YES** |
| express | reverse | 37.6820% | 2.591e-01 | 73.4 | no |
| express | symmetric | 98.4566% | 4.984e-01 | 374.9 | no |
| graphgraph | directed | 0.0107% | 0.000e+00 | 1.0 | **YES** |
| graphgraph | reverse | 30.2637% | 4.495e-01 | 215.9 | no |
| graphgraph | symmetric | 99.9464% | 6.501e-01 | 819.8 | no |
| requests | directed | 27.4764% | 3.348e-01 | 80.1 | no |
| requests | reverse | 0.1493% | 0.000e+00 | 3.0 | **YES** |
| requests | symmetric | 99.2534% | 4.912e-01 | 211.4 | no |

| coupling | degenerate projects | worst median support | median mass outside top-64 |
| --- | ---: | ---: | ---: |
| directed (incumbent) | **3/4** | 0.0107% | 0.000e+00 |
| reverse | 1/4 | 0.1493% | 4.495e-01 |
| symmetric | **0/4** | 98.4566% | 6.247e-01 |

Reproduce with `python benchmarks/context_graph/global_attention_phase2_coupling.py`.

## Mechanism

Personalized PageRank follows edge direction, so an entity receives mass only
along a directed path from a seed. In the live GraphGraph graph **62.9% of
active entities (5,871 of 9,328) have zero out-edges** — documentation
paragraphs, concepts, and leaf callees are all directed sinks. The graph is
99.97% connected when read undirected (9,325 of 9,328 mutually reachable), but
forward reachability from a degree-576 node is 42 nodes.

The consequence is visible in production. Compiling the shipped
`hybrid_reserve_v1` representation against the live graph yields:

```
exact_mass 1.0   aggregate_mass 0.0   refinements 0   aggregate_cells 1
~K project n=9281 m=0 k=paragraph:3937,function:1650,concept:1146
```

98.8% of the project is represented by a single line reporting mass zero. The
far field is not badly approximated; it is empty.

## What this does and does not license

It **does** invalidate the interpretation of `EXP-GPA-C1-P1` and
`EXP-GPA-C1-FORMULA-SWEEPS` as tests of cover formulas. On three of four
projects those experiments compared formulas over a field with zero mass
outside the exact frontier. No formula can distribute mass that does not exist,
so the measurements cannot isolate the formula.

It **does not** explain the recorded pass/fail split. GraphGraph passed C1 at
0.0107% support while Chess failed at 0.0221% — degeneracy does not track the
verdict, so no causal claim is made about *why* individual projects failed.

It also contradicts the governing definition `GPA-DEF-001` at the substrate
level: "every entity contributes a nonzero, query-conditioned influence" is
false for 99.99% of entities under the incumbent coupling, before any
representation choice is made.

## Consequences

1. `F1-SYMMETRIC-COUPLING` is registered as `measured` and is the first
   candidate to clear a substrate gate on every project.
2. `C1` and `C1-HYBRID-RESERVE-003` must be re-run under symmetric coupling
   before any cover verdict is treated as final.
3. `EXP-GPA-HYBRID-RESERVE` is registered `pending` — the shipped candidate had
   no experiment at all until now.
4. Production defaults are unchanged. `--representation` stays `flat`, and the
   coupling stage lives in `graphgraph.research`, which production does not
   import.

## Caveats

- Per-project **minimum** support is identical across couplings (0.0107%–
  0.0498%), so at least one task per project collapses even under symmetric
  coupling. Those tasks are worth isolating before symmetric coupling is
  treated as sufficient rather than necessary.
- Non-degeneracy is a precondition, not a benefit. That symmetric coupling
  produces a real field says nothing yet about whether a multiresolution
  representation over that field beats an equal-token flat packet. That is
  `EXP-GPA-HYBRID-RESERVE`, still pending.
- Symmetric coupling changes what "influence" means: a caller and its callee
  become mutually influential. Whether that matches the retrieval intent is a
  modelling decision this experiment does not settle.
