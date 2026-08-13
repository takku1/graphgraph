from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Mapping, Protocol

from ..graph.core import Graph
from ..io import load_any, project_root_for_graph
from ..packet_targets import target_spec
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
from ..surface import COMPILER_PASS_NAMES
from .artifacts import (
    GRAPH_ARTIFACTS,
    GRAPH_EDGES,
    GRAPH_METADATA,
    GRAPH_NODES,
    AnalysisCache,
    AnalysisKey,
    ArtifactFingerprint,
    ArtifactIndex,
)
from .contracts import CapabilityReceipt, EvidenceProvider, ProviderRegistry, StructuralEvidenceProvider
from .source_planner import QuerySourcePlanner, receipt_data

if TYPE_CHECKING:
    from .evidence_store import EvidenceStore


DEFAULT_SOURCE_MODE = "auto"
DEFAULT_MEMORY_SCOPES = ("project", "session")


@dataclass(frozen=True)
class CompileRequest:
    """Immutable context goal and constraints over an evidence graph."""

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
class PassCostModel:
    """Static work model used for scheduling and receipts."""

    complexity: str
    fixed_cost: float = 0.0
    node_cost: float = 0.0
    edge_cost: float = 0.0

    def estimate(self, graph: Graph) -> float:
        return round(
            self.fixed_cost
            + self.node_cost * len(graph.nodes)
            + self.edge_cost * len(graph.edges),
            4,
        )


@dataclass(frozen=True)
class CompilerPassSpec:
    """Declarative pass metadata exposed without exposing pass machinery."""

    name: str
    description: str
    version: str = "1"
    requires: tuple[str, ...] = GRAPH_ARTIFACTS
    produces: tuple[str, ...] = GRAPH_ARTIFACTS
    preserves: tuple[str, ...] = ()
    capabilities: tuple[str, ...] = ()
    deterministic: bool = False
    cache_scope: str = "none"
    parameters: tuple[str, ...] = ()
    cost: PassCostModel = PassCostModel("unknown")


@dataclass(frozen=True)
class PassContext:
    """Immutable inputs shared by compiler passes for one compilation."""

    compiler: ContextCompiler
    request: CompileRequest
    preferred_paths: tuple[str, ...]


@dataclass(frozen=True)
class PassOutcome:
    graph: Graph
    provider_receipts: tuple[CapabilityReceipt, ...] = ()
    receipts: tuple[dict[str, object], ...] = ()
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class TransformationOutcome:
    """Result of applying the requested graph-to-graph compiler passes."""

    graph: Graph
    passes: tuple[str, ...]
    receipts: tuple[dict[str, object], ...]
    provider_receipts: tuple[CapabilityReceipt, ...]
    warnings: tuple[str, ...]


class CompilerPass(Protocol):
    """Internal seam for graph-to-graph compiler transformations."""

    spec: CompilerPassSpec

    def run(self, context: PassContext, graph: Graph) -> PassOutcome: ...


class _EvidencePass:
    spec = CompilerPassSpec(
        "evidence",
        "Collect bounded structural and CPG evidence.",
        produces=(*GRAPH_ARTIFACTS, "provider_receipts"),
        capabilities=("structural_evidence", "cpg_evidence"),
        parameters=("max_nodes",),
        cost=PassCostModel("external_linear", node_cost=1.0, edge_cost=0.25),
    )

    def run(self, context: PassContext, graph: Graph) -> PassOutcome:
        receipts_graph, receipts = context.compiler.apply_evidence(
            graph,
            preferred_paths=context.preferred_paths,
            max_nodes=max(256, min(2000, (context.request.max_nodes or 120) * 6)),
            max_edges=max(1024, min(8000, (context.request.max_nodes or 120) * 24)),
        )
        return PassOutcome(
            receipts_graph,
            provider_receipts=receipts,
            warnings=tuple(warning for receipt in receipts for warning in receipt.warnings),
        )


