"""CLI: ``python -m graphgraph.acceptance run --repo <path>``.

Drives the canonical Locus regression tasks against a real graph and prints the
scoreboard. Ground truth is used only to score packets already produced.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from .service import execute_acceptance


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="acceptance")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="run the canonical acceptance cases")
    run.add_argument("--repo", required=True, type=Path, help="target repository root")
    run.add_argument("--graph", type=Path, default=None, help="graph path (default <repo>/.graphgraph/graph.gg)")
    run.add_argument("--case", action="append", default=None, help="only run these case ids")
    run.add_argument("--json", dest="as_json", action="store_true", help="emit JSON instead of Markdown")
    run.add_argument("--out", type=Path, default=None, help="also write the report to this path")
    args = parser.parse_args(argv)

    try:
        execution = execute_acceptance(
            repo=args.repo,
            graph_path=args.graph,
            case_ids=args.case or (),
            as_json=args.as_json,
            output=args.out,
        )
    except (ValueError, FileNotFoundError) as exc:
        parser.error(str(exc))
        return 2
    print(execution.report)
    return execution.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
