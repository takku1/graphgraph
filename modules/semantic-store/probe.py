"""Recurspec measurement probe for the OW-AC-03 semantic-store contract."""

from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

QUERY = (
    "How does the query planner decide whether auxiliary meaning-based evidence "
    "should participate when ordinary word matching appears confident?"
)
COLD_RUNS = 10
WARM_RUNS = 30
COLD_P95_LIMIT_MS = 3_000.0
WARM_P95_LIMIT_MS = 1_500.0
CODE_KINDS = frozenset(
    {"function", "method", "class", "struct", "trait", "enum", "interface", "type"}
)


def _p95(values: list[float]) -> float:
    if not values:
        raise ValueError("p95 requires at least one reading")
    ordered = sorted(values)
    return ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)]


def _compile_once(*, resident_status=None) -> dict[str, Any]:
    from graphgraph.services.compiler_driver import CompilerDriver, DriverRequest

    graph_path = Path(".graphgraph/graph.gg").resolve()
    started = time.perf_counter()
    rendered, _status = CompilerDriver().compile(
        DriverRequest(
            query=QUERY,
            graph_path=graph_path,
            resident_status=resident_status,
            json_output=True,
            json_details=True,
            cache_namespace=f"recurspec-semantic-store-{uuid.uuid4().hex}",
        )
    )
    wall_ms = (time.perf_counter() - started) * 1000.0
    payload = json.loads(rendered)
    sources = payload.get("retrieval", {}).get("sources", {})
    semantic_count = int(sources.get("semantic_seeds", 0) or 0)
    seed_ids = list(sources.get("seed_ids", ()))[:semantic_count]
    return {
        "wall_ms": wall_ms,
        "query_ms": float(payload.get("workflow", {}).get("query_milliseconds", wall_ms)),
        "semantic_state": str(sources.get("semantic_index_state", "unknown")),
        "semantic_count": semantic_count,
        "seed_ids": seed_ids,
        "load_ms": float(sources.get("semantic_load_milliseconds", 0.0) or 0.0),
        "embed_ms": float(sources.get("semantic_embed_milliseconds", 0.0) or 0.0),
        "score_ms": float(sources.get("semantic_score_milliseconds", 0.0) or 0.0),
        "packet_valid": payload.get("workflow", {}).get("packet_validation", {}).get("ok"),
    }


def _single() -> int:
    print(json.dumps(_compile_once(), separators=(",", ":")))
    return 0


def _cold_observations() -> list[dict[str, Any]]:
    script = Path(__file__).resolve()
    env = dict(os.environ)
    root = Path.cwd().resolve()
    env["PYTHONPATH"] = os.pathsep.join(
        value for value in (str(root / "src"), env.get("PYTHONPATH", "")) if value
    )
    observations: list[dict[str, Any]] = []
    for _index in range(COLD_RUNS):
        result = subprocess.run(
            [sys.executable, str(script), "--single"],
            cwd=root,
            env=env,
            capture_output=True,
            text=True,
            timeout=90,
        )
        if result.returncode != 0:
            raise RuntimeError(
                "cold semantic query failed: " + (result.stderr or result.stdout).strip()
            )
        observations.append(json.loads(result.stdout))
    return observations


def _warm_observations() -> list[dict[str, Any]]:
    from graphgraph.io import load_any
    from graphgraph.services.lifecycle import GraphBuildStatus

    graph_path = Path(".graphgraph/graph.gg").resolve()
    graph = load_any(graph_path)
    resident = GraphBuildStatus(graph_path, graph, built=True)
    _compile_once(resident_status=resident)  # backend/model warm-up, excluded
    return [_compile_once(resident_status=resident) for _index in range(WARM_RUNS)]


def _seed_composition(observation: dict[str, Any], graph) -> tuple[int, int]:
    kinds = [
        graph.nodes[node_id].kind
        for node_id in observation["seed_ids"]
        if node_id in graph.nodes
    ]
    code = sum(kind in CODE_KINDS for kind in kinds)
    return code, len(kinds) - code


def _artifact_bytes() -> int:
    manifest_path = Path(".graphgraph/semantic.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    paths = [manifest_path]
    vectors_file = manifest.get("vectors_file")
    if vectors_file:
        paths.append(manifest_path.parent / str(vectors_file))
    return sum(path.stat().st_size for path in paths)


def _metric(
    name: str,
    value: float | int,
    unit: str,
    direction: str,
    tier: str,
) -> dict[str, Any]:
    return {
        "metric": name,
        "value": value,
        "unit": unit,
        "direction": direction,
        "tier": tier,
        "evidence_stage": "Measured",
    }


def _measure(module: str) -> int:
    from graphgraph.io import load_any

    cold = _cold_observations()
    warm = _warm_observations()
    graph = load_any(Path(".graphgraph/graph.gg"))
    observations = [*cold, *warm]
    invalid = [item for item in observations if item["semantic_state"] != "current"]
    invalid_packets = [item for item in observations if item["packet_valid"] is not True]
    compositions = [_seed_composition(item, graph) for item in observations]

    cold_p95 = _p95([item["wall_ms"] for item in cold])
    warm_p95 = _p95([item["wall_ms"] for item in warm])
    min_code = min((code for code, _prose in compositions), default=0)
    min_prose = min((prose for _code, prose in compositions), default=0)
    failures: list[str] = []
    if invalid:
        failures.append(f"{len(invalid)} queries did not consume a current semantic store")
    if invalid_packets:
        failures.append(f"{len(invalid_packets)} packets failed validation")
    if cold_p95 > COLD_P95_LIMIT_MS:
        failures.append(f"cold p95 {cold_p95:.1f} ms > {COLD_P95_LIMIT_MS:.1f} ms")
    if warm_p95 > WARM_P95_LIMIT_MS:
        failures.append(f"warm p95 {warm_p95:.1f} ms > {WARM_P95_LIMIT_MS:.1f} ms")
    if min_code < 1 or min_prose < 1:
        failures.append(
            f"semantic seed balance missing (minimum code={min_code}, prose={min_prose})"
        )
    if failures:
        for failure in failures:
            print(f"[HARD GATE] {failure}", file=sys.stderr)
        return 1

    metrics = [
        _metric("cold_query_p95_ms", round(cold_p95, 3), "ms", "lower", "hard_gate"),
        _metric("warm_query_p95_ms", round(warm_p95, 3), "ms", "lower", "hard_gate"),
        _metric("semantic_code_seed_min", min_code, "seeds", "higher", "hard_gate"),
        _metric("semantic_prose_seed_min", min_prose, "seeds", "higher", "hard_gate"),
        _metric(
            "semantic_load_p95_ms",
            round(_p95([item["load_ms"] for item in observations]), 3),
            "ms",
            "lower",
            "observation",
        ),
        _metric(
            "semantic_embed_p95_ms",
            round(_p95([item["embed_ms"] for item in observations]), 3),
            "ms",
            "lower",
            "observation",
        ),
        _metric(
            "semantic_score_p95_ms",
            round(_p95([item["score_ms"] for item in observations]), 3),
            "ms",
            "lower",
            "observation",
        ),
        _metric("semantic_store_bytes", _artifact_bytes(), "bytes", "lower", "observation"),
    ]
    print(
        json.dumps(
            {
                "event_type": "measurement",
                "module": module,
                "status": "success",
                "evidence_stage": "Measured",
                "metrics": metrics,
            },
            separators=(",", ":"),
        )
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--module", default="semantic-store")
    parser.add_argument("--single", action="store_true")
    args = parser.parse_args()
    return _single() if args.single else _measure(args.module)


if __name__ == "__main__":
    raise SystemExit(main())
