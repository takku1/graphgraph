"""Local-first platform capabilities built on GraphGraph's native graph model."""

from .benchmarking import (
    BenchmarkCase,
    BenchmarkConfig,
    BenchmarkGates,
    load_benchmark_config,
    run_benchmark,
)
from .change import ChangePacket, ContinuationReceipt, build_change_packet, build_continuation_receipt
from .compiler import CompilationReceipt, CompilationResult, GraphProgram, GraphRuntime
from .contracts import (
    CapabilityReceipt,
    EvidenceBatch,
    EvidenceProvider,
    ProviderRegistry,
    PythonAstEvidenceProvider,
    StructuralEvidenceProvider,
)
from .cpg import CpgEvidenceProvider
from .evaluation import EvaluationCase, evaluate_cases
from .evidence_store import EVIDENCE_STORE_VERSION, EvidenceStore
from .federation import ProjectRegistry, federate_graphs
from .inference import InferenceRule, infer_edges
from .intelligence import build_hierarchy, detect_communities
from .memory import MemoryRecord, MemoryStore
from .persistence import PLATFORM_STATE_VERSION, migrate_platform_state
from .repair import build_repair_context, repair_context_json
from .semantic import SemanticIndex
from .source_planner import QuerySourcePlanner, SourcePlan, SourcePlannerReceipt
from .temporal import Episode, TemporalStore, graph_as_of
from .tracing import ingest_runtime_trace

__all__ = [
    "CapabilityReceipt",
    "BenchmarkCase",
    "BenchmarkConfig",
    "BenchmarkGates",
    "ChangePacket",
    "CompilationReceipt",
    "CompilationResult",
    "ContinuationReceipt",
    "CpgEvidenceProvider",
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
