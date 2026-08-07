from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING

from ..graph.core import Graph
from ..packets import estimate_tokens, render_packet
from ..packets.validation import validate_packet
from ..planning import (
    ContextPlan,
    QueryRoute,
    compute_subgraph_stats,
    plan_context,
    refine_plan_for_subgraph,
    route_query,
)
from ..representation import (
    REPRESENTATION_NAMES,
    HybridRepresentationConfig,
    accept_representation,
    compile_hybrid_representation,
)
from ..retrieval import (
    RetrievalResult,
    apply_shape_budget,
    packet_priority,
    reconcile_semantic_retrieval_receipt,
    retrieve_context,
    search_nodes,
)
from ..runtime.cache import activation_state_file_for_graph
from .contracts import CapabilityReceipt, EvidenceProvider, ProviderRegistry
from .source_planner import QuerySourcePlanner, receipt_data

if TYPE_CHECKING:
    from .evidence_store import EvidenceStore


@dataclass(frozen=True)
class CompilerPassSpec:
    name: str
    description: str


COMPILER_PASSES: tuple[CompilerPassSpec, ...] = (
    CompilerPassSpec("evidence", "Collect bounded structural and CPG evidence."),
    CompilerPassSpec("inference", "Infer typed edges from the current graph IR."),
    CompilerPassSpec("hierarchy", "Materialize the graph hierarchy."),
)
COMPILER_PASS_NAMES: tuple[str, ...] = tuple(spec.name for spec in COMPILER_PASSES)


