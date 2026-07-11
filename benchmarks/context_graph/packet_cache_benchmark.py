from __future__ import annotations

import json
import statistics
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from graphgraph.io import find_graph_path  # noqa: E402
from graphgraph.runtime.cache import TopologicalKVCache  # noqa: E402
from graphgraph.services.context import _GRAPH_CACHE, render_query_context  # noqa: E402

OUT = ROOT / "benchmarks" / "context_graph" / "out" / "live"
REPORT_JSON = OUT / "packet_cache.json"
REPORT_MD = OUT / "packet_cache.md"


def elapsed_ms(call) -> float:
    start = time.perf_counter()
    call()
    return (time.perf_counter() - start) * 1_000


def main() -> None:
    graph_path = find_graph_path()
    OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        cache = TopologicalKVCache(Path(tmp) / "cache.json")
        namespace = "packet_cache_benchmark"

        def query() -> str:
            return render_query_context(
                query="who calls render_packet",
                query_class="reverse_lookup",
                graph_path=graph_path,
                cache_namespace=namespace,
            )

        _GRAPH_CACHE.clear()
        with patch("graphgraph.services.context.TopologicalKVCache", return_value=cache):
            cold_ms = elapsed_ms(query)
            cache.clear()
            warm_graph_ms = elapsed_ms(query)
            hit_samples = [elapsed_ms(query) for _ in range(25)]

    report = {
        "graph": str(graph_path),
        "cold_query_ms": round(cold_ms, 3),
        "warm_graph_query_ms": round(warm_graph_ms, 3),
        "packet_cache_hit_median_ms": round(statistics.median(hit_samples), 3),
        "packet_cache_hit_min_ms": round(min(hit_samples), 3),
        "packet_cache_hit_max_ms": round(max(hit_samples), 3),
        "hit_rounds": len(hit_samples),
    }
    REPORT_JSON.write_text(json.dumps(report, indent=2), encoding="utf-8")
    REPORT_MD.write_text(render_markdown(report), encoding="utf-8")
    print(REPORT_MD.read_text(encoding="utf-8"))


def render_markdown(report: dict[str, object]) -> str:
    return "\n".join(
        [
            "# Packet Cache Hot Path",
            "",
            f"- Graph: `{report['graph']}`",
            f"- Cold query: `{report['cold_query_ms']}ms`",
            f"- Warm graph, empty packet cache: `{report['warm_graph_query_ms']}ms`",
            f"- Packet-cache hit median: `{report['packet_cache_hit_median_ms']}ms`",
            f"- Packet-cache hit range: `{report['packet_cache_hit_min_ms']}ms` to `{report['packet_cache_hit_max_ms']}ms`",
            f"- Hit rounds: `{report['hit_rounds']}`",
            "",
            "The temporary packet cache isolates this measurement from project cache state.",
            "Warm-graph timing still performs retrieval; a packet-cache hit bypasses graph load,",
            "retrieval, expansion, packet rendering, and validation.",
        ]
    ) + "\n"


if __name__ == "__main__":
    main()
