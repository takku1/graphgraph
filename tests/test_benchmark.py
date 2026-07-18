# Benchmark test for graphgraph extraction and token estimation
"""Run the benchmark utilities on a sample codebase and assert reasonable performance.

This test exercises the new AST‑based Python extractor and measures:
* Extraction time (seconds)
* Number of symbol nodes and edges created
* Approximate token size of the resulting graph packet
"""

import json
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from graphgraph.benchmark.bench_utils import estimate_token_size
from graphgraph.core import Edge, Graph, Node
from graphgraph.scanner.ast import extract_symbols


class BenchmarkExtractionTest(unittest.TestCase):
    def test_negative_query_benchmark_uses_real_isolation_state(self):
        from benchmarks.context_graph.real_project_answerability_limit import make_tasks

        connected = Graph(
            nodes={"A": Node("A", "A"), "B": Node("B", "B")},
            edges=[Edge("A", "B", "calls")],
        )
        connected_task = next(task for task in make_tasks(connected) if task.query_class == "negative_query")
        self.assertFalse(connected_task.negative)
        self.assertEqual(connected_task.expected_edges, frozenset({("A", "B", "calls")}))

        with_isolated = Graph(
            nodes={"A": Node("A", "A"), "B": Node("B", "B"), "C": Node("C", "C")},
            edges=[Edge("A", "B", "calls")],
        )
        isolated_task = next(task for task in make_tasks(with_isolated) if task.query_class == "negative_query")
        self.assertTrue(isolated_task.negative)
        self.assertEqual(isolated_task.starts, ("C",))
        self.assertFalse(isolated_task.expected_edges)

    def test_production_evidence_requirements_follow_query_semantics(self):
        from benchmarks.context_graph.production_retrieval_benchmark import production_evidence_requirements
        from benchmarks.context_graph.real_project_answerability_limit import Task

        graph = Graph(
            nodes={name: Node(name, name) for name in ("TARGET", "CALLER", "TEST", "IMPL", "DOC")},
            edges=[
                Edge("CALLER", "TARGET", "calls"),
                Edge("TEST", "TARGET", "tests"),
                Edge("TARGET", "IMPL", "calls"),
                Edge("DOC", "TARGET", "mentions"),
            ],
        )
        task = Task("blast_radius", ("TARGET",), frozenset(), frozenset())

        groups = production_evidence_requirements(graph, task)

        self.assertEqual(
            groups,
            (
                frozenset({("CALLER", "TARGET", "calls"), ("TEST", "TARGET", "tests")}),
                frozenset({("TEST", "TARGET", "tests")}),
                frozenset({("TARGET", "IMPL", "calls")}),
            ),
        )

    def test_extraction_and_token_estimation(self):
        # Scan the source directory for code files
        src_dir = Path(__file__).parents[1] / "src"
        files = []
        for path in src_dir.rglob("*.*"):
            if path.suffix.lower() not in {
                ".py",
                ".rs",
                ".ts",
                ".tsx",
                ".js",
                ".jsx",
                ".go",
                ".java",
                ".cs",
                ".c",
                ".cpp",
                ".cxx",
                ".cc",
                ".h",
                ".hpp",
            }:
                continue
            rel = path.relative_to(src_dir).as_posix()
            file_node_id = f"file_{rel}"  # deterministic id
            text = path.read_text(encoding="utf-8", errors="ignore")
            files.append((path, rel, file_node_id, text))

        # Run symbol extraction benchmark
        start = time.perf_counter()
        symbol_nodes, symbol_edges, _truncated = extract_symbols(files, max_total_symbols=5000)
        elapsed = time.perf_counter() - start

        # Basic sanity checks
        self.assertGreater(len(symbol_nodes), 0, "No symbols extracted")
        self.assertGreater(len(symbol_edges), 0, "No edges extracted")
        self.assertLess(elapsed, 10.0, f"Extraction took too long: {elapsed:.2f}s")

        # Build a temporary graph and estimate token size
        g = Graph(nodes=symbol_nodes, edges=symbol_edges)

        token_est = estimate_token_size(g)
        # Soft sanity ceiling on the full source-graph size (naive JSON word
        # count), not a packet budget. Bumped as the codebase grows; raise it
        # again if a legitimate expansion trips it rather than treating it as a
        # regression.
        self.assertLess(token_est, 93000, f"Token estimate too high: {token_est}")

        print(
            f"Extraction time: {elapsed:.2f}s, symbols: {len(symbol_nodes)}, edges: {len(symbol_edges)}, token_estimate: {token_est}"
        )

    def test_model_reasoning_prompt_records_do_not_embed_answer_keys(self):
        from benchmarks.context_graph import model_reasoning_benchmark as benchmark

        if not benchmark.PACKETS.exists():
            self.skipTest("interpretability packets are not generated")

        records = benchmark.iter_prompt_records()
        self.assertGreater(len(records), 0)
        for record in records:
            self.assertNotIn("expected_nodes", record)
            self.assertNotIn("expected_edges", record)
            serialized = json.dumps(record, ensure_ascii=False)
            self.assertNotIn('"expected_nodes"', serialized)
            self.assertNotIn('"expected_edges"', serialized)

    def test_configure_codex_plugin_rewrites_mcp_paths_for_checkout(self):
        from scripts.configure_codex_plugin import configure

        repo_root = Path(__file__).parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            temp_root = Path(tmp) / "graphgraph-copy"
            plugin_root = temp_root / "plugins" / "graphgraph"
            plugin_root.mkdir(parents=True)
            shutil.copytree(repo_root / "plugins" / "graphgraph", plugin_root, dirs_exist_ok=True)

            result = configure(temp_root)
            mcp = json.loads((plugin_root / ".mcp.json").read_text(encoding="utf-8"))
            server = mcp["mcpServers"]["graphgraph"]

            self.assertEqual(server["cwd"], temp_root.resolve().as_posix())
            self.assertIn("--project", server["args"])
            project_index = server["args"].index("--project") + 1
            self.assertEqual(server["args"][project_index], temp_root.resolve().as_posix())
            self.assertEqual(server["args"][-1], "graphgraph-mcp")
            self.assertEqual(result["cwd"], temp_root.resolve().as_posix())


if __name__ == "__main__":
    unittest.main()
