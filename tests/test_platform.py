from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from graphgraph import Edge, Graph, Node
from graphgraph.cli.parser import build_parser
from graphgraph.io import save_graph
from graphgraph.mcp import dispatch
from graphgraph.platform import (
    PLATFORM_STATE_VERSION,
    BenchmarkCase,
    BenchmarkConfig,
    BenchmarkGates,
    CapabilityReceipt,
    CompileRequest,
    CompilerPassSpec,
    ContextCompiler,
    CpgEvidenceProvider,
    Episode,
    EvaluationCase,
    EvidenceBatch,
    EvidenceStore,
    MemoryStore,
    PassContext,
    PassOutcome,
    ProjectRegistry,
    ProviderRegistry,
    PythonAstEvidenceProvider,
    QuerySourcePlanner,
    SemanticIndex,
    StructuralEvidenceProvider,
    TemporalStore,
    build_change_packet,
    build_hierarchy,
    build_repair_context,
    evaluate_cases,
    federate_graphs,
    graph_as_of,
    infer_edges,
    ingest_runtime_trace,
    migrate_platform_state,
    run_benchmark,
)
from graphgraph.platform.interop import export_graph
from graphgraph.platform.server import create_server, install_git_hooks, serve_graph
from graphgraph.runtime.state import atomic_write_text, file_lock
from graphgraph.scanner.frontends import TreeSitterExtractor
from graphgraph.scanner.source_ir import SourceIR, clear_syntax_ir_cache
from graphgraph.services.compiler_driver import CompilerDriver, DriverRequest


def platform_graph() -> Graph:
    nodes = {
        "app": Node("app", "app.py", "python", "src/app.py", "L1 application entry"),
        "run": Node("run", "run", "function", "src/app.py", "L3 def run()"),
        "db": Node("db", "db.py", "python", "src/db.py", "L1 database adapter"),
        "query": Node("query", "query", "function", "src/db.py", "L4 def query()"),
        "test_app": Node("test_app", "test_app.py", "python", "tests/test_app.py", "L1 tests application"),
        "config": Node("config", "pyproject.toml", "toml", "pyproject.toml"),
    }
    edges = [
        Edge("app", "run", "contains"),
        Edge("run", "query", "calls"),
        Edge("db", "query", "contains"),
        Edge("test_app", "run", "calls"),
        Edge("config", "app", "imports"),
    ]
    return Graph(nodes, edges, {"project": "sample"})


