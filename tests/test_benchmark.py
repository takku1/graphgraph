# Benchmark test for graphgraph extraction and token estimation
"""Run the benchmark utilities on a sample codebase and assert reasonable performance.

This test exercises the new AST‑based Python extractor and measures:
* Extraction time (seconds)
* Number of symbol nodes and edges created
* Approximate token size of the resulting graph packet
"""

import unittest
import json
import shutil
import tempfile
from pathlib import Path
import time

from graphgraph.scanner.ast import extract_symbols
from graphgraph.core import Graph
from graphgraph.benchmark.bench_utils import estimate_token_size

class BenchmarkExtractionTest(unittest.TestCase):
    def test_extraction_and_token_estimation(self):
        # Scan the source directory for code files
        src_dir = Path(__file__).parents[1] / "src"
        files = []
        for path in src_dir.rglob("*.*"):
            if path.suffix.lower() not in {".py", ".rs", ".ts", ".tsx", ".js", ".jsx", ".go", ".java", ".cs", ".c", ".cpp", ".cxx", ".cc", ".h", ".hpp"}:
                continue
            rel = path.relative_to(src_dir).as_posix()
            file_node_id = f"file_{rel}"  # deterministic id
            text = path.read_text(encoding="utf-8", errors="ignore")
            files.append((path, rel, file_node_id, text))

        # Run symbol extraction benchmark
        start = time.perf_counter()
        symbol_nodes, symbol_edges = extract_symbols(files, max_total_symbols=5000)
        elapsed = time.perf_counter() - start

        # Basic sanity checks
        self.assertGreater(len(symbol_nodes), 0, "No symbols extracted")
        self.assertGreater(len(symbol_edges), 0, "No edges extracted")
        self.assertLess(elapsed, 10.0, f"Extraction took too long: {elapsed:.2f}s")

        # Build a temporary graph and estimate token size
        g = Graph(nodes=symbol_nodes, edges=symbol_edges)

        token_est = estimate_token_size(g)
        self.assertLess(token_est, 50000, f"Token estimate too high: {token_est}")

        print(f"Extraction time: {elapsed:.2f}s, symbols: {len(symbol_nodes)}, edges: {len(symbol_edges)}, token_estimate: {token_est}")

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
