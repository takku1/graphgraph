"""Canonical Locus regression tasks (GG10-LC-001..012).

Ground truth was established from Locus source and the companion usage report
(``docs/bugs/2026-07-19-locus-black-box-usage-report.md``); it is sealed here for
scoring only. Cases whose ground truth is not yet mechanically codified are
marked ``status="pending"`` so the scoreboard never counts them as passing.
"""

from __future__ import annotations

from pathlib import Path

from .affected_tests_case import run_affected_tests
from .boundary import run_secret_boundary
from .cache_latency import run_cache_latency
from .delete_rename import run_delete_rename
from .docs_case import run_doc_enumeration
from .incremental import run_incremental_edit
from .model import CaseResult, GroundTruth, Task
from .parity import run_transport_parity
from .qualification import run_member_qualification
from .scope_case import run_scope_inference


def _affected_tests_case(task: Task, repo: Path, graph_path: Path | None = None) -> CaseResult:
    return run_affected_tests(task, repo, graph_path)


def _doc_enumeration_case(
    task: Task,
    _repo: Path,
    _graph_path: Path | None = None,
) -> CaseResult:
    return run_doc_enumeration(task)


def _scope_inference_case(
    task: Task,
    _repo: Path,
    _graph_path: Path | None = None,
) -> CaseResult:
    return run_scope_inference(task)


def _secret_boundary_case(
    task: Task,
    _repo: Path,
    _graph_path: Path | None = None,
) -> CaseResult:
    return run_secret_boundary(task)


def _transport_parity_case(
    task: Task,
    _repo: Path,
    _graph_path: Path | None = None,
) -> CaseResult:
    return run_transport_parity(task)


def _incremental_edit_case(
    task: Task,
    _repo: Path,
    _graph_path: Path | None = None,
) -> CaseResult:
    return run_incremental_edit(task)


def _cache_latency_case(
    task: Task,
    repo: Path,
    graph_path: Path | None = None,
) -> CaseResult:
    return run_cache_latency(task, repo, graph_path)


def _member_qualification_case(
    task: Task,
    repo: Path,
    graph_path: Path | None = None,
) -> CaseResult:
    return run_member_qualification(task, repo, graph_path)


def _delete_rename_case(
    task: Task,
    _repo: Path,
    _graph_path: Path | None = None,
) -> CaseResult:
    return run_delete_rename(task)


# Eight source-verified direct callers of `normalize_rust` (usage report GG-LC-004).
_NORMALIZE_RUST_CALLERS = (
    "transform_finding",
    "rust_logical_ops_lower_to_bitwise_at_binary_positions",
    "extract_rust",
    "rust_parse_bound",
    "rust_tropical_loop",
    "compose_rust_accumulator_summary",
    "compose_rust_block_summary",
    "rust_scan_update",
)

