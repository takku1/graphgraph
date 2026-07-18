from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Sequence

DEFAULT_SKIP_DIRS = (
    "tmp",
    "graphify-out",
    ".code-review-graph",
    ".pytest_cache",
    "__pycache__",
    "node_modules",
)
STRUCTURAL_NODE_KINDS = {
    "class",
    "enum",
    "file",
    "function",
    "interface",
    "method",
    "module",
    "python",
    "struct",
    "theorem",
    "trait",
}
SAVED_REPORT_PATHS = {
    "planner_fit": "benchmarks/context_graph/out/real_projects/planner_fit_report.md",
    "frontier": "benchmarks/context_graph/out/real_projects/frontier_policy_report.md",
    "doc_code_pairing": "benchmarks/context_graph/out/real_projects/doc_code_pairing_report.md",
    "model_reasoning": "benchmarks/context_graph/out/protocol/model_reasoning_summary.md",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate GraphGraph against any live codebase.")
    parser.add_argument("--repo", type=Path, default=Path.cwd(), help="Target repository to scan.")
    parser.add_argument("--max-nodes", type=int, default=1800, help="Maximum scan collection budget.")
    parser.add_argument(
        "--query",
        action="append",
        default=[],
        help="Live query to run instead of repo-derived defaults. Repeatable.",
    )
    parser.add_argument("--skip-tests", action="store_true", help="Do not run a repository test command.")
    parser.add_argument(
        "--test-command",
        help='Override ecosystem detection, for example: --test-command "cargo test --workspace".',
    )
    parser.add_argument("--test-timeout", type=float, default=600.0, help="Test-command timeout in seconds.")
    parser.add_argument(
        "--saved-reports",
        action="store_true",
        help="Compare GraphGraph-project benchmark reports. Off by default for foreign repositories.",
    )
    return parser


def split_command(command: str) -> list[str]:
    parts = shlex.split(command, posix=True)
    if not parts:
        raise ValueError("--test-command must not be empty")
    return parts


def detect_test_command(repo: Path) -> tuple[list[str] | None, str]:
    if (repo / "Cargo.toml").exists():
        return ["cargo", "test", "--workspace"], "cargo"
    if (repo / "go.mod").exists():
        return ["go", "test", "./..."], "go"
    if (repo / "package.json").exists():
        try:
            package = json.loads((repo / "package.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            package = {}
        if isinstance(package.get("scripts"), dict) and package["scripts"].get("test"):
            return ["npm", "test"], "npm"
    tests = repo / "tests"
    if tests.is_dir():
        pyproject = (repo / "pyproject.toml").read_text(encoding="utf-8", errors="replace") if (
            repo / "pyproject.toml"
        ).exists() else ""
        if (
            "[tool.pytest" in pyproject
            or (repo / "pytest.ini").exists()
            or (repo / "conftest.py").exists()
            or (tests / "conftest.py").exists()
        ):
            return [sys.executable, "-m", "pytest", "-q"], "pytest"
        return [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-t", "."], "unittest"
    return None, "none"


def _test_count(output: str) -> int | None:
    python_match = re.search(r"\bRan (\d+) tests?\b", output)
    if python_match:
        return int(python_match.group(1))
    pytest_match = re.search(r"\b(\d+) passed\b", output)
    if pytest_match:
        return int(pytest_match.group(1))
    cargo_matches = re.findall(r"test result: \w+\.\s+(\d+) passed;", output)
    if cargo_matches:
        return sum(int(value) for value in cargo_matches)
    go_matches = re.findall(r"^ok\s+\S+", output, re.MULTILINE)
    return len(go_matches) if go_matches else None


def run_tests(
    repo: Path,
    *,
    command_text: str | None = None,
    timeout: float = 600.0,
) -> dict[str, Any]:
    if command_text:
        command = split_command(command_text)
        ecosystem = "override"
    else:
        command, ecosystem = detect_test_command(repo)
    if command is None:
        return {
            "status": "skipped",
            "ok": None,
            "reason": "no supported test ecosystem detected",
            "ecosystem": ecosystem,
            "command": [],
        }
    try:
        proc = subprocess.run(
            command,
            cwd=repo,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "status": "failed",
            "ok": False,
            "reason": f"{exc.__class__.__name__}: {exc}",
            "ecosystem": ecosystem,
            "command": command,
            "tests": None,
            "tail": "",
        }
    return {
        "status": "passed" if proc.returncode == 0 else "failed",
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "ecosystem": ecosystem,
        "command": command,
        "tests": _test_count(proc.stdout),
        "tail": "\n".join(proc.stdout.strip().splitlines()[-12:]),
    }


def summarize_graph(graph: Any) -> dict[str, Any]:
    node_kinds = Counter(node.kind for node in graph.nodes.values())
    relations = Counter(edge.type for edge in graph.edges if getattr(edge, "active", True))
    docs = sum(1 for node in graph.nodes.values() if node.kind in {"section", "paragraph", "concept", "document"})
    code = sum(1 for node in graph.nodes.values() if node.kind in STRUCTURAL_NODE_KINDS)
    return {
        "nodes": len(graph.nodes),
        "edges": len(graph.edges),
        "doc_like_nodes": docs,
        "code_like_nodes": code,
        "top_node_kinds": node_kinds.most_common(12),
        "top_relations": relations.most_common(12),
    }


def derived_queries(graph: Any) -> list[tuple[str, str]]:
    outgoing = graph.outgoing()
    candidates = [
        node
        for node in graph.nodes.values()
        if getattr(node, "active", True)
        and node.kind in STRUCTURAL_NODE_KINDS
        and outgoing.get(node.id)
        and node.label.strip()
    ]
    candidates.sort(key=lambda node: (-len(outgoing[node.id]), node.path or "", node.label))
    labels: list[str] = []
    for node in candidates:
        if node.label not in labels:
            labels.append(node.label)
        if len(labels) == 3:
            break
    if not labels:
        labels = [
            node.label
            for node in graph.nodes.values()
            if getattr(node, "active", True) and node.label.strip()
        ][:1]
    if not labels:
        return []
    first = labels[0]
    queries = [
        (first, "direct_lookup"),
        (f"callers and dependents of {first}", "reverse_lookup"),
        (f"what changes if {first} changes", "blast_radius"),
    ]
    if len(labels) > 1:
        queries.append((f"how does {first} reach {labels[1]}", "multi_hop_path"))
    return queries


def validate_queries(graph: Any, graph_path: Path, query_texts: Sequence[str]) -> list[dict[str, Any]]:
    from graphgraph.services import render_query_context
    from graphgraph.validate import validate_packet

    queries = [(query, "blast_radius") for query in query_texts] if query_texts else derived_queries(graph)
    rows: list[dict[str, Any]] = []
    for query, query_class in queries:
        try:
            raw = render_query_context(
                query=query,
                query_class=query_class,
                graph_path=graph_path,
                show_anchors=True,
                json_anchors=True,
                cache_namespace="skill_validate_live",
            )
            data = json.loads(raw)
            packet = data.get("packet", "")
            validation = validate_packet(packet) if packet else None
            rows.append(
                {
                    "query": query,
                    "query_class": query_class,
                    "anchors": len(data.get("anchors", [])),
                    "packet_format": validation.format if validation else "",
                    "packet_valid": bool(validation and validation.ok),
                    "packet_nodes": validation.node_count if validation else 0,
                    "packet_edges": validation.edge_count if validation else 0,
                    "errors": list(validation.errors) if validation else ["no packet"],
                }
            )
        except Exception as exc:
            rows.append(
                {
                    "query": query,
                    "query_class": query_class,
                    "anchors": 0,
                    "packet_format": "",
                    "packet_valid": False,
                    "packet_nodes": 0,
                    "packet_edges": 0,
                    "errors": [f"{exc.__class__.__name__}: {exc}"],
                }
            )
    return rows


def validate_gate_packets(graph: Any, graph_path: Path) -> list[dict[str, Any]]:
    from graphgraph.services import render_final_packet
    from graphgraph.validate import validate_packet

    outgoing = graph.outgoing()
    candidates = [
        node.id
        for node in graph.nodes.values()
        if getattr(node, "active", True) and node.kind in STRUCTURAL_NODE_KINDS and outgoing.get(node.id)
    ]
    candidates.sort(key=lambda node_id: (-len(outgoing[node_id]), node_id))
    if not candidates:
        return [{"case": "structural_start", "ok": False, "errors": ["graph has no connected structural node"]}]
    start = candidates[0]
    cases = [
        ("negative_query_zero_edge", "negative_query", "semantic_arrow", 0),
        ("direct_lookup_structural", "direct_lookup", "gg", None),
    ]
    rows: list[dict[str, Any]] = []
    for case, query_class, expected_format, expected_edges in cases:
        try:
            packet = render_final_packet(
                starts=[start],
                query_class=query_class,
                query_text=f"live validation for {graph.nodes[start].label}",
                graph_path=graph_path,
                policies_path=None,
                cache_namespace="skill_validate_gate",
            )
            validation = validate_packet(packet.removeprefix("GRAPH:\n"))
            edge_ok = expected_edges is None or validation.edge_count == expected_edges
            if case == "direct_lookup_structural":
                edge_ok = validation.edge_count > 0
            rows.append(
                {
                    "case": case,
                    "start": start,
                    "expected_format": expected_format,
                    "format": validation.format,
                    "expected_edges": expected_edges,
                    "edges": validation.edge_count,
                    "nodes": validation.node_count,
                    "ok": validation.ok and validation.format == expected_format and edge_ok,
                    "errors": list(validation.errors),
                }
            )
        except Exception as exc:
            rows.append(
                {
                    "case": case,
                    "start": start,
                    "expected_format": expected_format,
                    "format": "",
                    "expected_edges": expected_edges,
                    "edges": 0,
                    "nodes": 0,
                    "ok": False,
                    "errors": [f"{exc.__class__.__name__}: {exc}"],
                }
            )
    return rows


def load_saved_reports(repo: Path, enabled: bool) -> dict[str, Any]:
    if not enabled:
        return {"status": "skipped", "reason": "enable with --saved-reports for GraphGraph self-validation"}
    reports: dict[str, Any] = {"status": "checked", "reports": {}}
    for name, relative in SAVED_REPORT_PATHS.items():
        path = repo / relative
        reports["reports"][name] = {"exists": path.exists(), "path": str(path)}
    return reports


def write_markdown(report: dict[str, Any], path: Path) -> None:
    tests = report["tests"]
    lines = [
        "# GraphGraph Live Validation",
        "",
        f"- Repo: `{report['repo']}`",
        f"- Graph: `{report['graph_path']}`",
        f"- Tests: `{tests['status']}`"
        + (f" ({tests.get('tests')} tests via `{tests.get('ecosystem')}`)" if tests.get("tests") is not None else ""),
        f"- Saved reports: `{report['saved_reports']['status']}`",
        "",
        "## Live graph",
        "",
        f"- Nodes: `{report['graph']['nodes']}`",
        f"- Edges: `{report['graph']['edges']}`",
        f"- Doc-like nodes: `{report['graph']['doc_like_nodes']}`",
        f"- Code-like nodes: `{report['graph']['code_like_nodes']}`",
        "",
        "## Query packet validation",
        "",
        "| Query | Class | Anchors | Format | Valid | Nodes | Edges |",
        "| --- | --- | ---: | --- | --- | ---: | ---: |",
    ]
    for row in report["queries"]:
        lines.append(
            f"| {row['query']} | `{row['query_class']}` | {row['anchors']} | `{row['packet_format']}` | "
            f"`{row['packet_valid']}` | {row['packet_nodes']} | {row['packet_edges']} |"
        )
    lines.extend(
        [
            "",
            "## Structural gate checks",
            "",
            "| Case | Expected | Actual | Valid | Nodes | Edges |",
            "| --- | --- | --- | --- | ---: | ---: |",
        ]
    )
    for row in report["gate_checks"]:
        lines.append(
            f"| `{row['case']}` | `{row['expected_format']}` | `{row['format']}` | "
            f"`{row['ok']}` | {row['nodes']} | {row['edges']} |"
        )
    if tests.get("tail"):
        lines.extend(["", "## Test tail", "", "```text", tests["tail"], "```"])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repo = args.repo.resolve()
    if not repo.is_dir():
        raise SystemExit(f"repo does not exist: {repo}")

    from graphgraph.io import save_graph
    from graphgraph.scanner import scan_directory

    out_dir = repo / ".graphgraph" / "skill-validation"
    out_dir.mkdir(parents=True, exist_ok=True)
    graph_path = out_dir / "live.graph.json"
    graph = scan_directory(
        repo,
        max_nodes=args.max_nodes,
        generic_mentions=False,
        skip_dirs=DEFAULT_SKIP_DIRS,
        depth="symbols",
        frontend="auto",
        docs=True,
        previous_graph_path=None,
        manifest_path=None,
    )
    save_graph(graph, graph_path)
    tests = (
        {"status": "skipped", "ok": None, "reason": "disabled by --skip-tests", "command": []}
        if args.skip_tests
        else run_tests(repo, command_text=args.test_command, timeout=args.test_timeout)
    )
    report = {
        "repo": str(repo),
        "graph_path": str(graph_path),
        "graph": summarize_graph(graph),
        "queries": validate_queries(graph, graph_path, args.query),
        "gate_checks": validate_gate_packets(graph, graph_path),
        "saved_reports": load_saved_reports(repo, args.saved_reports),
        "tests": tests,
    }
    json_path = out_dir / "report.json"
    markdown_path = out_dir / "report.md"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    write_markdown(report, markdown_path)
    summary = {
        "report": str(markdown_path),
        "nodes": report["graph"]["nodes"],
        "edges": report["graph"]["edges"],
        "queries_valid": sum(row["packet_valid"] for row in report["queries"]),
        "queries_total": len(report["queries"]),
        "gates_valid": sum(row["ok"] for row in report["gate_checks"]),
        "gates_total": len(report["gate_checks"]),
        "tests_status": tests["status"],
    }
    print(json.dumps(summary, indent=2))
    structural_ok = (
        summary["queries_valid"] == summary["queries_total"]
        and summary["gates_valid"] == summary["gates_total"]
    )
    tests_ok = tests["ok"] is not False
    return 0 if structural_ok and tests_ok else 1

