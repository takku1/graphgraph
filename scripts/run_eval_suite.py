"""Run a frozen multi-repository evaluation suite against pinned checkouts."""

from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from graphgraph.analysis.eval import evaluate_graph
from graphgraph.analysis.eval_protocol import (
    deterministic_result_signature,
    load_eval_manifest,
    stratified_report,
)


def _mapping(values: list[str], *, option: str) -> dict[str, Path]:
    mapped: dict[str, Path] = {}
    for value in values:
        key, separator, raw_path = value.partition("=")
        if not separator or not key or not raw_path:
            raise SystemExit(f"{option} expects PROJECT=PATH, got {value!r}")
        if key in mapped:
            raise SystemExit(f"{option} repeats project {key!r}")
        mapped[key] = Path(raw_path).resolve()
    return mapped


def _git_commit(root: Path) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=Path("eval/retrieval-v1/manifest.json"))
    parser.add_argument("--graph", action="append", default=[], metavar="PROJECT=PATH", required=True)
    parser.add_argument("--project-root", action="append", default=[], metavar="PROJECT=PATH", required=True)
    parser.add_argument("--source-mode", choices=("auto", "off", "all"), default="auto")
    parser.add_argument("--max-nodes", type=int)
    parser.add_argument("--calibration-bins", type=int, default=10)
    parser.add_argument("--abstain-threshold", type=float, default=0.5)
    parser.add_argument("--repeat", type=int, default=1, help="Repeat each project and reject non-latency drift.")
    args = parser.parse_args(argv)
    if args.repeat < 1:
        parser.error("--repeat must be >= 1")

    suite = load_eval_manifest(args.manifest)
    graphs = _mapping(args.graph, option="--graph")
    roots = _mapping(args.project_root, option="--project-root")
    expected_ids = {project.project_id for project in suite.projects}
    for label, mapping in (("--graph", graphs), ("--project-root", roots)):
        if set(mapping) != expected_ids:
            missing = sorted(expected_ids - set(mapping))
            extra = sorted(set(mapping) - expected_ids)
            raise SystemExit(f"{label} project mismatch: missing={missing}, extra={extra}")

    results = []
    projects: list[dict[str, object]] = []
    for project in suite.projects:
        graph_path = graphs[project.project_id]
        root = roots[project.project_id]
        if not graph_path.is_file():
            raise SystemExit(f"missing graph for {project.project_id}: {graph_path}")
        observed_commit = _git_commit(root)
        if observed_commit != project.commit:
            raise SystemExit(
                f"{project.project_id} checkout mismatch: expected {project.commit}, observed {observed_commit}"
            )
        project_results = []
        reference_signature = ""
        for repeat_index in range(args.repeat):
            measured = evaluate_graph(
                graph_path,
                list(project.tasks),
                max_nodes=args.max_nodes,
                source_mode=args.source_mode,
            )
            signature = deterministic_result_signature(measured)
            if repeat_index == 0:
                project_results = measured
                reference_signature = signature
            elif signature != reference_signature:
                raise SystemExit(
                    f"{project.project_id} non-latency evaluation results changed on repeat {repeat_index + 1}"
                )
        results.extend(project_results)
        projects.append(
            {
                "id": project.project_id,
                "repository": project.repository,
                "commit": observed_commit,
                "split": project.split,
                "language": project.language,
                "graph": str(graph_path),
                "task_count": len(project.tasks),
            }
        )

    payload = {
        "suite_id": suite.suite_id,
        "measured_at": datetime.now(timezone.utc).isoformat(),
        "environment": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "source_mode": args.source_mode,
            "max_nodes": args.max_nodes,
            "repeat_count": args.repeat,
            "latency_state": (
                "The first timed query for each project uses a newly created runtime (cold_runtime); "
                "later queries reuse it (warm_runtime). Graph loading and runtime construction occur "
                "before the timer and are not included."
            ),
        },
        "projects": projects,
        "results": [asdict(result) for result in results],
        "report": stratified_report(
            results,
            calibration_bins=args.calibration_bins,
            abstain_threshold=args.abstain_threshold,
        ),
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