class _InferencePass:
    spec = CompilerPassSpec(
        "inference",
        "Infer typed edges from the current graph IR.",
        requires=(GRAPH_NODES, GRAPH_EDGES),
        produces=(GRAPH_EDGES, "inference_receipt"),
        preserves=(GRAPH_NODES, GRAPH_METADATA),
        capabilities=("typed_edge_inference",),
        deterministic=True,
        cache_scope="compiler",
        cost=PassCostModel("rule_cross_product", node_cost=1.0, edge_cost=1.0),
    )

    def run(self, context: PassContext, graph: Graph) -> PassOutcome:
        del context
        from .inference import DEFAULT_RULES, infer_edges

        inferred, receipt = infer_edges(graph, DEFAULT_RULES)
        warnings = ("inference edge budget reached",) if receipt["truncated"] else ()
        return PassOutcome(inferred, receipts=(receipt,), warnings=warnings)


class _HierarchyPass:
    spec = CompilerPassSpec(
        "hierarchy",
        "Materialize the graph hierarchy.",
        requires=(GRAPH_NODES, GRAPH_EDGES),
        produces=(*GRAPH_ARTIFACTS, "hierarchy_receipt"),
        capabilities=("community_hierarchy",),
        deterministic=True,
        cache_scope="compiler",
        cost=PassCostModel("community_detection", node_cost=1.0, edge_cost=1.0),
    )

    def run(self, context: PassContext, graph: Graph) -> PassOutcome:
        del context
        from .intelligence import build_hierarchy

        transformed = build_hierarchy(graph)
        return PassOutcome(
            transformed,
            receipts=(
                {
                    "pass": "hierarchy",
                    "communities": transformed.metadata.get("communities", "0"),
                },
            ),
        )


BUILTIN_COMPILER_PASSES: tuple[CompilerPass, ...] = (
    _EvidencePass(),
    _InferencePass(),
    _HierarchyPass(),
)
COMPILER_PASSES: tuple[CompilerPassSpec, ...] = tuple(
    compiler_pass.spec for compiler_pass in BUILTIN_COMPILER_PASSES
)
def compiler_pass_table() -> tuple[dict[str, object], ...]:
    """Serializable pass contracts for diagnostic and transport surfaces."""
    return tuple(asdict(spec) for spec in COMPILER_PASSES)


def compiler_pass_schema() -> dict[str, object]:
    return {
        "type": "array",
        "items": {"type": "string", "enum": list(COMPILER_PASS_NAMES)},
        "description": "Optional compiler passes: " + ", ".join(COMPILER_PASS_NAMES) + ".",
    }


def _pass_catalog(compiler_passes: tuple[CompilerPass, ...]) -> Mapping[str, CompilerPass]:
    catalog: dict[str, CompilerPass] = {}
    for compiler_pass in compiler_passes:
        name = compiler_pass.spec.name
        if not name:
            raise ValueError("compiler pass name must not be empty")
        if name in catalog:
            raise ValueError(f"duplicate GraphGraph compiler pass: {name}")
        if compiler_pass.spec.cache_scope not in {"none", "compiler"}:
            raise ValueError(f"invalid cache scope for compiler pass {name}: {compiler_pass.spec.cache_scope}")
        if compiler_pass.spec.cache_scope != "none" and not compiler_pass.spec.deterministic:
            raise ValueError(f"cached compiler pass must be deterministic: {name}")
        unknown = set(compiler_pass.spec.requires) - set(GRAPH_ARTIFACTS)
        if unknown:
            raise ValueError(f"compiler pass {name} requires unknown artifacts: {sorted(unknown)}")
        unknown_preserved = set(compiler_pass.spec.preserves) - set(GRAPH_ARTIFACTS)
        if unknown_preserved:
            raise ValueError(f"compiler pass {name} preserves unknown artifacts: {sorted(unknown_preserved)}")
        undeclared_outputs = set(GRAPH_ARTIFACTS) - (
            set(compiler_pass.spec.produces) | set(compiler_pass.spec.preserves)
        )
        if undeclared_outputs:
            raise ValueError(
                f"compiler pass {name} neither produces nor preserves graph artifacts: "
                f"{sorted(undeclared_outputs)}"
            )
        catalog[name] = compiler_pass
    return MappingProxyType(catalog)


def _pass_parameters(
    spec: CompilerPassSpec,
    request: CompileRequest,
    preferred_paths: tuple[str, ...],
) -> tuple[tuple[str, object], ...]:
    values: list[tuple[str, object]] = []
    for name in spec.parameters:
        value = preferred_paths if name == "preferred_paths" else getattr(request, name)
        if isinstance(value, list):
            value = tuple(value)
        values.append((name, value))
    return tuple(values)