class PlatformTest(unittest.TestCase):
    def test_platform_state_migrations_and_concurrent_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "memory.json").write_text(
                json.dumps([{
                    "id": "old",
                    "scope": "project",
                    "content": "legacy memory",
                }]),
                encoding="utf-8",
            )
            (root / "projects.json").write_text('{"projects":[]}\n', encoding="utf-8")
            (root / "semantic.json").write_text(
                '{"version":1,"dimensions":32,"vectors":{}}\n',
                encoding="utf-8",
            )
            (root / "evidence.json").write_text(
                '{"version":1,"providers":{}}\n',
                encoding="utf-8",
            )
            (root / "kv_cache.json").write_text('{"entries":{}}\n', encoding="utf-8")
            (root / "episodes.jsonl").write_text(
                json.dumps({
                    "id": "old",
                    "timestamp": "2026-01-01T00:00:00+00:00",
                    "kind": "event",
                    "summary": "legacy episode",
                }) + "\n",
                encoding="utf-8",
            )
            receipt = migrate_platform_state(root)
            self.assertTrue(receipt["ok"])
            self.assertEqual(len(receipt["migrated"]), 6)
            self.assertEqual(receipt["evidence_backend"], "sqlite")
            self.assertTrue((root / "evidence.db").exists())
            for name in ("memory.json", "projects.json", "semantic.json", "evidence.json", "kv_cache.json"):
                self.assertEqual(json.loads((root / name).read_text(encoding="utf-8"))["version"], PLATFORM_STATE_VERSION)
            self.assertEqual(
                json.loads((root / "episodes.jsonl").read_text(encoding="utf-8"))["version"],
                PLATFORM_STATE_VERSION,
            )
            self.assertEqual(MemoryStore(root / "memory.json").read()[0].content, "legacy memory")

            store = MemoryStore(root / "concurrent-memory.json")
            threads = [
                threading.Thread(target=store.remember, args=(f"memory {index}",))
                for index in range(12)
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=5)
            self.assertEqual(len(store.read()), 12)

    def test_cpg_provider_normalizes_multiple_languages(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            files = {
                "sample.py": (
                    "def normalize(value: int) -> int:\n"
                    "    result = value\n"
                    "    if result:\n"
                    "        result += 1\n"
                    "    return result\n"
                ),
                "sample.js": (
                    "function process(input) {\n"
                    "  let total = input;\n"
                    "  if (total) { total = total + 1; }\n"
                    "  return total;\n"
                    "}\n"
                ),
                "sample.ts": (
                    "function convert(value: number): string {\n"
                    "  const result: string = String(value);\n"
                    "  return result;\n"
                    "}\n"
                ),
                "sample.go": (
                    "package sample\n"
                    "func compute(value int) int {\n"
                    "  total := value\n"
                    "  for total > 0 { total-- }\n"
                    "  return total\n"
                    "}\n"
                ),
                "sample.rs": (
                    "fn adjust(value: i32) -> i32 {\n"
                    "  let mut result = value;\n"
                    "  if result > 0 { result -= 1; }\n"
                    "  result\n"
                    "}\n"
                ),
                "Sample.java": (
                    "class Config {\n"
                    "  int retries;\n"
                    "  String execute(int value) {\n"
                    "    String result = String.valueOf(value);\n"
                    "    return result;\n"
                    "  }\n"
                    "}\n"
                ),
            }
            for name, text in files.items():
                (root / name).write_text(text, encoding="utf-8")
            graph = Graph({
                "py_normalize": Node("py_normalize", "normalize", "function", "sample.py", "L1", source=str(root / "sample.py")),
                "js_process": Node("js_process", "process", "function", "sample.js", "L1", source=str(root / "sample.js")),
                "ts_convert": Node("ts_convert", "convert", "function", "sample.ts", "L1", source=str(root / "sample.ts")),
                "go_compute": Node("go_compute", "compute", "function", "sample.go", "L2", source=str(root / "sample.go")),
                "rs_adjust": Node("rs_adjust", "adjust", "function", "sample.rs", "L1", source=str(root / "sample.rs")),
                "java_config": Node("java_config", "Config", "class", "Sample.java", "L1", source=str(root / "Sample.java")),
                "java_execute": Node("java_execute", "execute", "method", "Sample.java", "L3", source=str(root / "Sample.java")),
            })
            enriched, receipts = ProviderRegistry((CpgEvidenceProvider(),)).apply(graph)
            relations = {edge.type for edge in enriched.edges}
            self.assertTrue(
                {"reads", "writes", "control_flow", "field_of", "type_of", "returns"}
                <= relations
            )
            languages = {
                fact.split(":", 1)[1]
                for node in enriched.nodes.values()
                for fact in node.facts
                if fact.startswith("language:")
            }
            self.assertTrue({"py", "js", "ts", "go", "rs", "java"} <= languages)
            self.assertEqual(receipts[0].provider, "cpg")
            self.assertEqual(receipts[0].paths_processed, 6)
            self.assertTrue(all(edge.evidence and edge.source_location for edge in enriched.edges))

    def test_cpg_reuses_scanner_syntax_for_unchanged_source_revision(self) -> None:
        clear_syntax_ir_cache()
        with tempfile.TemporaryDirectory() as tmp:
            source_path = Path(tmp) / "sample.js"
            text = "function process(value) { let result = value; return result; }\n"
            source_path.write_text(text, encoding="utf-8")
            source = SourceIR(source_path, "sample.js", "sample_js", text)
            extraction = TreeSitterExtractor().extract_symbols(
                [source],
                max_total_symbols=20,
            )
            graph = Graph(extraction.nodes, extraction.edges)

            with patch(
                "graphgraph.platform.cpg.parse_with_timeout",
                side_effect=AssertionError("CPG reparsed an unchanged SourceIR"),
            ):
                batch = CpgEvidenceProvider().collect(graph)

        self.assertEqual(batch.receipt.artifacts_compiled, 0)
        self.assertEqual(batch.receipt.artifacts_reused, 1)
        self.assertTrue(batch.receipt.cache_hit)

    def test_cpg_receipt_preserves_concrete_grammar_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "sample.go"
            source.write_text("package sample\nfunc run() {}\n", encoding="utf-8")
            graph = Graph({
                "run": Node(
                    "run",
                    "run",
                    "function",
                    "sample.go",
                    "L2",
                    source=str(source),
                ),
            })

            with (
                patch("graphgraph.platform.cpg.parser_for_suffix", return_value=None),
                patch(
                    "graphgraph.platform.cpg.parser_unavailable_reason",
                    return_value="PermissionError: grammar cache is read-only",
                ),
            ):
                batch = CpgEvidenceProvider().collect(graph)

        self.assertIn(
            "sample.go:grammar_unavailable:PermissionError: grammar cache is read-only",
            batch.receipt.warnings,
        )

    def test_multi_repository_benchmark_enforces_quality_and_cost_gates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first_path = root / "first.json"
            second_path = root / "second.json"
            save_graph(platform_graph(), first_path)
            save_graph(Graph(
                {
                    "worker": Node("worker", "worker", "function", "src/worker.py"),
                    "queue": Node("queue", "queue", "service", "src/queue.py"),
                },
                [Edge("worker", "queue", "uses")],
            ), second_path)
            config = BenchmarkConfig(
                projects={"app": first_path, "worker": second_path},
                cases=(
                    BenchmarkCase(
                        "app",
                        "database query call",
                        expected_nodes=("src/db.py",),
                        expected_relations=("calls",),
                    ),
                    BenchmarkCase(
                        "worker",
                        "worker queue",
                        expected_nodes=("src/worker.py", "src/queue.py"),
                        expected_relations=("uses",),
                    ),
                ),
                gates=BenchmarkGates(
                    min_projects=2,
                    min_pass_rate=1.0,
                    min_mean_recall=1.0,
                    min_relation_recall=1.0,
                    max_p95_latency_ms=5000,
                    max_mean_tokens=2000,
                ),
                repeats=2,
                warmups=1,
            )
            report = run_benchmark(config)
            self.assertTrue(report["ok"])
            self.assertEqual(report["projects"], 2)
            self.assertEqual(report["passed"], 2)
            self.assertTrue(all(result["valid"] for result in report["results"]))

            strict = BenchmarkConfig(
                projects=config.projects,
                cases=config.cases,
                gates=BenchmarkGates(max_mean_tokens=1),
            )
            failed = run_benchmark(strict)
            self.assertFalse(failed["ok"])
            self.assertFalse(failed["gates"]["mean_tokens"])

    def test_query_source_planner_projects_all_sources_into_hot_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            graph_path = root / "graph.json"
            graph = platform_graph()
            save_graph(graph, graph_path)
            SemanticIndex(root / "semantic.json").build(graph)
            memory = MemoryStore(root / "memory.json")
            memory.remember(
                "Runtime database rollback procedure",
                scope="project",
                related_nodes=("db",),
            )
            memory.remember("Runtime database personal preference", scope="user")
            TemporalStore(root / "episodes.jsonl").append(Episode(
                "incident",
                "2026-01-01T00:00:00+00:00",
                "incident",
                "Runtime database rollback incident",
                related_nodes=("query",),
            ))
            foreign_path = root / "foreign.json"
            save_graph(Graph({
                "payments": Node(
                    "payments",
                    "payments runtime coordinator",
                    "service",
                    "src/payments.py",
                )
            }), foreign_path)
            ProjectRegistry(root / "projects.json").register("payments", root, foreign_path)
            (root / "runtime-trace.jsonl").write_text(
                json.dumps({"caller": "run", "callee": "query", "count": 4}) + "\n",
                encoding="utf-8",
            )

            plan = QuerySourcePlanner(root).plan(
                graph,
                "runtime database rollback payments",
                mode="all",
            )
            self.assertEqual(
                set(plan.receipt.sources),
                {"semantic", "memory", "temporal", "federation", "runtime_trace"},
            )
            self.assertEqual(plan.receipt.memories, 1)
            self.assertGreater(plan.receipt.federated_nodes, 0)
            self.assertEqual(plan.receipt.trace_edges, 1)
            self.assertIn("remembers", {edge.type for edge in plan.graph.edges})
            self.assertIn("records", {edge.type for edge in plan.graph.edges})
            self.assertIn("observed_calls", {edge.type for edge in plan.graph.edges})
            self.assertTrue(any(node_id.startswith("payments::") for node_id in plan.graph.nodes))

            payload = json.loads(CompilerDriver().compile(DriverRequest(
                query="runtime database rollback payments",
                graph_path=graph_path,
                show_anchors=True,
                json_output=True,
                source_mode="all",
            ))[0])
            self.assertEqual(
                set(payload["retrieval"]["sources"]["sources"]),
                {"semantic", "memory", "temporal", "federation", "runtime_trace"},
            )
            self.assertTrue(payload["packet"].startswith("#gg"))

    def test_named_federated_project_is_a_reserved_coverage_obligation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            graph_path = root / "base.json"
            save_graph(
                Graph({"fixture": Node("fixture", "fixture", "function", "src/base.py")}),
                graph_path,
            )
            foreign_path = root / "foreign.json"
            save_graph(
                Graph({"remote": Node("remote", "fixture Root", "function", "src/flow.py")}),
                foreign_path,
            )
            ProjectRegistry(root / "projects.json").register(
                "fixture",
                root / "foreign",
                foreign_path,
            )

            plan = QuerySourcePlanner(root, graph_path=graph_path).plan(
                Graph({"fixture": Node("fixture", "fixture", "function", "src/base.py")}),
                "fixture",
                mode="auto",
            )

            self.assertIn("federation", plan.receipt.sources)
            self.assertEqual(plan.receipt.federated_projects, 1)
            self.assertTrue(plan.seed_ids[0].startswith("fixture::"))
            self.assertIn("fixture::remote", plan.graph.nodes)

    def test_named_federated_context_covers_current_and_foreign_projects(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            graph_path = root / "flask.json"
            save_graph(
                Graph(
                    {"dispatch": Node("dispatch", "flask request dispatch", "function", "src/app.py")},
                    metadata={"source_root": str(root)},
                ),
                graph_path,
            )
            foreign_path = root / "fixture.json"
            save_graph(
                Graph({"root": Node("root", "fixture Root flow", "function", "src/flow.py")}),
                foreign_path,
            )
            registry = ProjectRegistry(root / "projects.json")
            registry.register("flask", root, graph_path)
            registry.register("fixture", root / "fixture", foreign_path)

            payload = json.loads(CompilerDriver().compile(DriverRequest(
                query="Compare flask request dispatch with fixture Root flow",
                graph_path=graph_path,
                show_anchors=True,
                json_output=True,
                source_mode="all",
            ))[0])

            coverage = payload["retrieval"]["project_coverage"]
            self.assertEqual(coverage["required"], ["fixture", "flask"])
            self.assertEqual(coverage["represented"], ["fixture", "flask"])
            self.assertEqual(coverage["missing"], [])

    def test_exact_query_projects_graph_local_memory_automatically(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            graph_dir = root / ".graphgraph"
            graph_dir.mkdir()
            graph_path = graph_dir / "graph.json"
            graph = Graph(
                nodes={"run": Node("run", "run", "function", "src/app.py")},
                edges=[],
                metadata={"source_root": str(root)},
            )
            save_graph(graph, graph_path)
            MemoryStore(graph_dir / "memory.json").remember(
                "The run deployment requires the blue-green rollback decision.",
                scope="project",
                related_nodes=("run",),
            )

            payload = json.loads(
                CompilerDriver().compile(DriverRequest(
                    query="run",
                    graph_path=graph_path,
                    show_anchors=True,
                    json_output=True,
                    source_mode="auto",
                ))[0]
            )

            sources = payload["retrieval"]["sources"]
            self.assertTrue(sources["exact_fast_path"])
            self.assertEqual(sources["memories"], 1)
            self.assertIn("memory", sources["sources"])
            self.assertIn("blue-green rollback", payload["packet"])

    def test_query_finds_nested_state_next_to_nonstandard_graph_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            graph_path = root / "fixture.gg"
            graph = Graph(
                nodes={"run": Node("run", "run", "function", "src/app.py")},
                metadata={"source_root": str(root)},
            )
            save_graph(graph, graph_path)
            state_dir = root / ".graphgraph"
            state_dir.mkdir()
            MemoryStore(state_dir / "memory.json").remember(
                "The run deployment uses the violet rollback marker.",
                scope="isolated",
                related_nodes=("run",),
            )

            payload = json.loads(
                CompilerDriver().compile(DriverRequest(
                    query="run violet rollback",
                    graph_path=graph_path,
                    show_anchors=True,
                    json_output=True,
                    memory_scopes=("isolated",),
                ))[0]
            )

            self.assertEqual(payload["retrieval"]["sources"]["memories"], 1)
            self.assertIn("violet rollback", payload["packet"])

    def test_persisted_evidence_is_incremental_and_versioned(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / "first.py"
            second = root / "second.py"
            first.write_text("def first():\n    value = 1\n    return value\n", encoding="utf-8")
            second.write_text("def second():\n    value = 2\n    return value\n", encoding="utf-8")
            graph = Graph({
                "first": Node("first", "first", "function", "first.py", source=str(first)),
                "second": Node("second", "second", "function", "second.py", source=str(second)),
            })
            store = EvidenceStore(root / "evidence.json")
            registry = ProviderRegistry((PythonAstEvidenceProvider(),))

            _, initial = registry.apply_persisted(graph, store)
            self.assertEqual(initial[0].paths_processed, 2)
            self.assertEqual(initial[0].paths_restored, 0)
            self.assertFalse(initial[0].cache_hit)

            _, cached = registry.apply_persisted(graph, store)
            self.assertEqual(cached[0].paths_processed, 0)
            self.assertEqual(cached[0].paths_restored, 2)
            self.assertTrue(cached[0].cache_hit)

            first.write_text("def first():\n    value = 3\n    return value\n", encoding="utf-8")
            _, refreshed = registry.apply_persisted(graph, store)
            self.assertEqual(refreshed[0].paths_processed, 1)
            self.assertEqual(refreshed[0].paths_restored, 1)

            class PythonAstV2(PythonAstEvidenceProvider):
                version = "2"

            _, invalidated = ProviderRegistry((PythonAstV2(),)).apply_persisted(graph, store)
            self.assertEqual(invalidated[0].paths_processed, 2)
            self.assertEqual(invalidated[0].paths_restored, 0)

    def test_sqlite_evidence_reads_query_preferred_partitions(self) -> None:
        class PartitionProvider:
            name = "partition"
            version = "1"
            capabilities = ("partition",)
            incremental = True
            max_nodes = 1
            max_edges = 1

            def supports_path(self, path: str) -> bool:
                return path.endswith(".py")

            def collect(self, graph: Graph, paths: tuple[str, ...] = ()) -> EvidenceBatch:
                path = paths[0]
                node_id = f"evidence:{path}"
                return EvidenceBatch(
                    nodes=(Node(node_id, path, "evidence", path),),
                    receipt=CapabilityReceipt(
                        self.name,
                        self.version,
                        self.capabilities,
                        nodes_emitted=1,
                        paths_processed=1,
                    ),
                )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / "first.py"
            second = root / "second.py"
            first.write_text("first = 1\n", encoding="utf-8")
            second.write_text("second = 2\n", encoding="utf-8")
            graph = Graph({
                "first": Node("first", "first", "function", "first.py", source=str(first)),
                "second": Node("second", "second", "function", "second.py", source=str(second)),
            })
            registry = ProviderRegistry((PartitionProvider(),))
            store = EvidenceStore(root / "evidence.db")

            enriched, initial = registry.apply_persisted(
                graph,
                store,
                preferred_paths=("second.py",),
            )
            self.assertIn("evidence:second.py", enriched.nodes)
            self.assertNotIn("evidence:first.py", enriched.nodes)
            self.assertEqual(initial[0].paths_processed, 2)
            self.assertEqual(initial[0].nodes_truncated, 1)

            _, cached = registry.apply_persisted(
                graph,
                store,
                preferred_paths=("first.py",),
            )
            self.assertTrue(cached[0].cache_hit)
            self.assertEqual(cached[0].paths_restored, 2)

    def test_evidence_receipts_conserve_emitted_candidates(self) -> None:
        class LedgerProvider:
            name = "ledger"
            version = "1"
            capabilities = ("ledger",)
            incremental = False

            def collect(self, graph: Graph, paths: tuple[str, ...] = ()) -> EvidenceBatch:
                return EvidenceBatch(
                    nodes=(
                        Node("app", "duplicate"),
                        Node("new", "accepted"),
                    ),
                    edges=(
                        Edge("app", "run", "contains"),
                        Edge("new", "run", "uses"),
                        Edge("missing", "run", "uses"),
                    ),
                    receipt=CapabilityReceipt(
                        self.name,
                        self.version,
                        self.capabilities,
                        nodes_emitted=3,
                        edges_emitted=4,
                        nodes_truncated=1,
                        edges_truncated=1,
                    ),
                )

        _, receipts = ProviderRegistry((LedgerProvider(),)).apply(platform_graph())
        receipt = receipts[0]
        self.assertEqual(
            receipt.nodes_emitted,
            receipt.nodes_accepted
            + receipt.nodes_duplicate
            + receipt.nodes_rejected
            + receipt.nodes_truncated,
        )
        self.assertEqual(
            receipt.edges_emitted,
            receipt.edges_accepted
            + receipt.edges_duplicate
            + receipt.edges_rejected
            + receipt.edges_truncated,
        )

    def test_evidence_provider_emits_typed_relations_and_receipt(self) -> None:
        graph, receipts = ProviderRegistry((StructuralEvidenceProvider(),)).apply(platform_graph())
        self.assertIn(("test_app", "app", "tests"), {(edge.source, edge.target, edge.type) for edge in graph.edges})
        self.assertEqual(receipts[0].provider, "structural")
        self.assertGreaterEqual(receipts[0].edges_emitted, 1)

    def test_python_ast_provider_emits_data_control_field_and_type_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "sample.py"
            source.write_text(
                "class Config:\n"
                "    retries: int = 3\n\n"
                "def execute(value: int) -> str:\n"
                "    result = value + retries\n"
                "    if result:\n"
                "        return str(result)\n"
                "    return ''\n",
                encoding="utf-8",
            )
            graph = Graph({
                "config_class": Node("config_class", "Config", "class", "sample.py", "L1 class Config:", source=str(source)),
                "execute_fn": Node("execute_fn", "execute", "function", "sample.py", "L4 def execute", source=str(source)),
            })
            enriched, receipts = ProviderRegistry((PythonAstEvidenceProvider(),)).apply(graph)
            relations = {edge.type for edge in enriched.edges}
            self.assertTrue({"reads", "writes", "control_flow", "field_of", "type_of", "returns"} <= relations)
            self.assertEqual(receipts[0].provider, "python_ast")
            self.assertTrue(all(edge.evidence and edge.source_location for edge in enriched.edges))

    def test_compiler_runs_passes_to_valid_packet(self) -> None:
        result = ContextCompiler(platform_graph(), (StructuralEvidenceProvider(),)).compile(CompileRequest(
            "where does run call database query", passes=("evidence", "inference", "hierarchy"), max_nodes=20
        ))
        self.assertTrue(result.receipt.valid)
        self.assertEqual(result.receipt.passes, ("evidence", "inference", "hierarchy"))
        self.assertTrue(result.packet.startswith("#gg"))
        self.assertTrue(result.receipt.provider_receipts)

    def test_compiler_accepts_an_injected_pass_through_one_seam(self) -> None:
        class MarkerPass:
            spec = CompilerPassSpec("marker", "Attach a test-only compiler receipt.")

            def run(self, context: PassContext, graph: Graph) -> PassOutcome:
                if context.request.query != "run":
                    raise AssertionError("pass received the wrong compilation request")
                return PassOutcome(graph, warnings=("marker ran",))

        result = ContextCompiler(
            platform_graph(),
            compiler_passes=(MarkerPass(),),
        ).compile(CompileRequest("run", query_class="direct_lookup", passes=("marker",)))

        self.assertEqual(result.receipt.passes, ("marker",))
        self.assertIn("marker ran", result.receipt.warnings)

    def test_compiler_cache_invalidates_only_required_artifacts(self) -> None:
        runs = 0

        class NodeAnalysisPass:
            spec = CompilerPassSpec(
                "node_analysis",
                "Derive metadata only from the node artifact.",
                requires=("graph.nodes",),
                produces=("graph.metadata",),
                preserves=("graph.nodes", "graph.edges"),
                capabilities=("node_count",),
                deterministic=True,
                cache_scope="compiler",
            )

            def run(self, context: PassContext, graph: Graph) -> PassOutcome:
                nonlocal runs
                del context
                runs += 1
                return PassOutcome(Graph(
                    dict(graph.nodes),
                    list(graph.edges),
                    {**graph.metadata, "node_count": str(len(graph.nodes))},
                ))

        graph = platform_graph()
        compiler = ContextCompiler(graph, compiler_passes=(NodeAnalysisPass(),))
        request = CompileRequest("", passes=("node_analysis",))

        first = compiler.transform(request)
        first.graph.metadata["node_count"] = "poisoned public result"
        graph.edges.append(Edge("query", "config", "reads"))
        preserved = compiler.transform(request)

        self.assertEqual(runs, 1)
        self.assertEqual(preserved.receipts[0]["cache"]["state"], "hit")
        self.assertEqual(preserved.graph.metadata["node_count"], "6")
        self.assertIn(Edge("query", "config", "reads"), preserved.graph.edges)

        graph.nodes["worker"] = Node("worker", "worker", "function", "src/worker.py")
        invalidated = compiler.transform(request)

        self.assertEqual(runs, 2)
        self.assertEqual(invalidated.receipts[0]["cache"]["state"], "miss")
        self.assertEqual(invalidated.graph.metadata["node_count"], "7")
        required = invalidated.receipts[0]["requires"]
        self.assertEqual([item["artifact"] for item in required], ["graph.nodes"])
        self.assertTrue(required[0]["digest"])

    def test_compiler_transform_uses_the_same_pass_catalog_without_retrieval(self) -> None:
        outcome = ContextCompiler(platform_graph()).transform(
            CompileRequest("", passes=("inference", "hierarchy"))
        )

        self.assertEqual(outcome.passes, ("inference", "hierarchy"))
        self.assertEqual(outcome.receipts[-1]["pass"], "hierarchy")
        self.assertIn("communities", outcome.graph.metadata)

    def test_compiler_preserves_document_scope_during_routing(self) -> None:
        path = "docs/roadmap/gaps.md"
        graph = Graph(nodes={
            "ABSENT": Node(
                "ABSENT",
                "Symbolic PAC learning",
                "paragraph",
                path,
                facts=("* `[ ]` **Symbolic PAC learning:** Not implemented.",),
            ),
        })

        result = ContextCompiler(graph).compile(CompileRequest(
            "Identify one capability currently marked absent.",
            scopes=(path,),
        ))

        self.assertEqual(result.route.query_class, "doc_summary")
        self.assertIn("explicit document scope", result.route.reasons)
        self.assertEqual(result.retrieval.starts, ("ABSENT",))

    def test_compiler_exact_paths_bypass_auxiliary_source_planning(self) -> None:
        class UnexpectedSourcePlanner:
            def plan(self, *_args: object, **_kwargs: object) -> object:
                raise AssertionError("exact paths must bypass global source planning")

        graph = Graph(nodes={
            "PLAN": Node("PLAN", "plan_writes", "method", "src/planner.rs"),
        })
        result = ContextCompiler(
            graph,
            source_planner=UnexpectedSourcePlanner(),  # type: ignore[arg-type]
        ).compile(CompileRequest(
            "plan write deduplication",
            query_class="direct_lookup",
            anchor_paths=("src/planner.rs",),
        ))

        self.assertEqual(result.retrieval.starts, ("PLAN",))
        self.assertEqual(result.receipt.source_receipt["mode"], "exact_paths")
        self.assertEqual(
            result.receipt.source_receipt["preferred_paths"],
            ["src/planner.rs"],
        )

    def test_change_packet_reports_breaking_symbol_and_impact(self) -> None:
        before = platform_graph()
        after = Graph({key: value for key, value in before.nodes.items() if key != "query"}, [
            edge for edge in before.edges if edge.source != "query" and edge.target != "query"
        ])
        packet = build_change_packet(before, after)
        self.assertIn("query", packet.removed_nodes)
        self.assertTrue(any("removed function query" in item for item in packet.breaking_changes))
        self.assertIn("run", packet.impacted_nodes)
        self.assertEqual(len(packet.cursor), 16)

    def test_semantic_index_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "semantic.json"
            SemanticIndex(path).build(platform_graph())
            matches = SemanticIndex.load(path).query("database adapter query")
            self.assertIn(matches[0][0], {"db", "query"})

    def test_temporal_store_projection_and_as_of(self) -> None:
        current = platform_graph()
        graph = Graph(
            {
                node_id: replace(node, created_at="2024-01-01T00:00:00+00:00")
                for node_id, node in current.nodes.items()
            },
            [
                replace(edge, valid_from="2024-01-01T00:00:00+00:00")
                for edge in current.edges
            ],
            dict(current.metadata),
        )
        graph.edges.append(Edge("run", "db", "uses", valid_from="2025-01-01T00:00:00+00:00", valid_to="2025-02-01T00:00:00+00:00", active=False))
        january = graph_as_of(graph, "2025-01-15T00:00:00+00:00")
        march = graph_as_of(graph, "2025-03-01T00:00:00+00:00")
        self.assertIn(("run", "db", "uses"), {(edge.source, edge.target, edge.type) for edge in january.edges})
        self.assertNotIn(("run", "db", "uses"), {(edge.source, edge.target, edge.type) for edge in march.edges})
        with tempfile.TemporaryDirectory() as tmp:
            store = TemporalStore(Path(tmp) / "episodes.jsonl")
            store.append(Episode("one", "2025-01-01T00:00:00+00:00", "decision", "Use DB", related_nodes=("db",)))
            store.append(Episode("two", "2025-02-01T00:00:00+00:00", "decision", "Replace DB", supersedes="one"))
            projected = store.project(platform_graph())
            self.assertFalse(projected.nodes["episode:one"].active)
            self.assertIn(("episode:two", "episode:one", "supersedes"), {(e.source, e.target, e.type) for e in projected.edges})

    def test_as_of_before_repository_history_is_empty_and_explicit(self) -> None:
        graph = platform_graph()
        graph.metadata["history_valid_from"] = "2025-01-01T12:17:18+00:00"

        before = graph_as_of(graph, "2025-01-01T12:17:00+00:00")
        after = graph_as_of(graph, "2025-01-01T12:18:00+00:00")

        self.assertEqual(before.nodes, {})
        self.assertEqual(before.edges, [])
        self.assertEqual(before.metadata["temporal_status"], "before_recorded_history")
        self.assertEqual(after.nodes, {})
        self.assertEqual(after.edges, [])
        self.assertEqual(
            after.metadata["temporal_status"],
            "historical_reconstruction_unavailable",
        )
        self.assertIn("refusing", after.metadata["temporal_reason"])

    def test_recent_changes_without_change_evidence_abstains(self) -> None:
        graph = Graph(
            nodes={
                "README": Node(
                    "README",
                    "Change history",
                    "section",
                    "README.md",
                    summary="Recent changes and project history",
                )
            },
            edges=[],
        )

        result = ContextCompiler(graph).compile(
            CompileRequest("What changed recently?", query_class="recent_changes")
        )

        self.assertFalse(result.retrieval.metadata["change_evidence"]["proven"])
        answerability = result.retrieval.metadata["answerability"]
        self.assertEqual(answerability["status"], "incomplete")
        self.assertTrue(answerability["abstained"])
        self.assertEqual(answerability["confidence"], 0.15)

    def test_memory_store_scopes_search_and_projection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(Path(tmp) / "memory.json")
            record = store.remember("Database migrations require a rollback test", scope="project", related_nodes=("db",))
            store.remember("Prefer short answers", scope="user")
            self.assertEqual(store.search("rollback database", scopes=("project",))[0].id, record.id)
            projected = store.project(platform_graph(), scopes=("project",))
            self.assertIn(f"memory:{record.id}", projected.nodes)
            self.assertIn("remembers", {edge.type for edge in projected.edges})

    def test_memory_auto_anchors_exact_symbols_with_ambiguity_receipt(self) -> None:
        graph = Graph(
            nodes={
                "router": Node(
                    "router",
                    "Router",
                    "class",
                    "src/router.py",
                ),
                "primary": Node(
                    "primary",
                    "search_path",
                    "method",
                    "src/router.py",
                    parent="router",
                ),
                "secondary": Node(
                    "secondary",
                    "search_path",
                    "function",
                    "src/helpers.py",
                ),
                "file_collision": Node(
                    "file_collision",
                    "search_path",
                    "python",
                    "tests/search_path.py",
                ),
            },
        )
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(Path(tmp) / "memory.json")
            record = store.remember(
                "Keep the PCRE2 decision near Router::search_path and search_path.",
                graph=graph,
            )
            reloaded = store.read()[0]
            projected = store.project(graph)

        self.assertEqual(record.related_nodes, ("primary", "secondary"))
        self.assertEqual(reloaded.related_nodes, record.related_nodes)
        self.assertEqual(
            reloaded.anchor_receipt["ambiguous"][0]["mention"],
            "search_path",
        )
        self.assertEqual(
            reloaded.anchor_receipt["ambiguous"][0]["candidate_count"],
            2,
        )
        self.assertNotIn("file_collision", record.related_nodes)
        self.assertEqual(
            {
                edge.target
                for edge in projected.edges
                if edge.source == f"memory:{record.id}"
                and edge.type == "remembers"
            },
            {"primary", "secondary"},
        )

    def test_memory_anchor_limit_is_explicit_and_deterministic(self) -> None:
        graph = Graph(
            nodes={
                "one": Node("one", "target_symbol", "function", "one.py"),
                "two": Node("two", "target_symbol", "function", "two.py"),
                "prose_collision": Node(
                    "prose_collision",
                    "alias",
                    "function",
                    "aliases.py",
                ),
            }
        )
        with tempfile.TemporaryDirectory() as tmp:
            record = MemoryStore(Path(tmp) / "memory.json").remember(
                "Alias validation decision about target_symbol",
                graph=graph,
                anchor_limit=1,
            )

        self.assertEqual(record.related_nodes, ("one",))
        self.assertNotIn("prose_collision", record.related_nodes)
        self.assertTrue(record.anchor_receipt["truncated"])
        self.assertEqual(record.anchor_receipt["limit"], 1)

    def test_federation_namespaces_and_links_repositories(self) -> None:
        federated = federate_graphs({"api": platform_graph(), "worker": platform_graph()})
        self.assertIn("api::run", federated.nodes)
        self.assertIn("worker::run", federated.nodes)
        self.assertIn("cross_repo", {edge.type for edge in federated.edges})
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            graph_path = root / "graph.json"
            save_graph(platform_graph(), graph_path)
            registry = ProjectRegistry(root / "projects.json")
            registry.register("api", root, graph_path)
            self.assertEqual(len(registry.build().nodes), len(platform_graph().nodes) + 1)

    def test_hierarchy_and_inference_are_bounded_graph_passes(self) -> None:
        graph, receipt = infer_edges(platform_graph(), max_edges=5)
        self.assertLessEqual(receipt["added"], 5)
        self.assertIn("uses", {edge.type for edge in graph.edges})
        hierarchy = build_hierarchy(graph)
        self.assertTrue(any(node.kind == "community" for node in hierarchy.nodes.values()))
        self.assertEqual(int(hierarchy.metadata["communities"]), sum(node.kind == "community" for node in hierarchy.nodes.values()))

    def test_runtime_trace_and_repair_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "trace.jsonl"
            path.write_text(json.dumps({"caller": "run", "callee": "query", "count": 3}) + "\n", encoding="utf-8")
            graph, receipt = ingest_runtime_trace(platform_graph(), path)
            observed = next(edge for edge in graph.edges if edge.type == "observed_calls")
            self.assertEqual(observed.weight, 3)
            self.assertEqual(receipt["edges_emitted"], 1)
        repair = build_repair_context(platform_graph(), "RuntimeError in run at src/app.py:3")
        self.assertTrue(repair["receipt"]["grounded"])
        self.assertIn("run", repair["anchors"])
        self.assertIn("tests/test_app.py", repair["tests"])
        windows = build_repair_context(platform_graph(), r"RuntimeError at C:\repo\src\app.py:3")
        self.assertIn("app", windows["anchors"])

    def test_portable_exports(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for suffix, format_name, marker in [
                ("json", "json", '"nodes"'),
                ("jsonl", "jsonl", '"record": "node"'),
                ("graphml", "graphml", "<graphml"),
                ("cypher", "cypher", "MERGE (n:GraphGraphNode"),
            ]:
                path = root / f"graph.{suffix}"
                receipt = export_graph(platform_graph(), path, format_name)
                self.assertEqual(receipt["format"], format_name)
                self.assertIn(marker, path.read_text(encoding="utf-8"))

    def test_cross_project_evaluation(self) -> None:
        report = evaluate_cases({"sample": platform_graph()}, [
            EvaluationCase("sample", "database adapter", ("src/db.py",)),
            EvaluationCase("missing", "anything", ("x",)),
        ])
        self.assertEqual(report["cases"], 2)
        self.assertEqual(report["passed"], 1)
        self.assertGreater(report["results"][0]["reciprocal_rank"], 0)
        self.assertFalse(report["ok"])

    def test_platform_cli_and_mcp_contracts(self) -> None:
        args = build_parser().parse_args(["platform", "compile", "database", "--pass", "inference"])
        self.assertEqual(args.platform_action, "compile")
        self.assertEqual(args.passes, ["inference"])
        listed = dispatch({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
        assert listed is not None
        names = {tool["name"] for tool in listed["result"]["tools"]}
        self.assertTrue({"compile_context", "repair_context", "graph_change", "memory_context", "graph_at_time"} <= names)
        with tempfile.TemporaryDirectory() as tmp:
            graph_path = Path(tmp) / "graph.json"
            save_graph(platform_graph(), graph_path)
            response = dispatch({
                "jsonrpc": "2.0", "id": 2, "method": "tools/call",
                "params": {"name": "compile_context", "arguments": {"query": "database query", "graph_path": str(graph_path)}},
            })
            assert response is not None
            data = json.loads(response["result"]["content"][0]["text"])
            self.assertTrue(data["receipt"]["valid"])
            memory_path = Path(tmp) / "memory.json"
            remembered = dispatch({
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "memory_context",
                    "arguments": {
                        "operation": "add",
                        "text": "Keep the retry decision near `run`",
                        "graph_path": str(graph_path),
                        "store_path": str(memory_path),
                    },
                },
            })
            assert remembered is not None
            memory_data = json.loads(
                remembered["result"]["content"][0]["text"]
            )
            self.assertEqual(memory_data["related_nodes"], ["run"])
            self.assertEqual(
                memory_data["anchor_receipt"]["accepted"],
                ["run"],
            )

    def test_memory_cli_accepts_observed_text_and_search_aliases(self) -> None:
        added = build_parser().parse_args(
            ["platform", "memory", "add", "--text", "Remember search_path"]
        )
        searched = build_parser().parse_args(
            ["platform", "memory", "search", "search path"]
        )

        self.assertEqual(added.text_option, "Remember search_path")
        self.assertEqual(searched.operation, "search")
        self.assertEqual(searched.text, "search path")

    def test_http_service_exposes_status_and_compiler(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            graph_path = Path(tmp) / "graph.json"
            save_graph(platform_graph(), graph_path)
            server = create_server(graph_path, port=0)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base = f"http://127.0.0.1:{server.server_address[1]}"
                with urllib.request.urlopen(base + "/api/status", timeout=5) as response:
                    status = json.loads(response.read())
                    self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
                    self.assertIsNone(response.headers["Access-Control-Allow-Origin"])
                self.assertEqual(status["nodes"], 6)
                with urllib.request.urlopen(base + "/api/status", timeout=5) as response:
                    cached_status = json.loads(response.read())
                self.assertGreaterEqual(cached_status["graph_cache"]["hits"], 1)
                with urllib.request.urlopen(base + "/api/query?q=database", timeout=5) as response:
                    result = json.loads(response.read())
                self.assertTrue(result["receipt"]["valid"])
                request = urllib.request.Request(
                    base + "/api/query",
                    data=json.dumps({
                        "query": "database query",
                        "passes": ["evidence"],
                    }).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(request, timeout=10) as response:
                    posted = json.loads(response.read())
                self.assertTrue(posted["receipt"]["valid"])
                for route, payload in (
                    ("memory", {"content": "Database rollback runbook", "related_nodes": ["db"]}),
                    ("episode", {"id": "incident", "summary": "Database incident", "related_nodes": ["db"]}),
                    ("trace", {"caller": "run", "callee": "query", "count": 2}),
                ):
                    request = urllib.request.Request(
                        base + f"/api/{route}",
                        data=json.dumps(payload).encode("utf-8"),
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    with urllib.request.urlopen(request, timeout=5) as response:
                        self.assertTrue(json.loads(response.read())["ok"])
                self.assertEqual(len(MemoryStore(Path(tmp) / "memory.json").read()), 1)
                self.assertEqual(len(TemporalStore(Path(tmp) / "episodes.jsonl").read()), 1)
                self.assertTrue((Path(tmp) / "runtime-trace.jsonl").exists())
                request = urllib.request.Request(
                    base + "/api/query",
                    data=json.dumps({"query": "Database rollback runbook"}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(request, timeout=10) as response:
                    sourced = json.loads(response.read())
                self.assertEqual(sourced["receipt"]["source_receipt"]["memories"], 1)
                self.assertIn("memory", sourced["receipt"]["source_receipt"]["sources"])
                with urllib.request.urlopen(base + "/api/graph?limit=3", timeout=5) as response:
                    topology = json.loads(response.read())
                self.assertEqual(len(topology["nodes"]), 3)
                self.assertTrue(topology["truncated"])
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

    def test_http_service_requires_auth_for_configured_or_remote_access(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            graph_path = Path(tmp) / "graph.json"
            save_graph(platform_graph(), graph_path)
            with self.assertRaisesRegex(ValueError, "requires an API token"):
                create_server(graph_path, host="0.0.0.0", port=0)
            server = create_server(
                graph_path,
                port=0,
                token="secret",
                allowed_origins=("https://client.example",),
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base = f"http://127.0.0.1:{server.server_address[1]}"
                with self.assertRaises(urllib.error.HTTPError) as unauthorized:
                    urllib.request.urlopen(base + "/api/status", timeout=5)
                self.assertEqual(unauthorized.exception.code, 401)
                request = urllib.request.Request(
                    base + "/api/status",
                    headers={
                        "Authorization": "Bearer secret",
                        "Origin": "https://client.example",
                    },
                )
                with urllib.request.urlopen(request, timeout=5) as response:
                    self.assertEqual(
                        response.headers["Access-Control-Allow-Origin"],
                        "https://client.example",
                    )
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

    def test_git_hook_install_is_idempotent_and_preserves_existing_hook(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", str(root)], check=True, capture_output=True)
            subprocess.run(
                ["git", "-C", str(root), "config", "core.hooksPath", ".git/hooks"],
                check=True,
            )
            hooks = Path(
                subprocess.run(
                    ["git", "-C", str(root), "rev-parse", "--path-format=absolute", "--git-path", "hooks"],
                    check=True,
                    capture_output=True,
                    text=True,
                ).stdout.strip()
            )
            post_commit = hooks / "post-commit"
            post_commit.write_text("#!/bin/sh\necho existing\n", encoding="utf-8")
            install_git_hooks(root, executable="gg")
            install_git_hooks(root, executable="graphgraph")
            content = post_commit.read_text(encoding="utf-8")
            self.assertIn("echo existing", content)
            self.assertEqual(content.count("# >>> graphgraph managed >>>"), 1)
            self.assertIn("graphgraph context", content)

    @unittest.skipUnless(shutil.which("git"), "Git is required")
    def test_git_hook_install_uses_custom_hooks_path_and_linked_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            root = parent / "main"
            linked = parent / "linked"
            subprocess.run(["git", "init", str(root)], check=True, capture_output=True)
            subprocess.run(
                ["git", "-C", str(root), "config", "user.email", "tests@example.invalid"],
                check=True,
            )
            subprocess.run(["git", "-C", str(root), "config", "user.name", "GraphGraph Tests"], check=True)
            (root / "tracked.txt").write_text("initial\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "add", "tracked.txt"], check=True)
            subprocess.run(["git", "-C", str(root), "commit", "-m", "initial"], check=True, capture_output=True)
            subprocess.run(
                ["git", "-C", str(root), "worktree", "add", "-b", "linked-test", str(linked)],
                check=True,
                capture_output=True,
            )
            subprocess.run(
                ["git", "-C", str(linked), "config", "core.hooksPath", ".custom-hooks"],
                check=True,
            )

            installed = install_git_hooks(linked)

            expected = linked / ".custom-hooks"
            self.assertEqual({path.parent.resolve() for path in installed}, {expected.resolve()})
            self.assertTrue((expected / "post-commit").is_file())
            self.assertTrue((linked / ".graphgraph").is_dir())

    @unittest.skipUnless(shutil.which("git"), "Git is required")
    def test_new_hook_recreates_receipt_directory_before_redirect(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", str(root)], check=True, capture_output=True)
            subprocess.run(
                ["git", "-C", str(root), "config", "core.hooksPath", ".git/hooks"],
                check=True,
            )
            subprocess.run(
                ["git", "-C", str(root), "config", "user.email", "tests@example.invalid"],
                check=True,
            )
            subprocess.run(["git", "-C", str(root), "config", "user.name", "GraphGraph Tests"], check=True)
            executable = root / "fake-graphgraph"
            executable.write_text("#!/bin/sh\nprintf '{\"ok\":true}\\n'\n", encoding="utf-8", newline="\n")
            executable.chmod(executable.stat().st_mode | 0o111)
            installed = install_git_hooks(root, executable="./fake-graphgraph")
            (root / ".graphgraph").rmdir()
            (root / "tracked.txt").write_text("initial\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "add", "tracked.txt"], check=True)

            commit = subprocess.run(
                ["git", "-C", str(root), "commit", "-m", "exercise hook"],
                capture_output=True,
                text=True,
            )

            self.assertEqual(commit.returncode, 0, commit.stderr)
            self.assertEqual(
                json.loads((root / ".graphgraph" / "hook-receipt.json").read_text(encoding="utf-8")),
                {"ok": True},
            )
            self.assertIn("mkdir -p .graphgraph", installed[0].read_text(encoding="utf-8"))

    def test_serve_graph_uses_bound_port_for_ready_and_browser_urls(self) -> None:
        server = SimpleNamespace(server_address=("127.0.0.1", 43123), serve_forever=lambda: None)
        ready: list[str] = []

        class ImmediateTimer:
            def __init__(self, _delay, callback):  # noqa: ANN001
                self.callback = callback

            def start(self) -> None:
                self.callback()

        with (
            patch("graphgraph.platform.server.create_server", return_value=server),
            patch("graphgraph.platform.server.threading.Timer", ImmediateTimer),
            patch("graphgraph.platform.server.webbrowser.open") as browser_open,
        ):
            serve_graph(
                Path("graph.gg"),
                port=0,
                open_browser=True,
                on_ready=ready.append,
            )

        self.assertEqual(ready, ["http://127.0.0.1:43123"])
        browser_open.assert_called_once_with("http://127.0.0.1:43123")

    def test_platform_serve_announces_only_the_post_bind_url(self) -> None:
        args = build_parser().parse_args(
            ["platform", "serve", "--graph", "graph.gg", "--port", "0"]
        )
        with (
            patch("graphgraph.platform.server.serve_graph") as mocked_serve,
            patch("builtins.print") as mocked_print,
        ):
            args.func(args)
            mocked_print.assert_not_called()
            mocked_serve.call_args.kwargs["on_ready"]("http://127.0.0.1:43123")

        mocked_print.assert_called_once_with(
            "GraphGraph console: http://127.0.0.1:43123",
            flush=True,
        )


class SemanticEmbeddingBackendTest(unittest.TestCase):
    """The optional embedding backend: real semantics when present, hash when
    not, and a hard refusal to mix the two coordinate spaces."""

    class _ConceptBackend:
        """Toy meaning-space so paraphrases with no shared tokens still align."""

        name = "test:concept-v1"
        _MAP = {
            "delete": (1, 0, 0), "remove": (1, 0, 0), "erase": (1, 0, 0), "purge": (1, 0, 0),
            "user": (0, 1, 0), "account": (0, 1, 0), "profile": (0, 1, 0), "person": (0, 1, 0),
            "render": (0, 0, 1), "dashboard": (0, 0, 1), "draw": (0, 0, 1), "view": (0, 0, 1),
        }

        def embed(self, texts):
            out = []
            for text in texts:
                vec = [0.0, 0.0, 0.0]
                for word in text.lower().replace("_", " ").split():
                    for i, x in enumerate(self._MAP.get(word, (0, 0, 0))):
                        vec[i] += x
                out.append(vec)
            return out

    def _graph(self):
        return Graph(
            nodes={
                "A": Node("A", "delete_user_account", "function", "accounts.py",
                          summary="removes a user and purges their records"),
                "B": Node("B", "render_dashboard", "function", "ui.py",
                          summary="draws the main dashboard view"),
            },
            edges=[],
        )

    def tearDown(self) -> None:
        from graphgraph.platform import reset_backend_cache

        reset_backend_cache()

    def test_offline_hash_misses_token_disjoint_paraphrase(self) -> None:
        # This is the reviewer's 0/4 in miniature: no shared tokens, no hit.
        from graphgraph.platform import SemanticIndex, set_backend

        # Pin the offline hash rather than inferring it from the environment:
        # `reset_backend_cache` only clears the cache, so resolution would pick
        # up FastEmbed wherever `graphgraph[semantic]` happens to be installed
        # and this test would assert against the wrong backend.
        set_backend(None)
        index = SemanticIndex().build(self._graph())
        self.assertEqual(index.backend_name, "hash")
        self.assertEqual(index.query("erase somebody's profile", limit=1), [])

    def test_embedding_backend_recovers_the_paraphrase(self) -> None:
        # The whole point: a real meaning-space resolves the paraphrase to the
        # deletion function the hash could not reach.
        from graphgraph.platform import SemanticIndex, set_backend

        set_backend(self._ConceptBackend())
        index = SemanticIndex().build(self._graph())
        self.assertEqual(index.backend_name, "test:concept-v1")
        hits = index.query("erase a person", limit=1)
        self.assertTrue(hits)
        self.assertEqual(hits[0][0], "A")

    def test_semantic_extra_gates_the_local_backend(self) -> None:
        import os
        from unittest.mock import patch

        from graphgraph.platform import embeddings

        os.environ.pop(embeddings.EMBED_URL_ENV, None)
        # Absent `[semantic]` extra -> the offline hash, unchanged.
        with patch.object(embeddings, "_local_backend_available", return_value=False):
            embeddings.reset_backend_cache()
            self.assertIsNone(embeddings.resolve_backend())
            self.assertEqual(embeddings.active_backend_name(), embeddings.HASH_BACKEND_NAME)
        # Extra installed -> the local ONNX backend auto-registers, no config.
        with patch.object(embeddings, "_local_backend_available", return_value=True):
            embeddings.reset_backend_cache()
            self.assertIsInstance(embeddings.resolve_backend(), embeddings.FastEmbedBackend)
            self.assertTrue(embeddings.active_backend_name().startswith("fastembed:"))
        embeddings.reset_backend_cache()

    def test_explicit_embed_url_overrides_the_local_backend(self) -> None:
        import os
        from unittest.mock import patch

        from graphgraph.platform import embeddings

        with patch.dict(os.environ, {embeddings.EMBED_URL_ENV: "http://localhost:9/embed"}):
            with patch.object(embeddings, "_local_backend_available", return_value=True):
                embeddings.reset_backend_cache()
                self.assertIsInstance(embeddings.resolve_backend(), embeddings.HttpEmbeddingBackend)
        embeddings.reset_backend_cache()

    def test_fastembed_backend_is_lazy(self) -> None:
        # Constructing the backend must not import fastembed or load a model.
        from graphgraph.platform.embeddings import FastEmbedBackend

        backend = FastEmbedBackend()
        self.assertTrue(backend.name.startswith("fastembed:"))
        self.assertIsNone(backend._model)

    def test_backend_failure_degrades_to_offline_hash(self) -> None:
        # path-to-10 #7 (cold-start/offline): a real backend that fails at
        # runtime -- an offline first-use model download, a dead endpoint -- must
        # degrade to the offline hash index rather than crashing the scan/query.
        import warnings

        from graphgraph.platform import SemanticIndex

        class _FailingBackend:
            name = "http:offline-model"

            def embed(self, texts):
                raise RuntimeError("model download failed: offline")

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            index = SemanticIndex().build(self._graph(), backend=_FailingBackend())
        self.assertEqual(index.backend_name, "hash")   # honest provenance
        self.assertTrue(index.vectors)                  # still built
        self.assertTrue(any("offline hash" in str(w.message) for w in caught))
        # The degraded index is still queryable offline.
        self.assertIsNotNone(index.query("erase somebody's profile", limit=1))

    def test_hash_index_is_flagged_when_a_real_backend_is_available(self) -> None:
        # The provenance guard only refuses in one direction: a real embedding
        # index queried without its backend. The reverse -- a hash index while a
        # model is installed -- is arithmetically safe and therefore silent, and
        # that silence made a stale index look like broken conceptual retrieval
        # (0/7 on held-out tasks while the model itself ranked 6/7 top-1).
        from graphgraph.platform import SemanticIndex
        from graphgraph.platform import semantic as semantic_module

        class _Model:
            name = "fastembed:test-model"

            def embed(self, texts):
                return [[0.1] * 8 for _ in texts]

        # Build as a core install would: no backend resolvable -> hash vectors.
        original = semantic_module.resolve_backend
        semantic_module.resolve_backend = lambda: None
        try:
            index = SemanticIndex().build(self._graph())
        finally:
            semantic_module.resolve_backend = original
        self.assertEqual(index.backend_name, "hash")

        # A model is available -> the hash index is a downgrade, and says so.
        reason = index.downgraded_reason(backend=_Model())
        self.assertIn("hash", reason)
        self.assertIn("rebuilt", reason)

        # Core install (no backend at all) -> hash is correct, stay silent.
        semantic_module.resolve_backend = lambda: None
        try:
            self.assertEqual(index.downgraded_reason(), "")
        finally:
            semantic_module.resolve_backend = original

        # An index already built by a real backend is never a downgrade.
        index.backend_name = "fastembed:test-model"
        self.assertEqual(index.downgraded_reason(backend=_Model()), "")

    def test_provenance_guard_refuses_cross_space_query(self) -> None:
        from graphgraph.platform import (
            SemanticBackendMismatch,
            SemanticIndex,
            reset_backend_cache,
            set_backend,
        )

        set_backend(self._ConceptBackend())
        index = SemanticIndex().build(self._graph())

        # Backend vanishes -> embedding vectors vs a hash query vector is
        # garbage, so the query must refuse rather than score it.
        reset_backend_cache()
        with self.assertRaises(SemanticBackendMismatch):
            index.query("erase a person")

    def test_index_is_stale_when_backend_changes(self) -> None:
        from graphgraph.platform import SemanticIndex, reset_backend_cache, set_backend

        reset_backend_cache()
        graph = self._graph()
        hash_index = SemanticIndex().build(graph)
        self.assertTrue(hash_index.is_current(graph))
        # Same graph, but an embedding backend is now active: the hash index is
        # no longer reusable and must be rebuilt.
        set_backend(self._ConceptBackend())
        self.assertFalse(hash_index.is_current(graph))

    def test_hash_path_is_unaffected_when_no_backend(self) -> None:
        # Regression fence: with no backend configured, behaviour must be
        # byte-identical to before the abstraction existed.
        from graphgraph.platform import SemanticIndex, reset_backend_cache

        reset_backend_cache()
        index = SemanticIndex().build(self._graph())
        by_name = index.query("delete user account", limit=1)
        self.assertEqual(by_name[0][0], "A")


class EmbeddingBackendHttpIntegrationTest(unittest.TestCase):
    """The env-var -> HTTP -> index path that the mock-backend unit tests skip.

    The unit tests inject a backend via set_backend(); a black-box caller can
    only set GRAPHGRAPH_EMBED_URL. This exercises resolve_backend() reading the
    env, HttpEmbeddingBackend doing the real HTTP round-trip, and a paraphrase
    with no shared tokens being recovered through it -- the whole GATE 23
    plumbing end to end, against a stdlib stub standing in for a real model.
    """

    _CONCEPT = {
        "delete": (1, 0, 0), "remove": (1, 0, 0), "erase": (1, 0, 0),
        "purge": (1, 0, 0), "removes": (1, 0, 0),
        "user": (0, 1, 0), "account": (0, 1, 0), "person": (0, 1, 0),
        "records": (0, 1, 0), "profile": (0, 1, 0),
        "render": (0, 0, 1), "dashboard": (0, 0, 1), "draws": (0, 0, 1),
    }

    @classmethod
    def _embed(cls, text: str) -> list[float]:
        vec = [0.0, 0.0, 0.0]
        for word in text.lower().replace("_", " ").replace(".", " ").split():
            for i, x in enumerate(cls._CONCEPT.get(word, (0, 0, 0))):
                vec[i] += x
        return vec

    def setUp(self) -> None:
        from http.server import BaseHTTPRequestHandler, HTTPServer

        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):  # noqa: A002 - silence test server
                pass

            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length) or b"{}")
                payload = json.dumps(
                    {"embeddings": [outer._embed(t) for t in body.get("input", [])]}
                ).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        host, port = self.server.server_address
        self.url = f"http://{host}:{port}"

    def tearDown(self) -> None:
        from graphgraph.platform import reset_backend_cache

        self.server.shutdown()
        self.server.server_close()
        os.environ.pop("GRAPHGRAPH_EMBED_URL", None)
        reset_backend_cache()

    def test_env_configured_backend_recovers_paraphrase_over_http(self) -> None:
        from graphgraph.platform import SemanticIndex, reset_backend_cache, set_backend

        graph = Graph(
            nodes={
                "A": Node("A", "delete_user_account", "function", "accounts.py",
                          summary="removes a user and purges their records"),
                "B": Node("B", "render_dashboard", "function", "ui.py",
                          summary="draws the main dashboard"),
            },
            edges=[],
        )

        # Offline: the token-disjoint paraphrase does not resolve. Pinned, not
        # inferred, so an installed FastEmbed cannot satisfy this baseline.
        set_backend(None)
        self.assertEqual(SemanticIndex().build(graph).query("erase a person", limit=1), [])

        # Env-configured HTTP backend: same paraphrase now resolves to A, and
        # the index records the http backend name (not "hash").
        os.environ["GRAPHGRAPH_EMBED_URL"] = self.url
        reset_backend_cache()
        index = SemanticIndex().build(graph)
        self.assertTrue(index.backend_name.startswith("http:"))
        hits = index.query("erase a person", limit=1)
        self.assertTrue(hits)
        self.assertEqual(hits[0][0], "A")


class FileLockTest(unittest.TestCase):
    """Windows delete-pending contention, found as a flaky concurrent write.

    ``test_platform_state_migrations_and_concurrent_writes`` failed
    intermittently under full-suite load with a PermissionError escaping a
    worker thread. These reproduce that deterministically rather than by
    hammering the real lock.
    """

    def test_transient_permission_error_is_retried_as_contention(self) -> None:
        # Transient sharing/permission failures while opening the rendezvous
        # file are contention and must be waited out.
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "state.json"
            real_open = os.open
            calls: list[int] = []

            def flaky_open(path, flags, *args, **kwargs):
                if str(path).endswith(".lock") and not calls:
                    calls.append(1)
                    raise PermissionError(13, "Access is denied")
                return real_open(path, flags, *args, **kwargs)

            with patch("graphgraph.runtime.state.os.open", flaky_open):
                with file_lock(target, timeout=5.0):
                    acquired = True

            self.assertTrue(acquired)
            self.assertEqual(len(calls), 1)
            # The stable inode prevents a waiter from locking an unlinked old
            # inode while another process creates a new lock at this path.
            self.assertTrue(target.with_name("state.json.lock").exists())

    def test_persistent_permission_error_surfaces_the_real_cause(self) -> None:
        # A read-only directory also raises PermissionError forever. Retrying
        # until timeout must not bury it under a misleading TimeoutError.
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "state.json"

            def always_denied(path, flags, *args, **kwargs):
                raise PermissionError(13, "Access is denied")

            with patch("graphgraph.runtime.state.os.open", always_denied):
                with self.assertRaises(PermissionError):
                    with file_lock(target, timeout=0.1):
                        pass

    def test_write_survives_a_reader_holding_the_destination(self) -> None:
        # file_lock serializes writers, but readers take no lock. On Windows
        # os.replace fails while any handle is open on the destination, so a
        # reader landing mid-write silently lost the write entirely.
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "state.json"
            atomic_write_text(target, "first")

            def hold_briefly() -> None:
                with open(target, "r", encoding="utf-8") as reader:
                    reader.read()
                    time.sleep(0.3)

            holder = threading.Thread(target=hold_briefly)
            holder.start()
            time.sleep(0.05)
            atomic_write_text(target, "second")
            holder.join()

            self.assertEqual(target.read_text(encoding="utf-8"), "second")

    def test_failed_write_does_not_strand_a_temp_file(self) -> None:
        # A permanently blocked replace must surface the real error and clean
        # up, rather than littering .tmp files beside the target.
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "state.json"
            atomic_write_text(target, "first")

            def always_denied(self, _target):  # noqa: ANN001
                raise PermissionError(5, "Access is denied")

            with patch.object(Path, "replace", always_denied):
                with self.assertRaises(PermissionError):
                    atomic_write_text(target, "second")

            stranded = [p.name for p in Path(tmp).iterdir() if ".tmp" in p.name]
            self.assertEqual(stranded, [])
            self.assertEqual(target.read_text(encoding="utf-8"), "first")

    def test_held_lock_still_times_out(self) -> None:
        # The FileExistsError path keeps its original TimeoutError contract.
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "state.json"
            with file_lock(target, timeout=5.0):
                with self.assertRaises(TimeoutError):
                    with file_lock(target, timeout=0.1):
                        pass

    def test_live_lock_is_not_stolen_when_age_threshold_expires(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "state.json"
            inside: list[str] = []
            overlap: list[str] = []
            barrier = threading.Barrier(2)

            def holder() -> None:
                with file_lock(target, stale_seconds=0.01):
                    inside.append("holder")
                    barrier.wait()
                    time.sleep(0.12)
                    inside.remove("holder")

            def waiter() -> None:
                barrier.wait()
                time.sleep(0.03)
                with file_lock(target, stale_seconds=0.01):
                    overlap.extend(inside)

            first = threading.Thread(target=holder)
            second = threading.Thread(target=waiter)
            first.start()
            second.start()
            first.join()
            second.join()

            self.assertEqual(overlap, [])

    def test_lock_is_recoverable_after_owner_process_exits_without_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "state.json"
            script = (
                "import os, sys\n"
                "from pathlib import Path\n"
                "from graphgraph.runtime.state import file_lock\n"
                "with file_lock(Path(sys.argv[1])):\n"
                "    os._exit(0)\n"
            )

            child = subprocess.run([sys.executable, "-c", script, str(target)])
            self.assertEqual(child.returncode, 0)
            with file_lock(target, timeout=1.0):
                recovered = True

            self.assertTrue(recovered)


if __name__ == "__main__":
    unittest.main()


class CachedWeightsAreNotAPendingDownload(unittest.TestCase):
    """Auto queries must skip a semantic index only when a *download* is pending.

    `active_backend_is_warm` answers "is the model constructed in this process",
    which every cold process answers False -- including one whose weights have
    been on disk for months. Using it as the auto-query gate made a cold CLI
    silently ignore a current semantic index forever, degrading paraphrase
    queries to structural-only retrieval with no network access in prospect.
    Measured on the conceptual fixture, that cost 4x recall (0.200 vs 0.800).
    """

    @staticmethod
    def _plant_model(root: Path, repo: str, *, complete: bool = True) -> None:
        snapshot = root / f"models--{repo}" / "snapshots" / "deadbeef"
        snapshot.mkdir(parents=True)
        (snapshot / "model_optimized.onnx").write_bytes(b"\x00" * 8)
        if complete:
            (snapshot / "tokenizer.json").write_text("{}", encoding="utf-8")
            (snapshot / "config.json").write_text("{}", encoding="utf-8")

    def test_a_partial_download_is_not_a_usable_cache(self) -> None:
        """Weights without a tokenizer let FastEmbed fall through to the network.

        FastEmbed tries `local_files_only=True` and then fetches on failure, so
        a probe that accepts an interrupted download re-opens the very hole this
        predicate exists to close. Found by an independent checker.
        """
        from graphgraph.platform.embeddings import FASTEMBED_CACHE_ENV, local_model_is_cached

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._plant_model(root, "qdrant--bge-small-en-v1.5-onnx-q", complete=False)
            with patch.dict(os.environ, {FASTEMBED_CACHE_ENV: str(root)}):
                self.assertFalse(local_model_is_cached("BAAI/bge-small-en-v1.5"))

    def test_a_zero_byte_weight_file_is_not_a_usable_cache(self) -> None:
        from graphgraph.platform.embeddings import FASTEMBED_CACHE_ENV, local_model_is_cached

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshot = root / "models--qdrant--bge-small-en-v1.5-onnx-q" / "snapshots" / "abc"
            snapshot.mkdir(parents=True)
            (snapshot / "model.onnx").write_bytes(b"")
            (snapshot / "tokenizer.json").write_text("{}", encoding="utf-8")
            (snapshot / "config.json").write_text("{}", encoding="utf-8")
            with patch.dict(os.environ, {FASTEMBED_CACHE_ENV: str(root)}):
                self.assertFalse(local_model_is_cached("BAAI/bge-small-en-v1.5"))

    def test_detects_weights_already_on_disk(self) -> None:
        from graphgraph.platform.embeddings import FASTEMBED_CACHE_ENV, local_model_is_cached

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._plant_model(root, "qdrant--bge-small-en-v1.5-onnx-q")
            with patch.dict(os.environ, {FASTEMBED_CACHE_ENV: str(root)}):
                # FastEmbed serves BAAI/... from the qdrant ONNX mirror, so the
                # match is on the trailing repo component, not the full name.
                self.assertTrue(local_model_is_cached("BAAI/bge-small-en-v1.5"))
                self.assertFalse(local_model_is_cached("acme/never-fetched-model"))

    def test_absent_cache_directory_reports_not_cached(self) -> None:
        from graphgraph.platform.embeddings import FASTEMBED_CACHE_ENV, local_model_is_cached

        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "no-such-cache"
            with patch.dict(os.environ, {FASTEMBED_CACHE_ENV: str(missing)}):
                self.assertFalse(local_model_is_cached("BAAI/bge-small-en-v1.5"))

    def test_a_directory_without_weights_still_needs_a_download(self) -> None:
        """A model dir with metadata but no .onnx is a partial fetch, not a hit."""
        from graphgraph.platform.embeddings import FASTEMBED_CACHE_ENV, local_model_is_cached

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "models--qdrant--bge-small-en-v1.5-onnx-q" / "snapshots" / "abc").mkdir(parents=True)
            with patch.dict(os.environ, {FASTEMBED_CACHE_ENV: str(root)}):
                self.assertFalse(local_model_is_cached("BAAI/bge-small-en-v1.5"))

    def test_cold_backend_with_cached_weights_is_not_a_pending_download(self) -> None:
        from graphgraph.platform import embeddings
        from graphgraph.platform.embeddings import (
            FASTEMBED_CACHE_ENV,
            FastEmbedBackend,
            active_backend_is_warm,
            active_backend_needs_download,
        )

        backend = FastEmbedBackend("BAAI/bge-small-en-v1.5")
        self.assertFalse(backend.is_warm)
        embeddings.set_backend(backend)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                self._plant_model(root, "qdrant--bge-small-en-v1.5-onnx-q")
                with patch.dict(os.environ, {FASTEMBED_CACHE_ENV: str(root)}):
                    # Cold either way, but nothing to fetch -> auto may proceed.
                    self.assertFalse(active_backend_is_warm())
                    self.assertFalse(active_backend_needs_download())
            with tempfile.TemporaryDirectory() as empty:
                with patch.dict(os.environ, {FASTEMBED_CACHE_ENV: empty}):
                    self.assertTrue(active_backend_needs_download())
        finally:
            embeddings.reset_backend_cache()

    def test_non_fastembed_backends_never_report_a_pending_download(self) -> None:
        from graphgraph.platform import embeddings
        from graphgraph.platform.embeddings import active_backend_needs_download

        embeddings.set_backend(None)  # offline hash
        try:
            self.assertFalse(active_backend_needs_download())
        finally:
            embeddings.reset_backend_cache()


class LengthSortedEmbeddingTest(unittest.TestCase):
    """Length-bucketed batching must be a pure throughput change.

    ONNX pads every batch to its longest member, so mixing a 14-char label with
    a 465-char docstring computes both at the longer width. Sorting by length
    before batching removed 2.7x of that waste on 1,200 real nodes while
    producing bit-identical vectors (334/334 exact, max component delta 0.0).

    The risk it introduces is silent: if the caller's order is not restored,
    every vector binds to the wrong node and the index is still perfectly
    well-formed while answering nonsense. These tests exist for that.
    """

    @staticmethod
    def _fingerprint(batch, _size):
        """Stand-in embedder whose output identifies its own input."""
        return [[float(len(text)), float(ord(text[0]))] for text in batch]

    def _expected(self, text):
        return [float(len(text)), float(ord(text[0]))]

    def test_restores_caller_order_across_mixed_lengths(self) -> None:
        from graphgraph.platform.embeddings import embed_length_sorted

        texts = [chr(97 + i % 26) * (1 + (i * 7) % 40) for i in range(200)]
        # Deliberately not already sorted: neighbouring inputs differ in length.
        self.assertNotEqual(texts, sorted(texts, key=len))
        vectors = embed_length_sorted(texts, self._fingerprint, 16)
        self.assertEqual(vectors, [self._expected(text) for text in texts])

    def test_small_input_skips_sorting_entirely(self) -> None:
        from graphgraph.platform.embeddings import embed_length_sorted

        texts = ["bbbb", "a", "ccc"]
        vectors = embed_length_sorted(texts, self._fingerprint, 16)
        self.assertEqual(vectors, [self._expected(text) for text in texts])

    def test_a_short_backend_response_is_an_error_not_silent_truncation(self) -> None:
        from graphgraph.platform.embeddings import embed_length_sorted

        def drops_one(batch, _size):
            return [[float(len(t))] for t in batch][:-1]

        texts = [chr(97 + i % 26) * (1 + i) for i in range(40)]
        with self.assertRaises(ValueError):
            embed_length_sorted(texts, drops_one, 8)

    def test_batch_size_is_environment_tunable(self) -> None:
        from graphgraph.platform.embeddings import EMBED_BATCH_ENV, _embed_batch_size

        with patch.dict(os.environ, {EMBED_BATCH_ENV: "64"}):
            self.assertEqual(_embed_batch_size(), 64)
        with patch.dict(os.environ, {EMBED_BATCH_ENV: "not-a-number"}):
            self.assertGreater(_embed_batch_size(), 0)
        with patch.dict(os.environ, {EMBED_BATCH_ENV: "0"}):
            self.assertGreater(_embed_batch_size(), 0)
