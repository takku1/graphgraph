"""Local-first platform capabilities, lazily loaded (PEP 562).

The platform package aggregates many heavy subsystems (benchmarking, the
compiler runtime, semantic embeddings, federation). Eagerly importing all of
them made every consumer -- including building the CLI parser, which only needs
``COMPILER_PASS_NAMES`` -- pay for the whole stack. Each public name now imports
only its defining submodule on first access.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

_LAZY_EXPORTS = {
    "BenchmarkCase": "benchmarking",
    "BenchmarkConfig": "benchmarking",
    "BenchmarkGates": "benchmarking",
    "COMPILER_PASSES": "compiler",
    "COMPILER_PASS_NAMES": "compiler",
    "CapabilityReceipt": "contracts",
    "ChangePacket": "change",
    "CompilationReceipt": "compiler",
    "CompileOutcome": "compiler",
    "CompileRequest": "compiler",
    "CompilerPass": "compiler",
    "CompilerPassSpec": "compiler",
    "PassCostModel": "compiler",
    "ContextCompiler": "compiler",
    "TransformationOutcome": "compiler",
    "ContinuationReceipt": "change",
    "CpgEvidenceProvider": "cpg",
    "DEFAULT_MEMORY_SCOPES": "compiler",
    "DEFAULT_SOURCE_MODE": "compiler",
    "EVIDENCE_STORE_VERSION": "evidence_store",
    "EmbeddingBackend": "embeddings",
    "Episode": "temporal",
    "EvaluationCase": "evaluation",
    "EvidenceBatch": "contracts",
    "EvidenceProvider": "contracts",
    "EvidenceStore": "evidence_store",
    "PassContext": "compiler",
    "PassOutcome": "compiler",
    "HttpEmbeddingBackend": "embeddings",
    "InferenceRule": "inference",
    "MemoryRecord": "memory",
    "MemoryStore": "memory",
    "PLATFORM_STATE_VERSION": "persistence",
    "ProjectRegistry": "federation",
    "ProviderRegistry": "contracts",
    "PythonAstEvidenceProvider": "contracts",
    "QuerySourcePlanner": "source_planner",
    "SemanticBackendMismatch": "semantic",
    "SemanticIndex": "semantic",
    "SourcePlan": "source_planner",
    "SourcePlannerReceipt": "source_planner",
    "StructuralEvidenceProvider": "contracts",
    "TemporalStore": "temporal",
    "active_backend_name": "embeddings",
    "build_change_packet": "change",
    "build_continuation_receipt": "change",
    "build_hierarchy": "intelligence",
    "build_repair_context": "repair",
    "compiler_pass_schema": "compiler",
    "detect_communities": "intelligence",
    "evaluate_cases": "evaluation",
    "federate_graphs": "federation",
    "graph_as_of": "temporal",
    "infer_edges": "inference",
    "ingest_runtime_trace": "tracing",
    "load_benchmark_config": "benchmarking",
    "migrate_platform_state": "persistence",
    "repair_context_json": "repair",
    "reset_backend_cache": "embeddings",
    "resolve_backend": "embeddings",
    "run_benchmark": "benchmarking",
    "set_backend": "embeddings",
}


def __getattr__(name: str):
    module_path = _LAZY_EXPORTS.get(name)
    if module_path is not None:
        module = importlib.import_module(f".{module_path}", __name__)
        value = getattr(module, name)
        globals()[name] = value
        return value
    try:
        submodule = importlib.import_module(f".{name}", __name__)
    except ImportError:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from None
    globals()[name] = submodule
    return submodule


def __dir__() -> list[str]:
    return sorted(__all__)


if TYPE_CHECKING:
    from .benchmarking import (
        BenchmarkCase,
        BenchmarkConfig,
        BenchmarkGates,
        load_benchmark_config,
        run_benchmark,
    )
    from .change import ChangePacket, ContinuationReceipt, build_change_packet, build_continuation_receipt
    from .compiler import (
        COMPILER_PASS_NAMES,
        COMPILER_PASSES,
        DEFAULT_MEMORY_SCOPES,
        DEFAULT_SOURCE_MODE,
        CompilationReceipt,
        CompileOutcome,
        CompileRequest,
        CompilerPass,
        CompilerPassSpec,
        ContextCompiler,
        PassContext,
        PassCostModel,
        PassOutcome,
        TransformationOutcome,
        compiler_pass_schema,
    )
    from .contracts import (
        CapabilityReceipt,
        EvidenceBatch,
        EvidenceProvider,
        ProviderRegistry,
        PythonAstEvidenceProvider,
        StructuralEvidenceProvider,
    )
    from .cpg import CpgEvidenceProvider
    from .embeddings import (
        EmbeddingBackend,
        HttpEmbeddingBackend,
        active_backend_name,
        reset_backend_cache,
        resolve_backend,
        set_backend,
    )
    from .evaluation import EvaluationCase, evaluate_cases
    from .evidence_store import EVIDENCE_STORE_VERSION, EvidenceStore
    from .federation import ProjectRegistry, federate_graphs
    from .inference import InferenceRule, infer_edges
    from .intelligence import build_hierarchy, detect_communities
    from .memory import MemoryRecord, MemoryStore
    from .persistence import PLATFORM_STATE_VERSION, migrate_platform_state
    from .repair import build_repair_context, repair_context_json
    from .semantic import SemanticBackendMismatch, SemanticIndex
    from .source_planner import QuerySourcePlanner, SourcePlan, SourcePlannerReceipt
    from .temporal import Episode, TemporalStore, graph_as_of
    from .tracing import ingest_runtime_trace

__all__ = [
    "EmbeddingBackend",
    "HttpEmbeddingBackend",
    "SemanticBackendMismatch",
    "active_backend_name",
    "reset_backend_cache",
    "resolve_backend",
    "set_backend",
    "CapabilityReceipt",
    "BenchmarkCase",
    "BenchmarkConfig",
    "BenchmarkGates",
    "ChangePacket",
    "COMPILER_PASSES",
    "COMPILER_PASS_NAMES",
    "CompilationReceipt",
    "CompileOutcome",
    "CompileRequest",
    "CompilerPass",
    "CompilerPassSpec",
    "PassCostModel",
    "ContextCompiler",
    "TransformationOutcome",
    "ContinuationReceipt",
    "CpgEvidenceProvider",
    "DEFAULT_MEMORY_SCOPES",
    "DEFAULT_SOURCE_MODE",
    "Episode",
    "EvaluationCase",
    "EvidenceBatch",
    "EvidenceProvider",
    "EvidenceStore",
    "EVIDENCE_STORE_VERSION",
    "PassContext",
    "PassOutcome",
    "InferenceRule",
    "MemoryRecord",
    "MemoryStore",
    "PLATFORM_STATE_VERSION",
    "ProjectRegistry",
    "ProviderRegistry",
    "PythonAstEvidenceProvider",
    "QuerySourcePlanner",
    "SemanticIndex",
    "StructuralEvidenceProvider",
    "SourcePlan",
    "SourcePlannerReceipt",
    "TemporalStore",
    "build_change_packet",
    "build_continuation_receipt",
    "build_hierarchy",
    "build_repair_context",
    "compiler_pass_schema",
    "repair_context_json",
    "detect_communities",
    "evaluate_cases",
    "federate_graphs",
    "graph_as_of",
    "infer_edges",
    "ingest_runtime_trace",
    "load_benchmark_config",
    "migrate_platform_state",
    "run_benchmark",
]
