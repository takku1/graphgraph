"""Application service for GraphGraph's canonical acceptance board."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from .runner import graph_identity, run_case
from .scoreboard import summarize, to_json, to_markdown
from .tasks import CANONICAL_TASKS
from .tokens import count_tokens


@dataclass(frozen=True)
class AcceptanceExecution:
    report: str
    exit_code: int
    summary: dict


def select_tasks(case_ids: Sequence[str] = ()):
    """Select canonical tasks in registry order and reject unknown IDs."""
    if not case_ids:
        return CANONICAL_TASKS
    wanted = set(case_ids)
    known = {task.id for task in CANONICAL_TASKS}
    unknown = sorted(wanted - known)
    if unknown:
        raise ValueError(f"unknown acceptance case(s): {', '.join(unknown)}")
    return tuple(task for task in CANONICAL_TASKS if task.id in wanted)


def execute_acceptance(
    *,
    repo: Path,
    graph_path: Path | None = None,
    case_ids: Sequence[str] = (),
    as_json: bool = False,
    output: Path | None = None,
) -> AcceptanceExecution:
    """Run the sealed-ground-truth board through GraphGraph's public API."""
    repo = repo.resolve()
    if not repo.is_dir():
        raise ValueError(f"repository not found: {repo}")
    graph_path = (graph_path or (repo / ".graphgraph" / "graph.gg")).resolve()
    if not graph_path.is_file():
        raise FileNotFoundError(
            f"graph not found: {graph_path}\n"
            "run: graphgraph scan --depth symbols --docs"
        )

    tasks = select_tasks(case_ids)
    cases = [run_case(task, repo, graph_path) for task in tasks]
    identity = graph_identity(graph_path)
    environment = {
        "repo": str(repo),
        "graph": str(graph_path),
        "graph_hash": identity.get("hash", "n/a"),
        "graph_files": identity.get("files", "?"),
        "token_mode": (
            "tiktoken cl100k/o200k"
            if count_tokens("x").precise
            else "proxy"
        ),
    }
    summary = summarize(cases)
    report = (
        json.dumps(to_json(cases, environment=environment), indent=2)
        if as_json
        else to_markdown(cases, environment=environment)
    )
    if output is not None:
        output = output.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(report + "\n", encoding="utf-8")
    return AcceptanceExecution(
        report=report,
        exit_code=0 if summary["release_ready"] else 1,
        summary=summary,
    )
