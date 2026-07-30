"""Retrieval evaluation and confidence-calibration CLI commands."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from ..analysis.eval import (
    EvalTasksError,
    evaluate_graph,
    load_eval_tasks,
    results_to_json,
    results_with_calibration_to_json,
)
from ..analysis.eval_protocol import (
    EvalProtocolError,
    load_eval_results,
    paired_bootstrap_comparison,
    stratified_report,
)


def cmd_eval(args: argparse.Namespace) -> None:
    try:
        tasks = load_eval_tasks(Path(args.tasks))
    except EvalTasksError as exc:
        raise SystemExit(f"graphgraph eval: {exc}") from exc
    results = evaluate_graph(
        Path(args.graph),
        tasks,
        max_nodes=args.max_nodes,
        source_mode=getattr(args, "source_mode", "auto"),
    )
    baseline_path = getattr(args, "baseline_results", None)
    if getattr(args, "report", False) or baseline_path:
        payload: dict[str, object] = {
            "results": [asdict(result) for result in results],
            "report": stratified_report(
                results,
                calibration_bins=args.calibration_bins,
                abstain_threshold=args.abstain_threshold,
            ),
        }
        if baseline_path:
            try:
                payload["comparison"] = paired_bootstrap_comparison(
                    load_eval_results(Path(baseline_path)),
                    results,
                    metric=args.compare_metric,
                    minimum_effect=args.minimum_effect,
                    samples=args.bootstrap_samples,
                    seed=args.bootstrap_seed,
                )
            except (ValueError, EvalProtocolError) as exc:
                raise SystemExit(f"graphgraph eval: cannot compare: {exc}") from exc
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return
    if getattr(args, "calibration", False):
        try:
            payload = results_with_calibration_to_json(
                results,
                bins=args.calibration_bins,
                complete_recall=args.complete_recall,
            )
        except ValueError as exc:
            raise SystemExit(f"graphgraph eval: cannot calibrate: {exc}") from exc
        print(payload)
        return
    print(results_to_json(results))


__all__ = ["cmd_eval"]