def compiler_pass_schema() -> dict[str, object]:
    return {
        "type": "array",
        "items": {"type": "string", "enum": list(COMPILER_PASS_NAMES)},
        "description": "Optional compiler passes: " + ", ".join(COMPILER_PASS_NAMES) + ".",
    }


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
    representation: str = "flat"
    representation_budget: int | None = None


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
    representation_receipt: dict[str, object] = field(default_factory=dict)
    format_selection: dict[str, object] = field(default_factory=dict)
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
        graph_path: Path | None = None,
    ) -> None:
        self.graph = graph
        self.providers = ProviderRegistry(providers)
        self.evidence_store = evidence_store
        self.changed_paths = changed_paths
        self.refresh_evidence = refresh_evidence
        self.source_planner = source_planner
        self.source_mode = source_mode
        self.memory_scopes = memory_scopes
        #: Where this graph is persisted, used to resolve the per-graph
        #: artifacts GraphGraph writes beside it. None when the caller supplied
        #: a resident Graph with no path, in which case that state falls back
        #: to its CWD-relative default.
        self.graph_path = graph_path

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
        if program.representation not in REPRESENTATION_NAMES:
            raise ValueError(
                f"unknown representation policy: {program.representation}; "
                f"expected one of {', '.join(REPRESENTATION_NAMES)}"
            )
        graph = self.graph
        source_seed_ids: tuple[str, ...] = ()
        source_preferred_paths: tuple[str, ...] = program.anchor_paths
        source_receipt: dict[str, object] = {}
        if self.source_planner is not None and not program.anchor_paths:
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
        elif program.anchor_paths:
            source_receipt = {
                "mode": "exact_paths",
                "lexical_strength": 0.0,
                "seed_ids": [],
                "sources": ["changed_paths"],
                "preferred_paths": list(program.anchor_paths),
                "warnings": [],
            }
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
                from .inference import DEFAULT_RULES, infer_edges

                graph, inference_receipt = infer_edges(graph, DEFAULT_RULES)
                if inference_receipt["truncated"]:
                    warnings.append("inference edge budget reached")
            elif compiler_pass == "hierarchy":
                from .intelligence import build_hierarchy

                graph = build_hierarchy(graph)
            else:
                raise ValueError(f"unknown GraphGraph compiler pass: {compiler_pass}")
            applied.append(compiler_pass)
        route = route_query(
            program.query,
            program.query_class,
            scopes=program.scopes,
        )
        plan = plan_context(
            route.query_class,
            program.query,
            max_nodes=program.max_nodes,
            packet=program.packet,
            hops=program.hops,
            anchor_limit=program.anchor_limit,
        )
        exact_direct_lookup = (
            route.query_class == "direct_lookup"
            and not program.anchor_paths
            and bool(search_nodes(
                graph,
                program.query,
                limit=1,
                scopes=program.scopes,
                exact_fast_path=True,
                exact_only=True,
            ))
        )
        if program.max_nodes is None and not exact_direct_lookup:
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
            activation_state_path=(
                activation_state_file_for_graph(self.graph_path)
                if self.graph_path is not None
                else None
            ),
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
        priority = packet_priority(
            retrieval.starts,
            retrieval.nodes,
            retrieval.edges,
            route.query_class,
            graph=graph,
        )
        format_selection: dict[str, object] = {}
        packet = ""
        if retrieval.starts:
            packet = render_packet(
                graph,
                retrieval.nodes,
                retrieval.edges,
                packet_format,
                priority=priority,
            )
            # Packet choice is made after the bounded subgraph exists.  Compare
            # exact rendered proxy costs rather than assuming one universal
            # winner.  SVO is admitted only when labels are unique, because its
            # triples use labels instead of node handles at the edge endpoints.
            labels = [
                graph.nodes[node_id].label
                for node_id in retrieval.nodes
                if node_id in graph.nodes
            ]
            adaptive = (
                program.packet is None
                and packet_format == "gg"
                and len(labels) == len(set(labels))
            )
            candidates = {packet_format: packet}
            svo_validation_safe = False
            if adaptive:
                svo_candidate = render_packet(
                    graph,
                    retrieval.nodes,
                    retrieval.edges,
                    "svo",
                )
                svo_validation_safe = validate_packet(svo_candidate).ok
                if svo_validation_safe:
                    candidates["svo"] = svo_candidate
            costs = {name: estimate_tokens(text) for name, text in candidates.items()}
            chosen = min(costs, key=lambda name: (costs[name], name))
            packet_format = chosen
            packet = candidates[chosen]
            minimum = min(costs.values())
            format_selection = {
                "policy": "exact_rendered_minimum_v1" if adaptive else "explicit_or_semantic_constraint",
                "candidates": costs,
                "chosen": chosen,
                "chosen_tokens": costs[chosen],
                "minimum_tokens": minimum,
                "ratio_to_minimum": round(costs[chosen] / max(1, minimum), 4),
                "label_identity_safe": len(labels) == len(set(labels)),
                "svo_validation_safe": svo_validation_safe,
            }
            retrieval.metadata["format_selection"] = format_selection
            if chosen != plan.packet:
                plan = replace(
                    plan,
                    packet=chosen,
                    reason=(
                        f"adaptive rendered format minimum: {chosen}={costs[chosen]} "
                        f"tokens across {costs}"
                    ),
                )
        representation_receipt: dict[str, object] = {}
        if packet and program.representation == "hybrid":
            seed_weights = {
                match.node.id: max(0.0, float(match.score))
                for match in retrieval.matches
                if match.node.id in graph.nodes and match.score > 0.0
            }
            for start in retrieval.starts:
                seed_weights[start] = max(1.0, seed_weights.get(start, 0.0))
            try:
                hybrid = compile_hybrid_representation(
                    graph,
                    seed_weights,
                    packet_format=packet_format,
                    priority=priority,
                    config=HybridRepresentationConfig(
                        token_budget=program.representation_budget or 4096,
                    ),
                )
            except ValueError as exc:
                warning = f"hybrid representation fell back to flat: {exc}"
                warnings.append(warning)
                representation_receipt = {
                    "policy": "hybrid",
                    "status": "fallback_flat",
                    "reason": str(exc),
                    "token_budget": program.representation_budget or 4096,
                }
            else:
                hybrid_packet, representation_receipt = accept_representation(hybrid)
                if hybrid_packet is not None:
                    packet = hybrid_packet
                else:
                    warnings.append(
                        f"hybrid representation fell back to flat: {representation_receipt['reason']}"
                    )
            retrieval.metadata["representation"] = representation_receipt
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
            representation_receipt=representation_receipt,
            format_selection=format_selection,
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
