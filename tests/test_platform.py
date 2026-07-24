from __future__ import annotations

import json
import os
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
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
    CpgEvidenceProvider,
    Episode,
    EvaluationCase,
    EvidenceBatch,
    EvidenceStore,
    GraphProgram,
    GraphRuntime,
    MemoryStore,
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
from graphgraph.platform.service import create_server, install_git_hooks
from graphgraph.runtime.state import atomic_write_text, file_lock
from graphgraph.services import render_query_context


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
            self.assertTrue({"js", "ts", "go", "rs", "java"} <= languages)
            self.assertEqual(receipts[0].provider, "cpg")
            self.assertEqual(receipts[0].paths_processed, 5)
            self.assertTrue(all(edge.evidence and edge.source_location for edge in enriched.edges))

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

            payload = json.loads(render_query_context(
                query="runtime database rollback payments",
                graph_path=graph_path,
                show_anchors=True,
                json_anchors=True,
                source_mode="all",
            ))
            self.assertEqual(
                set(payload["retrieval"]["sources"]["sources"]),
                {"semantic", "memory", "temporal", "federation", "runtime_trace"},
            )
            self.assertTrue(payload["packet"].startswith("#gg"))

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

    def test_runtime_compiles_passes_to_valid_packet(self) -> None:
        result = GraphRuntime(platform_graph(), (StructuralEvidenceProvider(),)).compile(GraphProgram(
            "where does run call database query", passes=("evidence", "inference", "hierarchy"), max_nodes=20
        ))
        self.assertTrue(result.receipt.valid)
        self.assertEqual(result.receipt.passes, ("evidence", "inference", "hierarchy"))
        self.assertTrue(result.packet.startswith("#gg"))
        self.assertTrue(result.receipt.provider_receipts)

    def test_runtime_preserves_document_scope_during_compiler_routing(self) -> None:
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

        result = GraphRuntime(graph).compile(GraphProgram(
            "Identify one capability currently marked absent.",
            scopes=(path,),
        ))

        self.assertEqual(result.route.query_class, "doc_summary")
        self.assertIn("explicit document scope", result.route.reasons)
        self.assertEqual(result.retrieval.starts, ("ABSENT",))

    def test_runtime_exact_paths_bypass_auxiliary_source_planning(self) -> None:
        class UnexpectedSourcePlanner:
            def plan(self, *_args: object, **_kwargs: object) -> object:
                raise AssertionError("exact paths must bypass global source planning")

        graph = Graph(nodes={
            "PLAN": Node("PLAN", "plan_writes", "method", "src/planner.rs"),
        })
        result = GraphRuntime(
            graph,
            source_planner=UnexpectedSourcePlanner(),  # type: ignore[arg-type]
        ).compile(GraphProgram(
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
        graph = platform_graph()
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
            hooks = root / ".git" / "hooks"
            hooks.mkdir(parents=True)
            post_commit = hooks / "post-commit"
            post_commit.write_text("#!/bin/sh\necho existing\n", encoding="utf-8")
            install_git_hooks(root, executable="gg")
            install_git_hooks(root, executable="graphgraph")
            content = post_commit.read_text(encoding="utf-8")
            self.assertIn("echo existing", content)
            self.assertEqual(content.count("# >>> graphgraph managed >>>"), 1)
            self.assertIn("graphgraph context", content)


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
        from graphgraph.platform import SemanticIndex, reset_backend_cache

        reset_backend_cache()
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
        from graphgraph.platform import SemanticIndex, reset_backend_cache

        graph = Graph(
            nodes={
                "A": Node("A", "delete_user_account", "function", "accounts.py",
                          summary="removes a user and purges their records"),
                "B": Node("B", "render_dashboard", "function", "ui.py",
                          summary="draws the main dashboard"),
            },
            edges=[],
        )

        # Offline: the token-disjoint paraphrase does not resolve.
        reset_backend_cache()
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
        # Windows leaves an unlinked-but-still-open lock file in "delete
        # pending", where os.open raises PermissionError rather than
        # FileExistsError. That is contention and must be waited out.
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
            self.assertFalse(target.with_name("state.json.lock").exists())

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


if __name__ == "__main__":
    unittest.main()
