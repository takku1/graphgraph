# Budgeted Selection (L3)

<!-- recurspec-contract: 1.0 -->

## 1. System Intent & Responsibility

Prune unsupported candidates and fit the surviving subgraph inside the planned token budget; does not discover anchors, expand the neighborhood, or encode the packet.

## 2. Sub-System Decomposition

**Atomic leaf (atomic build).** One assembly phase constructing the final bounded result.

## 3. Interface Contracts

- **Inputs:** `candidate_neighborhood`
- **Outputs:** `task_subgraph`

## 4. Invariants (EARS + Epistemic Stage)

- **[Conditional]** IF a multi-anchor class admits a lexically similar candidate that touches no structural edge and is unprotected THEN THE SYSTEM SHALL drop that candidate, as checked by `tests/test_retrieval.py`.
  - `EvidenceStage:` Measured
- **[Ubiquitous]** An anchor carrying an injected-reason tag SHALL be protected from unsupported-candidate pruning, so a deliberate reservation is not undone.
  - `EvidenceStage:` Observed
- **[Ubiquitous]** Selection SHALL respect the planned token budget rather than emitting an unbounded subgraph, as checked by `tests/test_tree_knapsack.py`.
  - `EvidenceStage:` Sampled
- **[Event-driven]** WHEN the budget cannot admit every supported candidate THE SYSTEM SHALL record what was omitted rather than silently truncating.
  - `EvidenceStage:` Observed

## 5. Architectural Decisions (ADRs)

- **ADR-BS-001:** Pruning protects tagged anchors. The reserving stage and the protecting stage must share one notion of admissible evidence, or reservation becomes a no-op.
- **ADR-BS-002:** Budget fitting is a constrained selection over a tree, not a greedy prefix; a prefix cut discards structurally required parents.

## 6. Leaf Execution & Test Seam

- **Implementation Files:** `src/graphgraph/retrieval/__init__.py`, `src/graphgraph/retrieval/budgeting.py`, `src/graphgraph/retrieval/context.py`, `src/graphgraph/retrieval/models.py`, `src/graphgraph/retrieval/phase_support.py`, `src/graphgraph/retrieval/pruning.py`, `src/graphgraph/retrieval/result_assembly.py`, `src/graphgraph/retrieval/selection.py`
- **Test Surface Seam:** `tests/test_retrieval.py`, `tests/test_tree_knapsack.py`, `tests/test_retrieval_phase_characterization.py`

## 7. Measurement Seams

- **Primary Metric:** `packet_token_units` (`direction: lower`)
- **Evaluation Gate Path:** `components/information-retrieval/measure.sh`
- **Correctness Backpressure:** `components/information-retrieval/checks.sh`
- **Telemetry Surface:** pruned candidate count, protected anchors, budget utilization, omitted candidates.
- **Branching Policy:** isolated candidate; a token reduction that loses node recall is a regression, not a win.

## 8. Technology Resolution

- **Decision class:** BUILD
- **Justification:** Differentiator — token cost at fixed answer quality is the project's primary axis, and the selection policy is where that trade is actually made.
- **Selected:** in-repo constrained selection on Python 3.10
- **Standard / protocol:** none
- **Alternatives considered:**

  | Option | Why not |
  |---|---|
  | Greedy top-k by score | Discards structurally required parents and produces packets that do not parse as a tree. |
  | General ILP/knapsack solver | Solver dependency and latency inside a millisecond retrieval budget for a bounded tree. |
  | Tree / precedence-constrained knapsack DP | The exact formalism for this leaf in isolation: items with an ancestor-inclusion precedence order under one budget, solvable exactly in pseudo-polynomial time on a tree. Worth adopting on its own terms; the reason it is not yet the design is that the real problem is the *connected* variant spanning three leaves — see `RF-04`. |
  | Connected Budgeted Maximum Coverage approximation | The honest statement of the full problem (ADR-SRT-007). Deferred to `RF-04` because it subsumes reservation and expansion and cannot be adopted in this leaf alone. |

- **Fit gap:** the budget is enforced against a calibrated token proxy rather than the consumer's exact tokenizer.
- **Seam:** `src/graphgraph/retrieval/result_assembly.py`
- **Exit cost:** HIGH — selection is the last stage before encoding and sets the cost metric.
- **Cost model:** in-process CPU.
- **Liability transferred:** none
- **Operational owner:** us
- **Failure mode:** an unsatisfiable budget emits the anchor set with an explicit omission receipt.
- **Open questions:** OW-Q05, OW-Q06
