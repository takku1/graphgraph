# Benchmark test for GraphGraph extraction and serialization density.
"""Run extraction-density measurements on a sample codebase.

This test exercises the new AST‑based Python extractor and measures:
* Extraction time (seconds)
* Number of symbol nodes and edges created
* Whitespace density of a deterministic graph serialization
"""

import json
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised on Python 3.10.
    import tomli as tomllib

ROOT = Path(__file__).parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from graphgraph.benchmark.extraction_density import graph_serialization_words
from graphgraph.graph.core import Edge, Graph, Node
from graphgraph.scanner.ast import extract_symbols

NON_ENGINE_SOURCE_PREFIXES = (
    "graphgraph/acceptance/",
    "graphgraph/research/",
)
NON_ENGINE_SOURCE_FILES = frozenset(
    {
        "graphgraph/analysis/eval_protocol.py",
        "graphgraph/live_validation.py",
    }
)
# This guard measures representation density instead of freezing the total size
# of a growing repository. The 2026-08-02 baseline was 1.0189 naive graph tokens
# per whitespace-delimited source word; 1.05 is the explicit density SLO. Adding
# ordinary source now grows both sides of the equation, while an extractor that
# starts duplicating records or payload fields still trips the guard.
SOURCE_GRAPH_TOKEN_DENSITY_LIMIT = 1.05
# Extraction throughput ceiling, normalized by input size for the same reason
# as the density limit above: a flat repository-total budget says nothing about
# extraction speed and fails purely because src/ grew.
#
# This is a change of denominator, not a re-baseline. The former flat 10.0s
# budget was written against a 1.8437 MiB engine tree, i.e. exactly 5.42 s/MiB,
# so an extractor that slows down trips this at the same throughput it always
# did.
#
# 2026-08-06 baseline, idle machine, 3 runs: 2.13-2.34 s/MiB (median 2.25),
# i.e. ~2.4x headroom. NOTE: this is wall-clock and therefore load-sensitive --
# the same tree measured 3.7-6.6 s/MiB while a second agent was running heavy
# work on this host. Re-run idle before treating a failure as a regression.
SOURCE_EXTRACTION_SECONDS_PER_MIB_LIMIT = 5.42


