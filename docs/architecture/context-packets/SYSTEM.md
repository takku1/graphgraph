# Context-Packet Encoding (L1)

> **Package:** `packets/`  
> **Narrative:** [../system-architecture.md](../system-architecture.md) § Packet Formats

## 1. Intent

Serialize a selected subgraph into an **LLM-facing context packet**. Choose format by **measured token cost** and **mechanical validation**, not a universal aesthetic floor.

Distinguish:

| Artifact | Role |
|----------|------|
| Binary `.gg` store | Persistence |
| Context packet (`gg`, `gg_lex`, hybrid, SVO, …) | Prompt boundary |
| JSON receipt | MCP/CLI control envelope |

## 2. Decomposition

| Concern | Module map |
|---------|------------|
| Renderers | `packets/renderers.py`, `formats.py` |
| Validation | `packets/validation.py` |
| Packet metrics | `packets/metrics.py` |

Public formats must generate and validate end-to-end or be unadvertised (OW-Q05-A). Names: compact `gg` is the accepted CLI/API name (older research text may say `gg_max`).

## 3. Interfaces

| | |
|--|--|
| **Inputs** | Selected subgraph (nodes, edges, facts), query class, token budget, format choice |
| **Outputs** | Rendered packet text, validation report, packet metrics (token units, node/edge counts) |
| **Consumers** | CLI `context`/`final`, MCP `final_packet`, acceptance gates |

## 4. Invariants (EARS + Epistemic Stage)

- **[Conditional]** IF validation fails THEN THE SYSTEM SHALL NOT claim structural success.
  - `EvidenceStage: Sampled` — `tests/test_packets.py`.
- **[Conditional]** IF selecting a cheaper encoding THEN identity-safe semantics SHALL be preserved.
  - `EvidenceStage: Sampled`.
- **[Ubiquitous]** Token claims for ranking formats SHALL use calibrated estimators (OW-AC-07, done).
  - `EvidenceStage: Measured` — mean error 2.78%, max 11.93%, cross-format spread 7.04% against `tiktoken`; see [token proxy recalibration](../../evaluation/graybox-cycles/2026-07-30-token-proxy-recalibration.md).
  - **Re-verified 2026-08-05** (T-B05, `benchmarks/context_graph/calibrate_token_proxy.py --enforce`, this project's own graph, 108 packet/tokenizer pairs across `o200k_base`+`cl100k_base`): mean |error| **2.73%**, p95 **5.93%**, cross-format spread **6.68%**, 0 format inversions — all four gates (MAE≤5%, p95≤10%, spread≤10%, 0 inversions) pass with headroom, materially unchanged from the 2026-07-30 baseline. A fresh least-squares refit produces slightly different constants (piece 1.32 vs shipped 1.26, punctuation 0.045 vs shipped 0.163) reflecting this repo's corpus drift since calibration, but the *shipped* constants — not the refit — are what the gate scores, and they still pass comfortably. Not re-fitted: the difference is a normal refit delta on a still-passing estimator, not a failing one, and this project's own convention holds format-ranking changes to an eval gate rather than updating constants opportunistically.
- **[Ubiquitous]** Code accumulating a packet line by line SHALL sum `token_units()` and round once.
  - `EvidenceStage: Measured` — summing `estimate_tokens` per line drifts from the same packet rendered whole; this silently broke incremental budget accounting once already.
- **[Ubiquitous]** A public format SHALL generate and validate end-to-end or remain unadvertised (OW-Q05-A).
  - `EvidenceStage: Observed`.

## 5. ADRs

- **ADR-CP-001:** Format is chosen by measured token cost, not a universal aesthetic floor — the ranking inverted once already under a real tokenizer, so aesthetics are not evidence.
- **ADR-CP-002:** The shipped estimator is a calibrated two-parameter proxy, not a bundled tokenizer. `tiktoken` stays an optional measurement instrument so the runtime keeps no model-vendor dependency.
- **ADR-CP-003:** The proxy is deliberately **whitespace-blind**. It sizes budgets; it cannot judge a layout or pretty-printing decision. A whitespace term was fitted twice and rejected both times for taking a negative coefficient.

## 6. Leaf execution & test seam

| | |
|--|--|
| **Implementation** | `packets/renderers.py`, `packets/formats.py`, `packets/validation.py`, `packets/metrics.py` |
| **Test surface** | `tests/test_packets.py` |
| **Contract test** | `tests/test_docs_contract.py::test_architecture_uses_current_public_packet_names` — keeps advertised format names in sync with this tree |

## 7. Measurement seams

| | |
|--|--|
| **Primary metric** | Packet token cost at fixed recall (`direction: lower`), denominated in calibrated units |
| **Estimator gate** | MAE ≤5%, p95 ≤10% versus a real tokenizer (OW-AC-07) |
| **Re-derivation** | `benchmarks/context_graph/calibrate_token_proxy.py` re-derives both constants by importing the shipped functions, so the fit cannot drift from the estimator; it prints `DRIFT:` with replacements when a renderer change invalidates them |
| **Reference tokenizer** | `cl100k_base` (benchmark manifest); model selection was validated on a held-out tokenizer (fit on `o200k`, scored on `cl100k`) |
| **Correctness backpressure** | `tests/test_packets.py` plus mechanical validation on every advertised format |

## 8. Technology resolution

- **Decision class:** **BUILD** (packet encodings + estimator) / **ADOPT** (`tiktoken`, measurement only)
- **Selected:** in-repo renderers; `tiktoken>=0.5.0` under the `benchmark` extra
- **Standard / protocol:** none — the packet is a prompt-boundary format, deliberately not a wire format
- **Alternatives considered:**

  | Option | Why not |
  |--------|---------|
  | JSON / YAML serialization | The verbose baseline this project measures against; identifier-heavy and structurally redundant at the prompt boundary |
  | Prompt compressors (LLMLingua-family) | Graph-blind: they prune on token entropy and break topological references, which is precisely the structure a context packet exists to carry |
  | Protobuf / MessagePack | Efficient on the wire, unreadable at the prompt boundary — the consumer here is a model, not a parser |
  | Bundling a tokenizer at runtime | Adds a model-vendor dependency to every scan to serve a budgeting estimate; the calibrated proxy covers it at 2.78% mean error |

- **Fit gap:** the proxy cannot see whitespace, so layout and pretty-printing decisions need a real tokenizer (`--json --pretty` measures +26.7% real, +0.0% proxy).
- **BUILD justification:** differentiator — "cheapest representation an LLM can reliably interpret" is the project's research question; the encoding *is* the product.
- **Seam:** `packets/metrics.py` (`estimate_tokens`, `token_units`)
- **Exit cost:** **MEDIUM** — swapping the estimator is contained, but every historical token figure is denominated in it (see the invalidation note below).
- **Operational owner:** us
- **Failure mode:** `tiktoken` absent ⇒ calibration and acceptance token gates cannot run; the runtime estimator is unaffected.
- **Known invalidation:** any `estimate_tokens` figure recorded **before 2026-07-30** is unreliable — the old proxy was a bare word count with 47.2% cross-format spread. Large-magnitude compression claims survive; specific percentages and all cross-format comparisons do not.
- **Open questions:** OW-Q05-*, OW-AC-06 — [open-work.md](../../open-work.md)