def _copy_graph(graph: Graph) -> Graph:
    return Graph(dict(graph.nodes), list(graph.edges), dict(graph.metadata))


def _snapshot_outcome(outcome: PassOutcome) -> PassOutcome:
    """Protect a cached result from mutation through a returned public Graph."""
    return replace(outcome, graph=_copy_graph(outcome.graph))


def _restore_outcome(
    cached: PassOutcome,
    source: Graph,
    preserved: tuple[str, ...],
) -> PassOutcome:
    """Materialize a cache hit and rebase precisely preserved artifacts."""
    graph = cached.graph
    restored = Graph(
        dict(source.nodes if GRAPH_NODES in preserved else graph.nodes),
        list(source.edges if GRAPH_EDGES in preserved else graph.edges),
        dict(source.metadata if GRAPH_METADATA in preserved else graph.metadata),
    )
    return replace(cached, graph=restored)


def _pass_execution_receipt(
    spec: CompilerPassSpec,
    key: AnalysisKey,
    inputs: tuple[ArtifactFingerprint, ...],
    outputs: tuple[ArtifactFingerprint, ...],
    cache_state: str,
    graph: Graph,
) -> dict[str, object]:
    return {
        "pass": spec.name,
        "version": spec.version,
        "capabilities": list(spec.capabilities),
        "deterministic": spec.deterministic,
        "cache": {
            "scope": spec.cache_scope,
            "state": cache_state,
            "key": key.digest,
        },
        "parameters": dict(key.parameters),
        "requires": [asdict(item) for item in inputs],
        "products": list(spec.produces),
        "output_artifacts": [asdict(item) for item in outputs],
        "preserves": list(spec.preserves),
        "cost": {
            **asdict(spec.cost),
            "estimate": spec.cost.estimate(graph),
        },
    }


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
    pass_receipts: tuple[dict[str, object], ...] = field(default_factory=tuple)
    source_receipt: dict[str, object] = field(default_factory=dict)
    representation_receipt: dict[str, object] = field(default_factory=dict)
    format_selection: dict[str, object] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class CompileOutcome:
    packet: str
    receipt: CompilationReceipt
    graph: Graph
    route: QueryRoute
    plan: ContextPlan
    retrieval: RetrievalResult

    def envelope(self) -> str:
        return json.dumps({"receipt": asdict(self.receipt), "packet": self.packet}, indent=2, ensure_ascii=False)


