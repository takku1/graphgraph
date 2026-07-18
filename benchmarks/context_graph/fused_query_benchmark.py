"""Compare separate update/remove/query calls with fused MCP query_context.

The setup cost is excluded. Each timed path starts from an equivalent saved
graph and applies one changed file plus one deleted file before retrieving the
new symbol.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import tempfile
from contextlib import contextmanager
from pathlib import Path
from time import perf_counter

from graphgraph.io import load_any, save_validated_graph
from graphgraph.mcp.server import build_query_context
from graphgraph.scanner import scan_directory
from graphgraph.services import render_query_context
from graphgraph.services.native import remove_paths_validated_graph, update_paths_validated_graph


@contextmanager
def _working_directory(path: Path):
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


def _prepare(root: Path, file_count: int) -> Path:
    for index in range(file_count):
        (root / f"module_{index}.py").write_text(
            f"def worker_{index}():\n    return {index}\n",
            encoding="utf-8",
        )
    graph_path = root / ".graphgraph" / "graph.gg"
    graph = scan_directory(
        root,
        depth="symbols",
        frontend="regex",
        previous_graph_path=None,
        manifest_path=graph_path.parent / "manifest.json",
    )
    save_validated_graph(graph, graph_path)
    (root / "module_0.py").write_text("def fused_target():\n    return 1\n", encoding="utf-8")
    (root / "module_1.py").unlink()
    return graph_path


def _assert_result(graph_path: Path, packet: str) -> None:
    if "fused_target" not in packet:
        raise AssertionError("refreshed query did not return fused_target")
    graph = load_any(graph_path)
    if any(node.path == "module_1.py" for node in graph.nodes.values()):
        raise AssertionError("deleted path survived graph refresh")


def _run_separate(root: Path, graph_path: Path) -> float:
    with _working_directory(root):
        start = perf_counter()
        update_paths_validated_graph(
            directory=root,
            output_path=graph_path,
            paths=["module_0.py"],
            frontend="regex",
        )
        remove_paths_validated_graph(
            directory=root,
            output_path=graph_path,
            paths=["module_1.py"],
            frontend="regex",
        )
        packet = render_query_context(
            query="fused_target",
            query_class="direct_lookup",
            graph_path=graph_path,
            cache_namespace="separate_benchmark",
        )
        elapsed = perf_counter() - start
    _assert_result(graph_path, packet)
    return elapsed


def _run_fused(root: Path, graph_path: Path) -> float:
    with _working_directory(root):
        start = perf_counter()
        packet = build_query_context(
            {
                "query": "fused_target",
                "query_class": "direct_lookup",
                "directory": str(root),
                "graph_path": str(graph_path),
                "changed_paths": ["module_0.py"],
                "deleted_paths": ["module_1.py"],
                "frontend": "regex",
            }
        )
        elapsed = perf_counter() - start
    _assert_result(graph_path, packet)
    return elapsed


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--files", type=int, default=500)
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()

    separate_times: list[float] = []
    fused_times: list[float] = []
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        for repeat in range(args.repeats):
            separate_root = base / f"separate_{repeat}"
            fused_root = base / f"fused_{repeat}"
            separate_root.mkdir()
            fused_root.mkdir()
            separate_times.append(_run_separate(separate_root, _prepare(separate_root, args.files)))
            fused_times.append(_run_fused(fused_root, _prepare(fused_root, args.files)))

    separate_median = statistics.median(separate_times)
    fused_median = statistics.median(fused_times)
    print(
        json.dumps(
            {
                "files": args.files,
                "repeats": args.repeats,
                "separate_seconds": separate_times,
                "fused_seconds": fused_times,
                "separate_median_seconds": separate_median,
                "fused_median_seconds": fused_median,
                "speedup": separate_median / fused_median,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
