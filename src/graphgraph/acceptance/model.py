"""Data model for the acceptance harness.

Everything here is plain data. Ground truth lives on :class:`Task` but is only
ever read by gate functions that score an already-produced :class:`ProbeResult`;
it is never handed back into retrieval.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from .tokens import TokenCount

PASS = "pass"
FAIL = "fail"
NA = "na"
PENDING = "pending"

# Relations that justify a node for a structural query. A node reachable only by
# ``contains`` from a non-callee container is sibling noise, not evidence.
STRUCTURAL_RELATIONS = frozenset(
    {"calls", "returns", "references", "imports", "covers", "tests", "implements", "extends"}
)


@dataclass(frozen=True)
class GateResult:
    name: str
    status: str  # PASS | FAIL | PENDING | NA
    detail: str = ""


@dataclass(frozen=True)
class PacketNode:
    local_id: str
    label: str
    path: str


@dataclass(frozen=True)
class PacketEdge:
    relation: str
    src: str
    dst: str


@dataclass
class ProbeResult:
    """The scored output of one black-box query. ``raw`` keeps the full payload."""

    task_id: str
    query: str
    query_class: str
    state: str
    next_action: str
    control_raw: str
    packet: str
    nodes: int
    edges: int
    tokens: TokenCount
    packet_nodes: list[PacketNode]
    packet_edges: list[PacketEdge]
    relations: dict[str, str]
    facet_coverage: dict
    structural_facet_coverage: dict
    answerability: dict
    anchors: list[dict]
    plain_nodes: Optional[int]
    plain_edges: Optional[int]
    graph_identity: dict
    query_ms: float
    cache_state: str
    raw: dict

    def node_ids(self, symbol: str) -> set[str]:
        """Return packet node IDs that structurally identify *symbol*.

        Labels must match exactly. Paths may contain a fragment such as
        ``formula.rs``. Packet prose is deliberately excluded so a decoy
        signature or summary cannot satisfy a structural gate.
        """
        return {
            node.local_id
            for node in self.packet_nodes
            if node.label == symbol or symbol in node.path
        }

    def has_symbol(self, symbol: str) -> bool:
        return bool(self.node_ids(symbol))

    def has_edge(self, relation: str, source: str, target: str) -> bool:
        source_ids = self.node_ids(source)
        target_ids = self.node_ids(target)
        return any(
            edge.relation == relation
            and edge.src in source_ids
            and edge.dst in target_ids
            for edge in self.packet_edges
        )

    def anchor_labels(self) -> set[str]:
        return {str(a.get("label", "")) for a in self.anchors}

    def is_complete(self) -> bool:
        return self.next_action == "answer" and self.state in ("answerable", "complete")

    def irrelevant_ratio(self, relevant_labels: set[str]) -> tuple[float, list[str]]:
        """Fraction of packet nodes that are neither anchors/required nor on a
        structural connecting edge. Returns (ratio, irrelevant_labels)."""
        justified = set(self.anchor_labels()) | set(relevant_labels)
        structural_ids = {
            end
            for edge in self.packet_edges
            if edge.relation in STRUCTURAL_RELATIONS
            for end in (edge.src, edge.dst)
        }
        irrelevant = [
            node.label
            for node in self.packet_nodes
            if node.label not in justified and node.local_id not in structural_ids
        ]
        total = len(self.packet_nodes) or 1
        return len(irrelevant) / total, irrelevant


@dataclass
class GroundTruth:
    """Sealed expected answers, used only for scoring."""

    required_symbols: tuple[str, ...] = ()
    required_callees: tuple[str, ...] = ()
    required_call_edges: tuple[tuple[str, str], ...] = ()
    forbidden_symbols: tuple[str, ...] = ()
    direct_callers: tuple[str, ...] = ()
    direct_call_target: str = ""
    required_tests: tuple[str, ...] = ()
    required_evidence_relations: tuple[str, ...] = ()
    relevant_labels: tuple[str, ...] = ()
    doc_stage_count: Optional[int] = None
    notes: str = ""


@dataclass
class Task:
    id: str
    title: str
    dimension: str
    severity: str
    query: str
    query_class: str = "auto"
    max_nodes: Optional[int] = None
    token_ceiling: Optional[int] = None
    scopes: tuple[str, ...] = ()
    ground_truth: GroundTruth = field(default_factory=GroundTruth)
    gate_fn: Optional[Callable[["ProbeResult", "Task"], list[GateResult]]] = None
    # Cases that are not a single query against the target graph (e.g. a
    # self-contained scan-boundary fixture) supply their own runner.
    case_fn: Optional[
        Callable[["Task", Path, Optional[Path]], "CaseResult"]
    ] = None
    expect_complete: Optional[bool] = None
    check_noise: bool = False
    max_irrelevant_ratio: float = 0.10
    status: str = "active"  # active | pending
    reference: str = ""


@dataclass
class CaseResult:
    task: Task
    probe: Optional[ProbeResult]
    gates: list[GateResult]
    error: str = ""

    @property
    def status(self) -> str:
        if self.task.status == "pending":
            return PENDING
        if self.error:
            return FAIL
        if any(g.status == FAIL for g in self.gates):
            return FAIL
        if any(g.status == PENDING for g in self.gates):
            return PENDING
        graded = [g for g in self.gates if g.status in (PASS, FAIL)]
        if not graded:
            return NA
        return PASS

    @property
    def failing_gates(self) -> list[GateResult]:
        return [g for g in self.gates if g.status == FAIL]