class ContextCompiler:
    """Compile evidence graphs into bounded, validated context outcomes."""

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
        compiler_passes: tuple[CompilerPass, ...] = BUILTIN_COMPILER_PASSES,
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
        self.compiler_passes = _pass_catalog(compiler_passes)
        self.artifact_index = ArtifactIndex()
        self.analysis_cache: AnalysisCache[PassOutcome] = AnalysisCache()

    @classmethod
    def open(
        cls,
        graph_path: Path | None,
        *,
        graph: Graph | None = None,
        providers: tuple[EvidenceProvider, ...] | None = None,
        enable_evidence: bool = True,
        evidence_store_path: Path | None = None,
        changed_paths: tuple[str, ...] = (),
        refresh_evidence: bool = False,
        source_planning: bool = True,
        source_mode: str = DEFAULT_SOURCE_MODE,
        memory_scopes: tuple[str, ...] = DEFAULT_MEMORY_SCOPES,
        compiler_passes: tuple[CompilerPass, ...] = BUILTIN_COMPILER_PASSES,
    ) -> ContextCompiler:
        """Open the canonical compiler over a saved or resident evidence graph."""
        resolved = Path(graph_path) if graph_path is not None else None
        if graph is None:
            if resolved is None:
                raise ValueError("graph or graph_path is required")
            graph = load_any(resolved)

        active_providers = providers
        if active_providers is None:
            if enable_evidence:
                from .cpg import CpgEvidenceProvider

            active_providers = (
                (StructuralEvidenceProvider(), CpgEvidenceProvider())
                if enable_evidence
                else ()
            )
        evidence_store = None
        if enable_evidence and resolved is not None:
            from .evidence_store import EvidenceStore

            evidence_store = EvidenceStore(evidence_store_path or resolved.parent / "evidence.db")
        source_planner = None
        if source_planning and resolved is not None:
            source_planner = QuerySourcePlanner(
                project_root_for_graph(resolved),
                graph_path=resolved,
            )

        return cls(
            graph,
            active_providers,
            evidence_store=evidence_store,
            changed_paths=changed_paths,
            refresh_evidence=refresh_evidence,
            source_planner=source_planner,
            source_mode=source_mode,
            memory_scopes=memory_scopes,
            graph_path=resolved,
            compiler_passes=compiler_passes,
        )

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

    def transform(self, request: CompileRequest) -> TransformationOutcome:
        """Apply compiler passes without retrieval, selection, or rendering."""
        preferred_paths = _preferred_paths(
            self.graph,
            request.query,
            (),
            request.anchor_paths,
        )
        return self._transform(self.graph, request, preferred_paths)

    def _transform(
        self,
        graph: Graph,
        request: CompileRequest,
        preferred_paths: tuple[str, ...],
    ) -> TransformationOutcome:
        provider_receipts: list[CapabilityReceipt] = []
        receipts: list[dict[str, object]] = []
        applied: list[str] = []
        warnings: list[str] = []
        pass_context = PassContext(self, request, preferred_paths)
        for pass_name in request.passes:
            compiler_pass = self.compiler_passes.get(pass_name)
            if compiler_pass is None:
                raise ValueError(f"unknown GraphGraph compiler pass: {pass_name}")
            spec = compiler_pass.spec
            inputs = self.artifact_index.fingerprints(graph, spec.requires)
            parameters = _pass_parameters(spec, request, preferred_paths)
            key = AnalysisKey(spec.name, spec.version, parameters, inputs)
            cached = self.analysis_cache.get(key) if spec.cache_scope == "compiler" else None
            if cached is None:
                outcome = compiler_pass.run(pass_context, graph)
                cache_state = "miss" if spec.cache_scope == "compiler" else "disabled"
                if spec.cache_scope == "compiler":
                    self.analysis_cache.put(key, _snapshot_outcome(outcome))
            else:
                outcome = _restore_outcome(cached, graph, spec.preserves)
                cache_state = "hit"
            graph_outputs = tuple(
                artifact for artifact in spec.produces if artifact in GRAPH_ARTIFACTS
            )
            outputs = self.artifact_index.fingerprints(outcome.graph, graph_outputs)
            receipts.append(
                _pass_execution_receipt(
                    spec,
                    key,
                    inputs,
                    outputs,
                    cache_state,
                    graph,
                )
            )
            graph = outcome.graph
            provider_receipts.extend(outcome.provider_receipts)
            receipts.extend(asdict(receipt) for receipt in outcome.provider_receipts)
            receipts.extend(outcome.receipts)
            warnings.extend(outcome.warnings)
            applied.append(pass_name)
        return TransformationOutcome(
            graph=graph,
            passes=tuple(applied),
            receipts=tuple(receipts),
            provider_receipts=tuple(provider_receipts),
            warnings=tuple(warnings),
        )

    def compile(self, request: CompileRequest) -> CompileOutcome:
        if request.representation not in REPRESENTATION_NAMES:
            raise ValueError(
                f"unknown representation policy: {request.representation}; "
                f"expected one of {', '.join(REPRESENTATION_NAMES)}"
            )
        graph = self.graph
        source_seed_ids: tuple[str, ...] = ()
        source_preferred_paths: tuple[str, ...] = request.anchor_paths
        source_receipt: dict[str, object] = {}
        if self.source_planner is not None and not request.anchor_paths:
            source_plan = self.source_planner.plan(
                graph,
                request.query,
                mode=self.source_mode,
                memory_scopes=self.memory_scopes,
            )
            graph = source_plan.graph
            source_seed_ids = source_plan.seed_ids
            source_preferred_paths = source_plan.preferred_paths
            source_receipt = receipt_data(source_plan)
        elif request.anchor_paths:
            source_receipt = {
                "mode": "exact_paths",
                "lexical_strength": 0.0,
                "seed_ids": [],
                "sources": ["changed_paths"],
                "preferred_paths": list(request.anchor_paths),
                "warnings": [],
            }
        preferred_paths = _preferred_paths(
            graph,
            request.query,
            source_seed_ids,
            source_preferred_paths,
        )
        transformation = self._transform(graph, request, preferred_paths)
        graph = transformation.graph
        warnings = list(transformation.warnings)
        route = route_query(
            request.query,
            request.query_class,
            scopes=request.scopes,
        )
        plan = plan_context(
            route.query_class,
            request.query,
            max_nodes=request.max_nodes,
            packet=request.packet,
            hops=request.hops,
            anchor_limit=request.anchor_limit,
        )
        exact_direct_lookup = (
            route.query_class == "direct_lookup"
            and not request.anchor_paths
            and bool(search_nodes(
                graph,
                request.query,
                limit=1,
                scopes=request.scopes,
                exact_fast_path=True,
                exact_only=True,
            ))
        )
        if request.max_nodes is None and not exact_direct_lookup:
            plan = apply_shape_budget(graph, plan, request.query)
        retrieval = retrieve_context(
            graph,
            request.query,
            route.query_class,
            plan.hops,
            anchor_limit=request.anchor_limit,
            max_nodes=request.max_nodes,
            scopes=request.scopes,
            scope_mode=request.scope_mode,
            seed_ids=source_seed_ids,
            anchor_paths=request.anchor_paths,
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
            automatic_route=(request.query_class or "auto").strip().lower() == "auto",
        )
        if request.packet is None:
            plan = refine_plan_for_subgraph(
                plan,
                compute_subgraph_stats(graph, retrieval.nodes, retrieval.edges),
            )
        packet_format = request.packet or plan.packet
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
            # Target declarations own both cost-tournament alternatives and
            # their identity-preservation constraints. The compiler only
            # executes the declared policy against the bounded subgraph.
            source_target = target_spec(packet_format)
            adaptive = request.packet is None and bool(source_target.selection.alternatives)
            candidates = {packet_format: packet}
            candidate_safety: dict[str, bool] = {}
            if adaptive:
                for candidate_name in source_target.selection.alternatives:
                    candidate_target = target_spec(candidate_name)
                    identity_safe = candidate_target.identity.admissible(graph, retrieval.nodes)
                    candidate_safety[candidate_name] = identity_safe
                    if not identity_safe:
                        continue
                    candidate_packet = render_packet(
                        graph,
                        retrieval.nodes,
                        retrieval.edges,
                        candidate_name,
                    )
                    candidate_safety[candidate_name] = validate_packet(candidate_packet).ok
                    if candidate_safety[candidate_name]:
                        candidates[candidate_name] = candidate_packet
            costs = {name: estimate_tokens(text) for name, text in candidates.items()}
            chosen = min(costs, key=lambda name: (costs[name], name))
            packet_format = chosen
            packet = candidates[chosen]
            minimum = min(costs.values())
            format_selection = {
                "policy": source_target.selection.criterion if adaptive else "explicit_or_semantic_constraint",
                "candidates": costs,
                "chosen": chosen,
                "chosen_tokens": costs[chosen],
                "minimum_tokens": minimum,
                "ratio_to_minimum": round(costs[chosen] / max(1, minimum), 4),
                "candidate_safety": candidate_safety,
                # Compatibility receipts retained while consumers migrate to
                # the target-agnostic candidate map above.
                "label_identity_safe": target_spec("svo").identity.admissible(graph, retrieval.nodes),
                "svo_validation_safe": candidate_safety.get("svo", False),
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
        if packet and request.representation == "hybrid":
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
                        token_budget=request.representation_budget or 4096,
                    ),
                )
            except ValueError as exc:
                warning = f"hybrid representation fell back to flat: {exc}"
                warnings.append(warning)
                representation_receipt = {
                    "policy": "hybrid",
                    "status": "fallback_flat",
                    "reason": str(exc),
                    "token_budget": request.representation_budget or 4096,
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
            passes=transformation.passes,
            anchors=retrieval.starts,
            nodes=len(retrieval.nodes),
            edges=len(retrieval.edges),
            valid=(validation.ok if validation is not None else True) and not semantic_errors,
            structural_validation=structural_validation,
            semantic_validation=semantic_validation,
            answerability=answerability,
            provider_receipts=tuple(
                asdict(item) for item in transformation.provider_receipts
            ),
            pass_receipts=transformation.receipts,
            source_receipt=source_receipt,
            representation_receipt=representation_receipt,
            format_selection=format_selection,
            warnings=(
                tuple(warnings)
                + (validation.errors if validation is not None else ())
                + tuple(semantic_errors)
            ),
        )
        return CompileOutcome(packet, receipt, graph, route, plan, retrieval)


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
