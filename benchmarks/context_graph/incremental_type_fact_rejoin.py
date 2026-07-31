"""Measure affected-key re-join cost after the persistent index is loaded.

Setup/index construction is intentionally outside the timed interval.  This
isolates the Q02-C algorithmic claim from manifest JSON and graph load costs,
which belong to the later persistent-state benchmark batch.
"""

from __future__ import annotations

import argparse
import json
from statistics import median
from time import perf_counter_ns

from graphgraph.scanner.frontends.persistent_facts import (
    PersistentPythonTypeIndex,
    python_file_type_snapshot,
)


def _percentile(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    return ordered[int(quantile * (len(ordered) - 1))]


def _snapshot_corpus(unrelated: int) -> tuple[dict, dict, dict]:
    old_provider = python_file_type_snapshot(
        "def build() -> Old:\n    return Old()\n",
        "provider.py",
    )
    new_provider = python_file_type_snapshot(
        "def build() -> New:\n    return New()\n",
        "provider.py",
    )
    snapshots = {
        "provider.py": old_provider,
        "consumer.py": python_file_type_snapshot(
            "from provider import build\n\n"
            "def use():\n"
            "    value = build()\n"
            "    return value.run()\n",
            "consumer.py",
        ),
    }
    for index in range(unrelated):
        snapshots[f"unrelated_{index}.py"] = {
            "fields": [],
            "globals": [[
                f"unrelated_{index}",
                f"value_{index}",
                {"types": [f"Type{index}"], "evidence": []},
            ]],
            "returns": [],
            "reexports": [[
                f"package_{index}",
                f"unrelated_{index}",
                f"value_{index}",
                f"value_{index}",
            ]],
            "obligations": [],
        }
    return snapshots, old_provider, new_provider


def run(
    sizes: tuple[int, ...],
    affected_sizes: tuple[int, ...],
    repeats: int,
) -> dict:
    rows = []
    for size in sizes:
        samples_ms: list[float] = []
        for _repeat in range(repeats):
            snapshots, old_provider, new_provider = _snapshot_corpus(size)
            index = PersistentPythonTypeIndex.from_snapshots(snapshots)
            started = perf_counter_ns()
            changed = index.update(
                {"provider.py": old_provider},
                {"provider.py": new_provider},
                {"provider.py"},
            )
            affected = index.affected_files(
                changed,
                excluded_files={"provider.py"},
            )
            samples_ms.append((perf_counter_ns() - started) / 1_000_000)
            if affected.files != frozenset({"consumer.py"}):
                raise AssertionError(affected)
        rows.append({
            "unrelated_facts_and_reexports": size,
            "delta_facts": 1,
            "affected_files": 1,
            "median_ms": round(median(samples_ms), 6),
            "p95_ms": round(_percentile(samples_ms, 0.95), 6),
            "max_ms": round(max(samples_ms), 6),
        })
    affected_rows = []
    for affected_count in affected_sizes:
        samples_ms = []
        for _repeat in range(repeats):
            snapshots, old_provider, new_provider = _snapshot_corpus(0)
            snapshots.pop("consumer.py")
            for index in range(affected_count):
                snapshots[f"consumer_{index}.py"] = python_file_type_snapshot(
                    "from provider import build\n\n"
                    f"def use_{index}():\n"
                    "    value = build()\n"
                    "    return value.run()\n",
                    f"consumer_{index}.py",
                )
            index = PersistentPythonTypeIndex.from_snapshots(snapshots)
            started = perf_counter_ns()
            changed = index.update(
                {"provider.py": old_provider},
                {"provider.py": new_provider},
                {"provider.py"},
            )
            affected = index.affected_files(
                changed,
                excluded_files={"provider.py"},
            )
            samples_ms.append((perf_counter_ns() - started) / 1_000_000)
            if len(affected.files) != affected_count:
                raise AssertionError(affected)
        affected_rows.append({
            "delta_facts": 1,
            "affected_files": affected_count,
            "median_ms": round(median(samples_ms), 6),
            "p95_ms": round(_percentile(samples_ms, 0.95), 6),
            "max_ms": round(max(samples_ms), 6),
        })

    return {
        "measurement": "loaded_index_affected_key_rejoin",
        "setup_in_timed_interval": False,
        "sizes": list(sizes),
        "repeats": repeats,
        "rows": rows,
        "affected_scaling_rows": affected_rows,
        "median_growth_ratio": round(
            rows[-1]["median_ms"] / max(rows[0]["median_ms"], 1e-12),
            6,
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sizes", default="0,1000,10000")
    parser.add_argument("--affected-sizes", default="1,100,1000")
    parser.add_argument("--repeats", type=int, default=25)
    args = parser.parse_args()
    sizes = tuple(int(value) for value in args.sizes.split(","))
    affected_sizes = tuple(int(value) for value in args.affected_sizes.split(","))
    print(json.dumps(run(sizes, affected_sizes, max(1, args.repeats)), indent=2))


if __name__ == "__main__":
    main()
