"""Local-first platform capabilities built on GraphGraph's native graph model."""

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
    CompilationReceipt,
    CompilationResult,
    CompilerPassSpec,
    GraphProgram,
    GraphRuntime,
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
from .runtime import DEFAULT_MEMORY_SCOPES, DEFAULT_SOURCE_MODE, create_graph_runtime
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
    "CompilationResult",
    "CompilerPassSpec",
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
    "GraphProgram",
    "GraphRuntime",
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
    "create_graph_runtime",
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
