from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

from ..graph.core import Graph
from ..packets import render_packet
from ..packets.validation import validate_packet
from ..planning import (
    ContextPlan,
    QueryRoute,
    compute_subgraph_stats,
    plan_context,
    refine_plan_for_subgraph,
    route_query,
)
from ..retrieval import (
    RetrievalResult,
    apply_shape_budget,
    reconcile_semantic_retrieval_receipt,
    retrieve_context,
    search_nodes,
)
from .contracts import CapabilityReceipt, EvidenceProvider, ProviderRegistry
from .evidence_store import EvidenceStore
from .inference import DEFAULT_RULES, infer_edges
from .intelligence import build_hierarchy
from .source_planner import QuerySourcePlanner, receipt_data


@dataclass(frozen=True)
class GraphProgram:
    """LLM-native compilation request over a typed evidence graph."""

    query: str
    query_class: str = "auto"
    packet: str | None = "gg"
    passes: tuple[str, ...] = ()
    scopes: tuple[str, ...] = ()
    max_nodes: int | None = None
    hops: int | None = None
    anchor_limit: int | None = None
    scope_mode: str = "strict"
    anchor_paths: tuple[str, ...] = ()


@dataclass(frozen=True)
class CompilationReceipt:
    query_class: str
    packet: str
    passes: tuple[str, ...]
    anchors: tuple[str, ...]
    nodes: int
    edges: int
    valid: bool
    structural_validation: str = "not_applicable"
    semantic_validation: str = "not_applicable"
    answerability: str = "unknown"
    provider_receipts: tuple[dict[str, object], ...] = field(default_factory=tuple)
    source_receipt: dict[str, object] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class CompilationResult:
    packet: str
    receipt: CompilationReceipt
    graph: Graph
    route: QueryRoute
    plan: ContextPlan
    retrieval: RetrievalResult

    def envelope(self) -> str:
        return json.dumps({"receipt": asdict(self.receipt), "packet": self.packet}, indent=2, ensure_ascii=False)


