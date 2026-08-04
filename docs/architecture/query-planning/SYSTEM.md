# Query Planning (L1)

> **Package:** `planning/`  
> **Narrative:** [../system-architecture.md](../system-architecture.md) § Query Classes  
> **Confidence detail:** [../information-retrieval/confidence-and-routing.md](../information-retrieval/confidence-and-routing.md)

## 1. Intent

Map natural-language or typed requests to a **query class**, expansion budget, **context-packet** encoding choice, and policy set. Deterministic routing is default; fitted models only after held-out utility gains (OW-Q03-A).

## 2. Query classes

| Query class | Purpose |
|-------------|---------|
| `direct_lookup` | Definition / focused symbol |
| `reverse_lookup` | Callers, references, dependents |
| `affected_tests` | Test impact attribution |
| `multi_hop_path` | Dependence / call / data-flow path |
| `blast_radius` | **Change-impact neighborhood** |
| `subsystem_summary` | Architectural slice summary |
| `doc_summary` | Document-grounded sections |
| `negative_query` | Absence / isolation evidence |
| `recent_changes` | History-qualified evidence |
| `spreading_activation` | Explicit multi-step activation |

Typical encoding heuristics (not hard law): direct/reverse → 1-hop compact packet; path/blast → 2-hop; zero-edge → semantic arrow; summary → structural or `doc_summary`.

## 3. Decomposition

| Concern | Module map |
|---------|------------|
| Query compiler (NL → typed) | `query_compiler.py` |
| Routing | `routing.py` |
| Budgets / shape | `budgets.py`, `shape.py` |
| Packet choice | `packet.py` |
| Policies | `policies.py` |
| Token cost model | `token_cost.py` |

## 4. Invariants (EARS + Epistemic Stage)

- **[Ubiquitous]** Semantic invariants remain hard gates; continuous scores SHALL NOT blur valid/invalid.
  - `EvidenceStage: Observed`.
- **[Conditional]** IF routing is automatic THEN an explicit class override SHALL still win.
  - `EvidenceStage: Sampled` — `tests/test_planning.py`.
- **[Ubiquitous]** Read-only query facades SHALL NOT imply mutation or silent full reindex.
  - `EvidenceStage: Observed`.
- **[Ubiquitous]** Route confidence SHALL NOT be reported as retrieval confidence.
  - `EvidenceStage: Observed` — route confidence is text-only class certainty and is near-constant; anchor-evidence confidence is a separate signal surfaced as `answerability.confidence`. See [confidence-and-routing.md](../information-retrieval/confidence-and-routing.md).
- **[Conditional]** IF a fitted routing model is proposed THEN it SHALL show held-out utility gains before replacing deterministic routing (OW-Q03-A).
  - `EvidenceStage: Unknown` — not yet attempted.

## 5. ADRs

- **ADR-QP-001:** Routing is deterministic by default. A model that routes correctly 95% of the time fails unpredictably in the remaining 5%, and the packet budget makes those failures expensive; determinism is preferred until a held-out gain is demonstrated.
- **ADR-QP-002:** Encoding heuristics per query class are defaults, not law — packet choice is ultimately a measured token-cost decision (see [context-packets](../context-packets/SYSTEM.md)).

## 6. Leaf execution & test seam

| | |
|--|--|
| **Implementation** | `planning/` (11 modules): `query_compiler.py`, `routing.py`, `budgets.py`, `shape.py`, `packet.py`, `policies.py`, `token_cost.py` |
| **Test surface** | `tests/test_planning.py` |
| **Downstream contract** | `tests/test_public_contracts.py` — keeps the advertised query-class and packet tables aligned with the registries |

## 7. Measurement seams

| | |
|--|--|
| **Primary metric** | Routing accuracy against a held-out labelled set (`direction: higher`) |
| **Budget metric** | Planned-versus-actual packet tokens (`direction: lower` on absolute error) |
| **Known bias** | The dynamic budget estimator is pessimistic about dense subgraphs and can over-prune — see [metric-validity-gaps.md](../../evaluation/metric-validity-gaps.md) |
| **Recorded results** | [empirical-evaluation.md](../../evaluation/empirical-evaluation.md) § Automatic Query Routing, § Dynamic Budget, § Adaptive Packet Choices |

## 8. Technology resolution

- **Decision class:** **BUILD**
- **Selected:** in-repo deterministic router and budget model
- **Standard / protocol:** none
- **Alternatives considered:**

  | Option | Why not |
  |--------|---------|
  | LLM classifier for routing | A model call on the hot path, priced and latent per query, to pick among ten known classes — and nondeterministic, so a routing regression is not reproducible |
  | Learned ranker / fitted router | Not rejected — gated. It needs held-out utility gains first (OW-Q03-A), and the labelled task set that would prove it is itself open work |
  | Fixed single strategy (always 2-hop) | Measured worse: expansion depth that helps a path query wastes the budget on a direct lookup |

- **Fit gap:** query classes are a closed vocabulary; a request that fits none routes to a default rather than inventing a class.
- **BUILD justification:** genuinely trivial and stable relative to its alternatives — a deterministic mapping over ten classes is a small amount of code whose failure modes are inspectable.
- **Seam:** `planning/routing.py`
- **Exit cost:** **LOW** — routing is a decision function; swapping it does not change the retrieval or packet contracts.
- **Operational owner:** us
- **Failure mode:** an unroutable query falls back to a default class and budget rather than erroring.
- **Open questions:** OW-Q03-A/B/C, OW-P1-03 — [open-work.md](../../open-work.md)