class BenchmarkExtractionTest(unittest.TestCase):
    def test_serialization_density_ignores_memoized_dataclass_attributes(self) -> None:
        node = Node("n", "node", "function", "src/node.py", scope="src")
        edge = Edge("n", "n", "references")
        graph = Graph({node.id: node}, [edge])
        before = graph_serialization_words(graph)

        node.normalized_scope_values
        edge.traversal_val

        self.assertEqual(graph_serialization_words(graph), before)

    def test_runtime_pins_the_offline_ready_tree_sitter_language_pack(self):
        data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertIn(
            "tree-sitter-language-pack==1.10.9",
            data["project"]["dependencies"],
        )

    def test_packet_cache_benchmark_uses_public_graph_cache_reset(self):
        from benchmarks.context_graph import packet_cache_benchmark
        from graphgraph.io import clear_graph_cache

        self.assertIs(packet_cache_benchmark.clear_graph_cache, clear_graph_cache)

    def test_real_project_packet_balance_skips_cleanly_without_a_corpus(self):
        from contextlib import redirect_stdout
        from io import StringIO
        from unittest.mock import patch

        from benchmarks.context_graph import real_project_packet_balance

        output = StringIO()
        with (
            patch.object(
                real_project_packet_balance,
                "project_paths",
                return_value=[Path("definitely-missing-corpus")],
            ),
            patch.object(real_project_packet_balance, "run") as run,
            redirect_stdout(output),
        ):
            real_project_packet_balance.main()

        run.assert_not_called()
        self.assertIn("SKIP", output.getvalue())

    def test_benchmark_runner_reports_prerequisite_skips_and_continues(self):
        from contextlib import redirect_stdout
        from io import StringIO
        from unittest.mock import patch

        from benchmarks.context_graph import run_all

        output = StringIO()
        with (
            patch.object(run_all, "SCRIPTS", ["real_project_packet_balance.py", "ready.py"]),
            patch.object(run_all, "project_paths", return_value=[]),
            patch.object(run_all.subprocess, "run") as run,
            redirect_stdout(output),
        ):
            run_all.main()

        run.assert_called_once()
        self.assertIn("1 ran, 1 skipped", output.getvalue())
        self.assertIn("SKIP real_project_packet_balance.py", output.getvalue())

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
            if rel.startswith(NON_ENGINE_SOURCE_PREFIXES) or rel in NON_ENGINE_SOURCE_FILES:
                continue  # release/eval harnesses are not the engine this ceiling guards
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
        # Normalized for the same reason as the token ceiling below: a fixed
        # repository-total wall-clock budget says nothing about extraction
        # speed and fails purely because src/ grew. The rate is set to exactly
        # the strictness the 10s/1.8437 MiB ceiling encoded when it was
        # written, so this is a change of denominator, not a re-baseline -- an
        # extractor that slows down still trips it at the same throughput.
        source_mib = sum(len(text) for _path, _rel, _id, text in files) / (1024 * 1024)
        seconds_per_mib = elapsed / source_mib
        self.assertLess(
            seconds_per_mib,
            SOURCE_EXTRACTION_SECONDS_PER_MIB_LIMIT,
            f"Extraction too slow: {seconds_per_mib:.2f}s/MiB over {source_mib:.2f} MiB "
            f"({elapsed:.2f}s total)",
        )

        # Build a temporary graph and measure serialization density. This is a
        # word-unit SLO, deliberately separate from calibrated packet tokens.
        g = Graph(nodes=symbol_nodes, edges=symbol_edges)

        graph_words = graph_serialization_words(g)
        # Normalize by the actual input size: a fixed repository-total ceiling
        # naturally fails whenever useful source is added and says nothing
        # about extraction efficiency.
        source_word_proxy = sum(len(text.split()) for _path, _rel, _id, text in files)
        word_ceiling = int(source_word_proxy * SOURCE_GRAPH_TOKEN_DENSITY_LIMIT)
        self.assertLess(
            graph_words,
            word_ceiling,
            f"Graph/source serialization density too high: {graph_words / source_word_proxy:.4f}",
        )

        # Extraction-quality floor (path-to-10 "adopt first" gate).
        # calls_per_symbol -- resolved call edges per callable symbol -- is the
        # single number that separates a healthy extractor from a broken one: JS
        # regressed to 0.10 while Python holds ~1.8. This self-graph is Python, so
        # the gate guards the Python extractor here; per-language enforcement
        # across js/rust needs the multi-language fixture repos.
        callable_symbols = sum(
            1 for node in symbol_nodes.values() if node.kind in {"function", "method", "class"}
        )
        call_edges = sum(1 for edge in symbol_edges if edge.type == "calls")
        calls_per_symbol = call_edges / max(1, callable_symbols)
        self.assertGreaterEqual(
            calls_per_symbol,
            0.5,
            f"Python calls_per_symbol {calls_per_symbol:.2f} below 0.5 floor -- "
            "member-call resolution regressed",
        )

        print(
            f"Extraction time: {elapsed:.2f}s, symbols: {len(symbol_nodes)}, "
            f"edges: {len(symbol_edges)}, graph_serialization_words: {graph_words}, "
            f"calls_per_symbol: {calls_per_symbol:.2f}"
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
            self.assertIn("--no-sync", server["args"])
            project_index = server["args"].index("--project") + 1
            self.assertEqual(server["args"][project_index], temp_root.resolve().as_posix())
            self.assertEqual(server["args"][-1], "graphgraph-mcp")
            self.assertEqual(result["cwd"], temp_root.resolve().as_posix())


if __name__ == "__main__":
    unittest.main()