class GraphRuntime:
    """Compiler/runtime that keeps all features inside GraphGraph's graph IR."""

    def __init__(
        self,
        graph: Graph,
        providers: tuple[EvidenceProvider, ...] = (),
        *,
        evidence_store: EvidenceStore | None = None,
        changed_paths: tuple[str, ...] = (),
        refresh_evidence: bool = False,
        source_planner: QuerySourcePlanner | None = None,
        source_mode: str = "auto",
        memory_scopes: tuple[str, ...] = ("project", "session"),
    ) -> None:
        self.graph = graph
        self.providers = ProviderRegistry(providers)
        self.evidence_store = evidence_store
        self.changed_paths = changed_paths
        self.refresh_evidence = refresh_evidence
        self.source_planner = source_planner
        self.source_mode = source_mode
        self.memory_scopes = memory_scopes

    def apply_evidence(
        self,
        graph: Graph | None = None,
        *,
        preferred_paths: tuple[str, ...] = (),
        max_nodes: int | None = None,
        max_edges: int | None = None,
    ) -> tuple[Graph, tuple[CapabilityReceipt, ...]]:
        current = graph or self.graph
        if self.evidence_store is None:
            return self.providers.apply(current)
        return self.providers.apply_persisted(
            current,
            self.evidence_store,
            changed_paths=self.changed_paths,
            force=self.refresh_evidence,
            preferred_paths=preferred_paths,
            max_nodes=max_nodes,
            max_edges=max_edges,
        )

    def compile(self, program: GraphProgram) -> CompilationResult:
        graph = self.graph
        source_seed_ids: tuple[str, ...] = ()
        source_preferred_paths: tuple[str, ...] = ()
        source_receipt: dict[str, object] = {}
        if self.source_planner is not None:
            source_plan = self.source_planner.plan(
                graph,
                program.query,
                mode=self.source_mode,
                memory_scopes=self.memory_scopes,
            )
            graph = source_plan.graph
            source_seed_ids = source_plan.seed_ids
            source_preferred_paths = source_plan.preferred_paths
            source_receipt = receipt_data(source_plan)
        provider_receipts: tuple[CapabilityReceipt, ...] = ()
        applied: list[str] = []
        warnings: list[str] = []
        preferred_paths = _preferred_paths(
            graph,
            program.query,
            source_seed_ids,
            source_preferred_paths,
        )
        for compiler_pass in program.passes:
            if compiler_pass == "evidence":
                graph, provider_receipts = self.apply_evidence(
                    graph,
                    preferred_paths=preferred_paths,
                    max_nodes=max(256, min(2000, (program.max_nodes or 120) * 6)),
                    max_edges=max(1024, min(8000, (program.max_nodes or 120) * 24)),
                )
                warnings.extend(
                    warning
                    for receipt in provider_receipts
                    for warning in receipt.warnings
                )
            elif compiler_pass == "inference":
                graph, inference_receipt = infer_edges(graph, DEFAULT_RULES)
                if inference_receipt["truncated"]:
                    warnings.append("inference edge budget reached")
            elif compiler_pass == "hierarchy":
                graph = build_hierarchy(graph)
            else:
                raise ValueError(f"unknown GraphGraph compiler pass: {compiler_pass}")
            applied.append(compiler_pass)
        route = route_query(program.query, program.query_class)
        plan = plan_context(
            route.query_class,
            program.query,
            max_nodes=program.max_nodes,
            packet=program.packet,
            hops=program.hops,
            anchor_limit=program.anchor_limit,
        )
        if program.max_nodes is None:
            plan = apply_shape_budget(graph, plan, program.query)
        retrieval = retrieve_context(
            graph,
            program.query,
            route.query_class,
            plan.hops,
            anchor_limit=program.anchor_limit,
            max_nodes=program.max_nodes,
            scopes=program.scopes,
            scope_mode=program.scope_mode,
            seed_ids=source_seed_ids,
            anchor_paths=program.anchor_paths,
        )
        retrieval.metadata["sources"] = source_receipt
        semantic_errors = reconcile_semantic_retrieval_receipt(
            graph,
            retrieval,
            route=route,
            automatic_route=(program.query_class or "auto").strip().lower() == "auto",
        )
        if program.packet is None:
            plan = refine_plan_for_subgraph(
                plan,
                compute_subgraph_stats(graph, retrieval.nodes, retrieval.edges),
            )
        packet_format = program.packet or plan.packet
        packet = (
            render_packet(graph, retrieval.nodes, retrieval.edges, packet_format)
            if retrieval.starts
            else ""
        )
        validation = validate_packet(packet) if packet else None
        structural_validation = (
            "pass" if validation is not None and validation.ok
            else "fail" if validation is not None
            else "not_applicable"
        )
        semantic_validation = "pass" if not semantic_errors else "fail"
        answerability = str(
            retrieval.metadata.get("answerability", {}).get("status", "unknown")
        )
        receipt = CompilationReceipt(
            query_class=route.query_class,
            packet=packet_format,
            passes=tuple(applied),
            anchors=retrieval.starts,
            nodes=len(retrieval.nodes),
            edges=len(retrieval.edges),
            valid=(validation.ok if validation is not None else True) and not semantic_errors,
            structural_validation=structural_validation,
            semantic_validation=semantic_validation,
            answerability=answerability,
            provider_receipts=tuple(asdict(item) for item in provider_receipts),
            source_receipt=source_receipt,
            warnings=(
                tuple(warnings)
                + (validation.errors if validation is not None else ())
                + tuple(semantic_errors)
            ),
        )
        return CompilationResult(packet, receipt, graph, route, plan, retrieval)


def _preferred_paths(
    graph: Graph,
    query: str,
    source_seed_ids: tuple[str, ...],
    planned_paths: tuple[str, ...],
) -> tuple[str, ...]:
    paths: list[str] = list(planned_paths)
    for node_id in source_seed_ids:
        node = graph.nodes.get(node_id)
        if node is not None and node.path:
            paths.append(node.path.replace("\\", "/"))
    if not planned_paths:
        for match in search_nodes(graph, query, limit=12, personalize=False):
            if match.node.path:
                paths.append(match.node.path.replace("\\", "/"))
    return tuple(dict.fromkeys(paths))
