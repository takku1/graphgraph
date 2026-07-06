from __future__ import annotations

import ast
import json
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BENCH = ROOT / "benchmarks" / "context_graph"
OUT = BENCH / "out" / "inventory"
REPORT_JSON = OUT / "integration_inventory.json"
REPORT_MD = OUT / "integration_inventory.md"


EXEMPT = {
    "integration_inventory.py",
    "promote_check.py",
    "run_all.py",
}


@dataclass(frozen=True)
class ScriptStatus:
    script: str
    in_run_all: bool
    in_promotion: bool
    documented: bool
    status: str
    next_action: str


def _literal_scripts(path: Path, variable_name: str) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == variable_name for target in node.targets):
            continue
        value = ast.literal_eval(node.value)
        return {str(item) for item in value}
    return set()


def _text_mentions(paths: list[Path]) -> str:
    parts = []
    for path in paths:
        if path.exists():
            parts.append(path.read_text(encoding="utf-8", errors="replace"))
    return "\n".join(parts)


def inventory() -> list[ScriptStatus]:
    run_all = _literal_scripts(BENCH / "run_all.py", "SCRIPTS")
    promote_text = (BENCH / "promote_check.py").read_text(encoding="utf-8", errors="replace")
    docs_text = _text_mentions([
        BENCH / "README.md",
        ROOT / "docs" / "empirical-findings.md",
        ROOT / "docs" / "adaptive-planning-math.md",
        ROOT / "docs" / "towards_publishable_research.md",
        ROOT / "docs" / "rigorous-framing.md",
    ])

    rows: list[ScriptStatus] = []
    for path in sorted(BENCH.glob("*.py")):
        script = path.name
        if script in EXEMPT:
            continue
        in_run_all = script in run_all
        in_promotion = script in promote_text
        documented = script in docs_text
        if in_promotion:
            status = "promotion"
            next_action = "Keep load-bearing; regressions should fail promote_check."
        elif in_run_all and documented:
            status = "integrated"
            next_action = "Keep as benchmark coverage."
        elif in_run_all:
            status = "run_all_only"
            next_action = "Document the claim it supports or remove from run_all."
        elif documented:
            status = "documented_only"
            next_action = "Add to run_all/promote if still current, otherwise mark archived."
        else:
            status = "exploratory"
            next_action = "Promote, document, archive, or delete after reading current output."
        rows.append(ScriptStatus(script, in_run_all, in_promotion, documented, status, next_action))
    return rows


def render_markdown(rows: list[ScriptStatus]) -> str:
    counts: dict[str, int] = {}
    for row in rows:
        counts[row.status] = counts.get(row.status, 0) + 1

    lines = [
        "# Benchmark Integration Inventory",
        "",
        "This report classifies benchmark scripts by whether they are part of the",
        "promotion gate, the broad run-all suite, or the written empirical record.",
        "Exploratory does not mean bad; it means the script is not yet load-bearing.",
        "",
        "## Counts",
        "",
        "| Status | Count |",
        "| --- | ---: |",
    ]
    for status in sorted(counts):
        lines.append(f"| `{status}` | {counts[status]} |")

    lines.extend([
        "",
        "## Scripts",
        "",
        "| Script | Status | Run all | Promotion | Documented | Next action |",
        "| --- | --- | ---: | ---: | ---: | --- |",
    ])
    for row in rows:
        lines.append(
            f"| `{row.script}` | `{row.status}` | "
            f"{'yes' if row.in_run_all else 'no'} | "
            f"{'yes' if row.in_promotion else 'no'} | "
            f"{'yes' if row.documented else 'no'} | {row.next_action} |"
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    rows = inventory()
    REPORT_JSON.write_text(
        json.dumps({"scripts": [row.__dict__ for row in rows]}, indent=2),
        encoding="utf-8",
    )
    report = render_markdown(rows)
    REPORT_MD.write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
