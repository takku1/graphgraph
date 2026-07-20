from __future__ import annotations

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from graphgraph.concepts.doccode import summarize_doc_code_components, summarize_doc_code_coverage  # noqa: E402
from graphgraph.io import load_any  # noqa: E402

OUT = ROOT / "benchmarks" / "context_graph" / "out" / "real_projects"
GRAPHS = OUT / "graphs"
RESULTS_CSV = OUT / "doc_code_pairing_results.csv"
SUMMARY_MD = OUT / "doc_code_pairing_report.md"


def run() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for graph_path in sorted(GRAPHS.glob("*.json")):
        graph = load_any(graph_path)
        coverage = summarize_doc_code_coverage(graph)
        components = summarize_doc_code_components(graph)
        total = coverage.paired_keys + coverage.doc_only_keys + coverage.code_only_keys + coverage.unlabeled_keys
        rows.append(
            {
                "project": graph_path.stem,
                "total_keys": total,
                "paired_keys": coverage.paired_keys,
                "doc_only_keys": coverage.doc_only_keys,
                "code_only_keys": coverage.code_only_keys,
                "unlabeled_keys": coverage.unlabeled_keys,
                "paired_components": components.paired_components,
                "doc_only_components": components.doc_only_components,
                "code_only_components": components.code_only_components,
                "unlabeled_components": components.unlabeled_components,
                "paired_examples": format_examples(coverage.paired_examples),
                "doc_only_examples": format_examples(coverage.doc_only_examples),
                "code_only_examples": format_examples(coverage.code_only_examples),
                "unlabeled_examples": format_examples(coverage.unlabeled_examples),
                "paired_component_examples": format_component_examples(components.paired_examples),
                "doc_only_component_examples": format_component_examples(components.doc_only_examples),
                "code_only_component_examples": format_component_examples(components.code_only_examples),
                "unlabeled_component_examples": format_component_examples(components.unlabeled_examples),
            }
        )
    return rows


def format_examples(items) -> str:
    parts = []
    for item in items[:4]:
        left = ",".join(item.doc_nodes[:2]) if item.doc_nodes else "-"
        right = ",".join(item.code_nodes[:2]) if item.code_nodes else "-"
        parts.append(f"{item.key} [{left}] <-> [{right}]")
    return " | ".join(parts)


def format_component_examples(items) -> str:
    parts = []
    for item in items[:4]:
        left = ",".join(item.doc_nodes[:2]) if item.doc_nodes else "-"
        right = ",".join(item.code_nodes[:2]) if item.code_nodes else "-"
        doc_keys = ",".join(item.doc_keys[:2]) if item.doc_keys else "-"
        code_keys = ",".join(item.code_keys[:2]) if item.code_keys else "-"
        parts.append(f"{item.component} {doc_keys} [{left}] <-> {code_keys} [{right}]")
    return " | ".join(parts)


def write(rows: list[dict[str, object]]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    fields = [
        "project",
        "total_keys",
        "paired_keys",
        "doc_only_keys",
        "code_only_keys",
        "unlabeled_keys",
        "paired_components",
        "doc_only_components",
        "code_only_components",
        "unlabeled_components",
        "paired_examples",
        "doc_only_examples",
        "code_only_examples",
        "unlabeled_examples",
        "paired_component_examples",
        "doc_only_component_examples",
        "code_only_component_examples",
        "unlabeled_component_examples",
    ]
    with RESULTS_CSV.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})

    total_keys = sum(int(row["total_keys"]) for row in rows)
    paired = sum(int(row["paired_keys"]) for row in rows)
    doc_only = sum(int(row["doc_only_keys"]) for row in rows)
    code_only = sum(int(row["code_only_keys"]) for row in rows)
    unlabeled = sum(int(row["unlabeled_keys"]) for row in rows)
    paired_components = sum(int(row["paired_components"]) for row in rows)
    doc_only_components = sum(int(row["doc_only_components"]) for row in rows)
    code_only_components = sum(int(row["code_only_components"]) for row in rows)
    unlabeled_components = sum(int(row["unlabeled_components"]) for row in rows)

    lines = [
        "# Doc-Code Pairing Report",
        "",
        "This benchmark inventories semantic keys across the saved real-project graphs and splits them into four buckets:",
        "",
        "- doc-only: a concept or section exists in docs, but no matching code implementation key is present",
        "- code-only: a code symbol exists, but no matching doc concept or section key is present",
        "- paired: both doc and code sides exist for the same semantic key",
        "- unlabeled: the graph contains nodes that do not participate in either side of the key classifier",
        "",
        "| Project | Total keys | Paired | Doc-only | Code-only | Unlabeled |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in sorted(rows, key=lambda r: str(r["project"])):
        lines.append(
            f"| {row['project']} | {int(row['total_keys'])} | {int(row['paired_keys'])} | "
            f"{int(row['doc_only_keys'])} | {int(row['code_only_keys'])} | {int(row['unlabeled_keys'])} |"
        )

    lines.extend(
        [
            "",
            "## Aggregate",
            "",
            f"- Total keys: `{total_keys}`",
            f"- Paired keys: `{paired}`",
            f"- Doc-only keys: `{doc_only}`",
            f"- Code-only keys: `{code_only}`",
            f"- Unlabeled keys: `{unlabeled}`",
            f"- Paired components: `{paired_components}`",
            f"- Doc-only components: `{doc_only_components}`",
            f"- Code-only components: `{code_only_components}`",
            f"- Unlabeled components: `{unlabeled_components}`",
            "",
            "## Read",
            "",
            "- Paired keys are the current fastest signal for merged document+code coverage.",
            "- Doc-only keys are documentation gaps or concepts that never landed in code.",
            "- Code-only keys are implementation gaps or symbols that need doc anchoring.",
            "- Unlabeled keys are the lowest-priority bucket unless they hide high-value nodes.",
            "- Paired components are the stricter signal: doc and code nodes are actually connected in the graph.",
            "- If keys are paired but components are not, the labels overlap but the graph does not yet prove the relationship.",
            "",
            "## Examples",
            "",
            "| Project | Paired examples | Doc-only examples | Code-only examples |",
            "| --- | --- | --- | --- |",
        ]
    )
    for row in sorted(rows, key=lambda r: str(r["project"])):
        lines.append(
            f"| {row['project']} | {row['paired_examples'] or '-'} | {row['doc_only_examples'] or '-'} | "
            f"{row['code_only_examples'] or '-'} |"
        )

    lines.extend(
        [
            "",
            "## Component Examples",
            "",
            "| Project | Paired components | Doc-only components | Code-only components |",
            "| --- | --- | --- | --- |",
        ]
    )
    for row in sorted(rows, key=lambda r: str(r["project"])):
        lines.append(
            f"| {row['project']} | {row['paired_component_examples'] or '-'} | {row['doc_only_component_examples'] or '-'} | "
            f"{row['code_only_component_examples'] or '-'} |"
        )

    lines.extend(["", f"CSV: `{RESULTS_CSV.relative_to(ROOT)}`"])
    SUMMARY_MD.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    rows = run()
    write(rows)
    print(f"Wrote {SUMMARY_MD.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