CANONICAL_TASKS: tuple[Task, ...] = (
    Task(
        id="GG10-LC-003",
        title="Qualified cross-crate calls: parse_to_ir",
        dimension="D5/D6",
        severity="P1",
        query="What does LocusEngine::parse_to_ir call?",
        query_class="direct_lookup",
        max_nodes=42,
        token_ceiling=500,
        check_noise=True,
        ground_truth=GroundTruth(
            required_callees=("lift_expr", "formula.rs"),
            required_call_edges=(
                ("parse_to_ir", "lift_expr"),
                ("parse_to_ir", "formula.rs"),
            ),
            forbidden_symbols=("binary-evidence-roadmap",),
            relevant_labels=("parse_to_ir", "lift_expr", "parse", "MathIR", "Expr"),
            notes="Both outgoing calls must be proven by typed edges; no sibling/audit noise; <=500 tokens.",
        ),
        reference="spec GG10-LC-003",
    ),
    Task(
        id="GG10-LC-004a",
        title="Budget-truncated reverse lookup reports incomplete",
        dimension="D6",
        severity="P1",
        query="What directly calls normalize_rust?",
        query_class="reverse_lookup",
        max_nodes=8,
        expect_complete=False,
        ground_truth=GroundTruth(
            direct_callers=_NORMALIZE_RUST_CALLERS,
            direct_call_target="normalize_rust",
            notes="8-node budget cannot hold 8 callers plus containment; must not claim complete.",
        ),
        reference="spec GG10-LC-004",
    ),
    Task(
        id="GG10-LC-004b",
        title="Reverse lookup returns all direct callers with budget",
        dimension="D6",
        severity="P1",
        query="What directly calls normalize_rust?",
        query_class="reverse_lookup",
        max_nodes=20,
        expect_complete=True,
        ground_truth=GroundTruth(
            direct_callers=_NORMALIZE_RUST_CALLERS,
            direct_call_target="normalize_rust",
            notes="With headroom, all eight verified direct callers must be present.",
        ),
        reference="spec GG10-LC-004",
    ),
    Task(
        id="GG10-LC-001",
        title="Focused unit-test recommendation selects >=1 test",
        dimension="D8",
        severity="P0",
        query="What calls normalize_rust and which tests cover it?",
        ground_truth=GroundTruth(
            required_tests=(
                "rust_logical_ops_lower_to_bitwise_at_binary_positions",
            ),
        ),
        case_fn=_affected_tests_case,
        reference="spec GG10-LC-001 (execution gated by GG_ACCEPT_EXEC=1 + cargo)",
    ),
    Task(
        id="GG10-LC-002",
        title="Core Expr type-change affected tests",
        dimension="D8",
        severity="P0",
        query="If Expr changes, which production code and tests are affected?",
        ground_truth=GroundTruth(
            required_evidence_relations=("references",),
        ),
        case_fn=_affected_tests_case,
        reference="spec GG10-LC-002",
    ),
    Task(
        id="GG10-LC-005",
        title="Complete document stage enumeration + validation parity",
        dimension="D9/D14",
        severity="P1",
        query="According to docs/pipeline.md, what stages form the pipeline?",
        token_ceiling=900,
        case_fn=_doc_enumeration_case,
        reference="spec GG10-LC-005",
    ),
    Task(
        id="GG10-LC-006",
        title="Natural-language architecture flow scope inference",
        dimension="D5/D7",
        severity="P2",
        query=(
            "How does expression parsing flow from frontends "
            "into the engine expression representation?"
        ),
        token_ceiling=1200,
        case_fn=_scope_inference_case,
        reference="spec GG10-LC-006",
    ),
    Task(
        id="GG10-LC-007",
        title="Exact incremental edit splice",
        dimension="D13",
        severity="P1",
        query="What directly calls normalize_value?",
        case_fn=_incremental_edit_case,
        reference="spec GG10-LC-007",
    ),
    Task(
        id="GG10-LC-008",
        title="Delete and rename leave no ghost nodes",
        dimension="D13",
        severity="P1",
        query="What directly calls normalize_value?",
        case_fn=_delete_rename_case,
        reference="spec GG10-LC-008",
    ),
    Task(
        id="GG10-LC-009",
        title="Same-named member qualification",
        dimension="D5",
        severity="P1",
        query="Expr::count_ops",
        case_fn=_member_qualification_case,
        reference="spec GG10-LC-009",
    ),
    Task(
        id="GG10-LC-010",
        title="Ignore and secret boundary",
        dimension="D2",
        severity="P0",
        query="secret canary API_KEY",
        case_fn=_secret_boundary_case,
        reference="spec GG10-LC-010",
    ),
    Task(
        id="GG10-LC-012",
        title="Cache and latency receipt",
        dimension="D12",
        severity="P1",
        query="normalize_rust",
        case_fn=_cache_latency_case,
        reference="spec GG10-LC-012",
    ),
    Task(
        id="GG10-LC-011",
        title="Transport parity across CLI plain / JSON / MCP",
        dimension="D14",
        severity="P1",
        query="What directly calls normalize_value?",
        case_fn=_transport_parity_case,
        reference="spec GG10-LC-011",
    ),
)


