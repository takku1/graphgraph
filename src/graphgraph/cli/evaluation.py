"""Retrieval evaluation and confidence-calibration CLI commands."""

from __future__ import annotations

import argparse
from pathlib import Path

from ..analysis.eval import (
    EvalTasksError,
    evaluate_graph,
    load_eval_tasks,
    results_to_json,
    results_with_calibration_to_json,
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
