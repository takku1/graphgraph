# Packet Validation (L2)

<!-- recurspec-contract: 1.0 -->

## 1. System Intent & Responsibility

Decide mechanically whether packet text is a well-formed instance of the format it claims, and report the node and edge counts and errors that decision rests on; does not render packets, choose a format, or estimate token cost.

## 2. Sub-System Decomposition

**Atomic leaf (atomic build).** One per-format validator set behind one dispatching entry point.

## 3. Interface Contracts

- **Inputs:** `context_packet`
- **Outputs:** `validation_report`

## 4. Invariants (EARS + Epistemic Stage)

- **[Conditional]** IF validation fails THEN THE SYSTEM SHALL NOT claim structural success, as checked by `tests/test_packets.py`.
  - `EvidenceStage:` Sampled
- **[Ubiquitous]** A validation result SHALL report the format it validated against alongside its verdict, so a pass cannot be read as a pass for a different format.
  - `EvidenceStage:` Observed
- **[Ubiquitous]** A section marker SHALL be recognized only as its own exact line, never as a bare substring of a payload line.
  - `EvidenceStage:` Observed

## 5. Architectural Decisions (ADRs)

- **ADR-PV-001:** Every advertised format has a validator, and the round trip is what makes a format public. A format that renders but does not validate is a dead format, not a shipped one.
- **ADR-PV-002:** Validation is structural and mechanical, not a similarity judgement. The verdict is a boolean plus counts plus errors, because a graded score would let a partially broken packet be reported as mostly fine.
- **ADR-PV-003:** Marker detection is line-exact rather than substring-based. A substring test passes on any packet whose payload happens to contain the marker characters, which is the specific way a validator silently becomes a no-op.

## 6. Leaf Execution & Test Seam

- **Implementation Files:** `src/graphgraph/packets/validation.py`
- **Test Surface Seam:** `tests/test_packets.py`, `tests/test_live_validation.py`

## 7. Measurement Seams

- **Primary Metric:** `packet_token_units` (summed over the gate's query set at fixed recall, `direction: lower`)
- **Evaluation Gate Path:** `components/context-packets/measure.sh`
- **Correctness Backpressure:** `components/context-packets/checks.sh`
- **Telemetry Surface:** validated format, ok flag, node and edge counts, error list.
- **Branching Policy:** isolated candidate; a validator that accepts a deliberately corrupted packet is a revert, not a pass.
- **Known granularity gap:** this leaf currently shares the component-level `packet_token_units` gate, which is a rendering number; validator strictness is exercised by red-control fixtures rather than measured by `measure.sh`. Recorded as an open granularity gap rather than satisfied with a placeholder number.

## 8. Technology Resolution

- **Decision class:** BUILD
- **Justification:** Genuinely trivial and stable at this scale, and a fatal fit gap for the alternatives: the formats being validated are line-oriented prompt-boundary encodings this repository defines, so no schema language describes them and every off-the-shelf validator would need the grammar written anyway.
- **Selected:** in-repo validators on Python 3.10, stdlib `re` and `json`
- **Standard / protocol:** none
- **Alternatives considered:**

  | Option | Why not |
  |---|---|
  | JSON Schema / Pydantic | Describes JSON documents; most packet formats here are not JSON. |
  | A parser generator (Lark, ANTLR) | A full grammar toolchain for line-shaped formats that are a few markers and fields. |
  | Trusting the renderer instead | The renderer and the validator failing together is the exact case the round trip exists to catch. |

- **Fit gap:** validation is structural; it cannot judge whether the packet's content answers the query.
- **Seam:** `src/graphgraph/packets/validation.py`
- **Exit cost:** LOW — validators are per-format and additive.
- **Cost model:** in-process; no service spend.
- **Liability transferred:** none
- **Operational owner:** us
- **Failure mode:** an unrecognized format is reported invalid with an error rather than passed through as valid.
- **Open questions:** OW-Q05
