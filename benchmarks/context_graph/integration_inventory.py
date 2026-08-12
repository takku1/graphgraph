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
    in_tests: bool
    in_research_registry: bool
    in_src_provenance: bool
    used_by_peers: bool
    protected: bool
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


def _tree_text(root: Path, pattern: str) -> str:
    """Concatenate every file matching `pattern` under `root`.

    Globbed rather than hardcoded: this scanner previously listed four
    individual doc paths, and all four had been moved by a docs
    reorganisation. Every script then scored `documented=False` regardless
    of the written record, which is how genuinely load-bearing scripts came
    to look `exploratory`.
    """
    if not root.exists():
        return ""
    return "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in sorted(root.rglob(pattern))
    )


def inventory() -> list[ScriptStatus]:
    run_all = _literal_scripts(BENCH / "run_all.py", "SCRIPTS")
    promote_text = (BENCH / "promote_check.py").read_text(encoding="utf-8", errors="replace")
    # Whole docs tree, plus this suite's own README.
    docs_text = _tree_text(ROOT / "docs", "*.md") + "\n" + _text_mentions([BENCH / "README.md"])
    # A script imported by a test is load-bearing no matter what the docs say:
    # deleting it breaks the suite.
    tests_text = _tree_text(ROOT / "tests", "*.py")
    # eval/*.json carries the research claim ledger. Scripts cited there are
    # the standing evidence for a claim -- including *rejected* claims, whose
    # artifacts tests/test_research_registry.py requires to still exist. A
    # concluded finding is therefore not a licence to delete the script.
    registry_text = _tree_text(ROOT / "eval", "*.json")
    # src/ comments cite benchmarks as the derivation source for shipped
    # numeric constants; deleting one severs a production audit trail.
    src_text = _tree_text(ROOT / "src", "*.py")

    rows: list[ScriptStatus] = []
    for path in sorted(BENCH.glob("*.py")):
        script = path.name
        if script in EXEMPT:
            continue
        # Match on the stem so module imports (`from ... import x`) count
        # alongside literal `foo.py` mentions. Over-detection is the safe
        # direction here: a false reference keeps a file, a missed one
        # deletes something load-bearing.
        stem = path.stem
        in_run_all = script in run_all
        in_promotion = stem in promote_text
        documented = stem in docs_text
        in_tests = stem in tests_text
        in_research_registry = stem in registry_text
        in_src_provenance = stem in src_text
        # Shared helpers inside this suite are imported by sibling scripts and
        # by nothing else, so every other signal reads as "unreferenced".
        used_by_peers = any(
            stem in peer.read_text(encoding="utf-8", errors="replace")
            for peer in BENCH.glob("*.py")
            if peer != path
        )
        protected = (
            in_promotion
            or in_tests
            or in_research_registry
            or in_src_provenance
            or used_by_peers
        )

        if in_tests:
            status = "test_dependency"
            next_action = "Do not delete; imported by the test suite."
        elif in_research_registry:
            status = "research_evidence"
            next_action = "Do not delete; cited as claim evidence in eval/ (registry test enforces existence)."
        elif in_src_provenance:
            status = "src_provenance"
            next_action = "Do not delete; cited in src/ as the derivation source for a shipped constant."
        elif in_promotion:
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
        elif used_by_peers:
            status = "shared_helper"
            next_action = "Do not delete; imported by sibling benchmark scripts."
        else:
            status = "exploratory"
            next_action = "Promote, document, archive, or delete after reading current output."
        rows.append(
            ScriptStatus(
                script,
                in_run_all,
                in_promotion,
                documented,
                in_tests,
                in_research_registry,
                in_src_provenance,
                used_by_peers,
                protected,
                status,
                next_action,
            )
        )
    return rows


def render_markdown(rows: list[ScriptStatus]) -> str:
    counts: dict[str, int] = {}
    for row in rows:
        counts[row.status] = counts.get(row.status, 0) + 1

    protected_count = sum(1 for row in rows if row.protected)
    deletable = [row.script for row in rows if row.status == "exploratory"]

    lines = [
        "# Benchmark Integration Inventory",
        "",
        "This report classifies benchmark scripts by whether they are part of the",
        "promotion gate, the broad run-all suite, or the written empirical record.",
        "Exploratory does not mean bad; it means the script is not yet load-bearing.",
        "",
        "`protected` means at least one of: imported by the test suite, cited as",
        "claim evidence in `eval/`, named in `src/` as a constant's derivation",
        "source, imported by a sibling benchmark, or wired into `promote_check.py`.",
        "Protected scripts must not be deleted on the strength of looking",
        "undocumented -- a *rejected* research claim still requires its evidence",
        "artifact to exist.",
        "",
        "## Counts",
        "",
        "| Status | Count |",
        "| --- | ---: |",
    ]
    for status in sorted(counts):
        lines.append(f"| `{status}` | {counts[status]} |")
    lines.append(f"| **protected (any reason)** | **{protected_count}** |")
    lines.append(f"| **unreferenced (`exploratory`)** | **{len(deletable)}** |")

    lines.extend([
        "",
        "## Scripts",
        "",
        "| Script | Status | Protected | Run all | Promotion | Docs | Tests | Registry | src | Peers | Next action |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ])

    def mark(flag: bool) -> str:
        return "yes" if flag else "no"

    for row in rows:
        lines.append(
            f"| `{row.script}` | `{row.status}` | "
            f"{mark(row.protected)} | "
            f"{mark(row.in_run_all)} | "
            f"{mark(row.in_promotion)} | "
            f"{mark(row.documented)} | "
            f"{mark(row.in_tests)} | "
            f"{mark(row.in_research_registry)} | "
            f"{mark(row.in_src_provenance)} | "
            f"{mark(row.used_by_peers)} | {row.next_action} |"
        )

    lines.extend([
        "",
        "## Unreferenced scripts",
        "",
        "No reference found in run_all, promote_check, docs, tests, eval registry,",
        "or src provenance. These are the only deletion candidates, and each still",
        "warrants reading its current output before removal.",
        "",
    ])
    if deletable:
        lines.extend(f"- `{script}`" for script in deletable)
    else:
        lines.append("_None._")
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
