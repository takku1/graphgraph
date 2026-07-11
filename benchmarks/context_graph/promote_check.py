from __future__ import annotations

import csv
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "benchmarks" / "context_graph" / "out" / "promotion"
REPORT_JSON = OUT / "promotion_report.json"
REPORT_MD = OUT / "promotion_report.md"


@dataclass(frozen=True)
class Gate:
    name: str
    ok: bool
    detail: str


def run_command(name: str, command: list[str], timeout: int = 180) -> Gate:
    proc = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
    )
    tail = "\n".join(proc.stdout.strip().splitlines()[-10:])
    return Gate(name, proc.returncode == 0, tail)


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    gates: list[Gate] = []

    gates.append(run_command("unit_tests", [sys.executable, "-m", "unittest", "discover", "-s", "tests"]))
    gates.append(run_command("live_graph_shape", [sys.executable, "benchmarks/context_graph/live_graph_shape.py"]))
    gates.append(run_command("search_hot_path", [sys.executable, "benchmarks/context_graph/search_hot_path_benchmark.py"]))
    gates.append(run_command("token_proxy_calibration", [sys.executable, "benchmarks/context_graph/token_proxy_calibration.py"]))
    gates.append(run_command("real_project_answerability", [sys.executable, "benchmarks/context_graph/real_project_answerability_limit.py"], timeout=240))
    gates.append(run_command("dynamic_budget", [sys.executable, "benchmarks/context_graph/dynamic_budget_benchmark.py"], timeout=240))
    gates.append(run_command("frontier_policy", [sys.executable, "benchmarks/context_graph/frontier_policy_benchmark.py"], timeout=240))
    gates.append(run_command("planner_fit", [sys.executable, "benchmarks/context_graph/planner_fit_benchmark.py"]))
    gates.append(run_command("prompt_preflight", [sys.executable, "benchmarks/context_graph/prompt_preflight.py"]))
    gates.append(run_command("codex_integration", [sys.executable, "benchmarks/context_graph/codex_integration_check.py"]))
    gates.append(run_command("integration_inventory", [sys.executable, "benchmarks/context_graph/integration_inventory.py"]))

    computed = computed_gates()
    gates.extend(computed)

    report = {
        "ok": all(gate.ok for gate in gates),
        "gates": [gate.__dict__ for gate in gates],
    }
    REPORT_JSON.write_text(json.dumps(report, indent=2), encoding="utf-8")
    REPORT_MD.write_text(render_markdown(gates), encoding="utf-8")
    print(REPORT_MD.read_text(encoding="utf-8"))
    if not report["ok"]:
        raise SystemExit("promotion gates failed")


def computed_gates() -> list[Gate]:
    gates: list[Gate] = []

    shape_path = ROOT / "benchmarks/context_graph/out/live/live_graph_shape.json"
    if shape_path.exists():
        shape = json.loads(shape_path.read_text(encoding="utf-8"))
        imports_per_source = float(shape.get("imports_per_source_file", 0.0))
        query_valid = all(row.get("valid") for row in shape.get("queries", []))
        zero_gate = shape.get("negative_gate", {})
        gates.append(Gate("shape_import_floor", imports_per_source >= 0.05, f"imports/source={imports_per_source:.4f}"))
        gates.append(Gate("shape_query_packets_valid", query_valid, f"{sum(1 for row in shape.get('queries', []) if row.get('valid'))}/{len(shape.get('queries', []))} valid"))
        gates.append(Gate("shape_zero_edge_gate", zero_gate.get("format") == "semantic_arrow" and zero_gate.get("edges") == 0, str(zero_gate)))
    else:
        gates.append(Gate("shape_report_present", False, "missing live_graph_shape.json"))

    answer_rows = read_csv(ROOT / "benchmarks/context_graph/out/real_projects/real_project_answerability_limit.csv")
    current = [row for row in answer_rows if row.get("candidate") == "current_default"]
    current_answerable = sum(1 for row in current if row.get("answerable", "").lower() == "true")
    gates.append(Gate("current_answerability", bool(current) and current_answerable == len(current), f"{current_answerable}/{len(current)} current_default answerable"))

    frontier_rows = read_csv(ROOT / "benchmarks/context_graph/out/real_projects/frontier_policy_results.csv")
    current_frontier = [row for row in frontier_rows if row.get("policy") == "current_expand"]
    current_frontier_answerable = sum(1 for row in current_frontier if row.get("answerable", "").lower() == "true")
    gates.append(Gate("frontier_current_expand", bool(current_frontier) and current_frontier_answerable == len(current_frontier), f"{current_frontier_answerable}/{len(current_frontier)} current_expand answerable"))

    proxy_rows = read_csv(ROOT / "benchmarks/context_graph/out/real_projects/token_proxy_calibration.csv")
    zero_edge_keys = {
        (row.get("project"), row.get("start_kind"), row.get("start"), row.get("hops"))
        for row in proxy_rows
        if row.get("edges") == "0"
    }
    zero_edge_semantic_matches = {
        (row.get("project"), row.get("start_kind"), row.get("start"), row.get("hops"))
        for row in proxy_rows
        if row.get("edges") == "0" and row.get("semantic_vs_gg_match", "").lower() == "true"
    }
    gates.append(Gate(
        "token_proxy_zero_edge_semantic_gg",
        bool(zero_edge_keys) and len(zero_edge_semantic_matches) == len(zero_edge_keys),
        f"{len(zero_edge_semantic_matches)}/{len(zero_edge_keys)} runtime-relevant zero-edge decisions match",
    ))

    dynamic_rows = read_csv(ROOT / "benchmarks/context_graph/out/real_projects/dynamic_budget_results.csv")
    shape_rows = [row for row in dynamic_rows if row.get("candidate") == "shape_recommended"]
    shape_answerable = sum(1 for row in shape_rows if row.get("answerable", "").lower() == "true")
    gates.append(Gate(
        "dynamic_budget_shape_recall",
        bool(shape_rows) and shape_answerable == len(shape_rows),
        f"{shape_answerable}/{len(shape_rows)} shape_recommended answerable",
    ))

    reasoning = ROOT / "benchmarks/context_graph/out/protocol/model_reasoning_summary.md"
    if reasoning.exists():
        text = reasoning.read_text(encoding="utf-8", errors="replace")
        skipped = "Live model execution skipped" in text
        gates.append(Gate("live_model_scoring_status", True, "skipped; required only for model-quality promotion" if skipped else "present"))
    else:
        gates.append(Gate("live_model_scoring_status", False, "missing model_reasoning_summary.md"))

    return gates


def render_markdown(gates: list[Gate]) -> str:
    lines = [
        "# Promotion Check",
        "",
        "| Gate | Status | Detail |",
        "| --- | --- | --- |",
    ]
    for gate in gates:
        status = "PASS" if gate.ok else "FAIL"
        detail = gate.detail.replace("\n", "<br>")
        lines.append(f"| `{gate.name}` | `{status}` | {detail} |")
    lines.extend([
        "",
        "## Read",
        "",
        "- Passing this report means retrieval/packet/scanner changes are structurally promotable.",
        "- It does not prove live model answer quality unless model reasoning was explicitly run.",
        "- Failed gates should be fixed or documented as hypotheses, not promoted as defaults.",
    ])
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
