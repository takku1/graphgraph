from __future__ import annotations

import csv
import os
import sys
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from graphgraph.core import Edge, Graph, Node  # noqa: E402
from graphgraph.eval import estimate_tokens  # noqa: E402
from graphgraph.io import load_any, save_graph  # noqa: E402
from graphgraph.packets import render_packet  # noqa: E402
from graphgraph.planning import compute_subgraph_stats, plan_context, refine_plan_for_subgraph  # noqa: E402
from graphgraph.retrieval import retrieve_context  # noqa: E402
from graphgraph.scanner import scan_directory  # noqa: E402


OUT = ROOT / "benchmarks" / "context_graph" / "out" / "cross_repo_anchor"
GRAPHS = OUT / "graphs"
RESULTS_CSV = OUT / "cross_repo_anchor_stress.csv"
SUMMARY_MD = OUT / "cross_repo_anchor_stress.md"

DEFAULT_PROJECT_PATHS = (
    r"C:\Users\dcarn\aiprojects\graphgraph",
    r"C:\Users\dcarn\aiprojects\contextminer",
    r"C:\Users\dcarn\aiprojects\chess",
    r"C:\Users\dcarn\aiprojects\slotmachine",
    r"C:\Users\dcarn\aiprojects\resources\requests",
    r"C:\Users\dcarn\aiprojects\resources\flask",
    r"C:\Users\dcarn\aiprojects\resources\regex",
    r"C:\Users\dcarn\aiprojects\resources\z3",
)

GENERIC_LABELS = {
    "__call__",
    "__init__",
    "call",
    "config",
    "context",
    "dense",
    "engine",
    "flask",
    "init",
    "main",
    "readme",
    "regex",
    "test",
}
TASK_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "do",
    "does",
    "for",
    "from",
    "how",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "this",
    "to",
    "what",
    "which",
    "with",
}
HUB_NODE_KINDS = {
    "class",
    "enum",
    "function",
    "method",
    "python",
    "javascript",
    "typescript",
    "rust",
    "go",
    "java",
    "header",
    "source",
}

SKIP_DIRS = (
    ".git",
    ".graphgraph",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
    ".venv",
    "venv",
    "node_modules",
    "target",
    "build",
    "dist",
    "graphify-out",
    "benchmarks/context_graph/out",
)


@dataclass(frozen=True)
class Task:
    query: str
    query_class: str
    expected_nodes: tuple[str, ...]
    kind: str


def project_paths() -> list[Path]:
    raw = os.environ.get("CROSS_REPO_PATHS")
    if raw:
        return [Path(item.strip()) for item in raw.split(";") if item.strip()]
    return [Path(item) for item in DEFAULT_PROJECT_PATHS]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    GRAPHS.mkdir(parents=True, exist_ok=True)
    max_nodes = int(os.environ.get("CROSS_REPO_MAX_NODES", "700"))
    frontend = os.environ.get("CROSS_REPO_FRONTEND", "auto")
    reuse_graphs = os.environ.get("CROSS_REPO_REUSE_GRAPHS", "1") == "1"

    rows: list[dict[str, object]] = []
    for path in project_paths():
        project = path.name
        if not path.exists():
            rows.append({"project": project, "status": "missing", "error": "path does not exist"})
            continue
        graph_path = GRAPHS / f"{safe_name(project)}.json"
        try:
            if reuse_graphs and graph_path.exists():
                graph = load_any(graph_path)
            else:
                graph = scan_directory(path, max_nodes=max_nodes, skip_dirs=SKIP_DIRS, depth="symbols", frontend=frontend, docs=True)
                save_graph(graph, graph_path)
        except Exception as exc:  # pragma: no cover - benchmark diagnostics
            rows.append({"project": project, "status": "scan_error", "error": f"{type(exc).__name__}: {exc}"})
            continue

        for task in make_tasks(graph):
            rows.append(score_task(project, graph, task))

    write(rows, max_nodes=max_nodes, frontend=frontend)
    failures = [row for row in rows if row.get("status") not in {"ok", "missing", "scan_error"}]
    print(SUMMARY_MD.read_text(encoding="utf-8"))
    if failures:
        raise SystemExit(f"{len(failures)} cross-repo anchor stress task(s) failed")


def make_tasks(graph: Graph) -> list[Task]:
    tasks: list[Task] = []
    active = [node for node in graph.nodes.values() if node.active]
    symbol_nodes = [
        node for node in active
        if node.kind in {"function", "method", "class", "struct", "enum", "trait"} and usable_anchor_node(node)
    ]
    file_nodes = [
        node for node in active
        if node.path and node.kind in {"file", "python", "typescript", "javascript", "rust", "go", "markdown"} and usable_anchor_node(node)
    ]
    concept_nodes = [node for node in active if node.kind in {"concept", "section"} and usable_concept_node(node)]

    for node in diverse_nodes(symbol_nodes, limit=4):
        tasks.append(Task(split_query(node), "direct_lookup", (node.id,), "symbol_direct"))
    for node in diverse_nodes(file_nodes, limit=3):
        tasks.append(Task(split_query(node), "subsystem_summary", (node.id,), "file_summary"))
    for node in diverse_nodes(concept_nodes, limit=2):
        tasks.append(Task(split_query(node), "subsystem_summary", (node.id,), "concept_summary"))

    outgoing = graph.outgoing()
    degree = graph.degree()
    hubs = sorted(
        (
            node for node in active
            if outgoing.get(node.id)
            and node.kind in HUB_NODE_KINDS
            and usable_anchor_node(node)
        ),
        key=lambda n: degree.get(n.id, 0),
        reverse=True,
    )
    for node in hubs[:2]:
        neighbor_edges = outgoing.get(node.id, [])[:2]
        expected = tuple(dict.fromkeys([node.id, *(edge.target for edge in neighbor_edges)]))
        tasks.append(Task(split_query(node), "blast_radius", expected, "hub_blast"))

    sparse = sorted((node for node in active if usable_anchor_node(node)), key=lambda n: degree.get(n.id, 0))[:1]
    for node in sparse:
        tasks.append(Task(split_query(node), "negative_query", (node.id,), "negative_sparse"))
    return tasks


def usable_anchor_node(node: Node) -> bool:
    query = split_query(node)
    terms = query.split()
    if len(query) < 4 or not any(ch.isalpha() for ch in query):
        return False
    if has_control_chars(query):
        return False
    if len(terms) == 1 and terms[0] in GENERIC_LABELS:
        return False
    return True


def usable_concept_node(node: Node) -> bool:
    query = split_query(node)
    terms = query.split()
    if len(terms) < 2:
        return False
    if any(term in TASK_STOPWORDS for term in terms):
        return False
    if has_control_chars(query):
        return False
    if not (query[0].isalnum() and query[-1].isalnum()):
        return False
    alpha_count = sum(ch.isalpha() for ch in query)
    return alpha_count / max(1, len(query)) >= 0.55


def has_control_chars(value: str) -> bool:
    return any(ord(ch) < 32 for ch in value)


def diverse_nodes(nodes: list[Node], limit: int) -> list[Node]:
    out: list[Node] = []
    seen_paths: set[str] = set()
    for node in sorted(nodes, key=lambda n: (n.path.count("/") + n.path.count("\\"), n.path, n.label)):
        bucket = node.path.rsplit("/", 1)[0].rsplit("\\", 1)[0] if node.path else node.kind
        if bucket in seen_paths and len(out) < limit - 1:
            continue
        seen_paths.add(bucket)
        out.append(node)
        if len(out) >= limit:
            break
    return out


def score_task(project: str, graph: Graph, task: Task) -> dict[str, object]:
    plan = plan_context(task.query_class, task.query)
    result = retrieve_context(graph, task.query, task.query_class, hops=plan.hops, max_nodes=plan.node_budget)
    plan = refine_plan_for_subgraph(plan, compute_subgraph_stats(graph, result.nodes, result.edges))
    packet = render_packet(graph, result.nodes, result.edges, plan.packet)
    returned = returned_node_keys(graph, result.nodes)
    expected = set(task.expected_nodes)
    hits = len(expected & returned)
    recall = hits / max(1, len(expected))
    irrelevant_ratio = (len(result.nodes) - hits) / max(1, len(result.nodes))
    tokens_per_hit = estimate_tokens(packet) / max(1, hits)
    status = "ok" if recall >= 1.0 else "recall_fail"
    return {
        "project": project,
        "status": status,
        "error": "",
        "task_kind": task.kind,
        "query_class": task.query_class,
        "query": task.query,
        "expected_nodes": len(expected),
        "hits": hits,
        "node_recall": round(recall, 4),
        "returned_nodes": len(result.nodes),
        "returned_edges": len(result.edges),
        "irrelevant_ratio": round(irrelevant_ratio, 4),
        "packet": plan.packet,
        "tokens": estimate_tokens(packet),
        "tokens_per_hit": round(tokens_per_hit, 3),
        "missing": " ".join(missing_labels(graph, expected - returned)),
    }


def split_query(node: Node) -> str:
    raw = node.label or Path(node.path).stem or node.id
    raw = strip_suffix(raw)
    parts = []
    for token in raw.replace("_", " ").replace("-", " ").replace(".", " ").split():
        parts.extend(split_camel(token))
    query = " ".join(part.lower() for part in parts if len(part) >= 2 and part.lower() not in TASK_STOPWORDS)
    return query or raw.lower()


def split_camel(value: str) -> list[str]:
    out: list[str] = []
    current = ""
    for ch in value:
        if current and ch.isupper() and (current[-1].islower() or current[-1].isdigit()):
            out.append(current)
            current = ch
        else:
            current += ch
    if current:
        out.append(current)
    return out


def expected_node_keys(node: Node) -> tuple[str, ...]:
    keys = [node.id, node.label]
    if node.path:
        keys.extend([node.path, Path(node.path).name, strip_suffix(Path(node.path).name)])
    keys.append(strip_suffix(node.label))
    return tuple(dict.fromkeys(key for key in keys if key))


def returned_node_keys(graph: Graph, node_ids: set[str]) -> set[str]:
    return set(node_ids)


def missing_labels(graph: Graph, missing: set[str]) -> list[str]:
    labels = []
    for node_id in sorted(missing):
        node = graph.nodes.get(node_id)
        labels.append(f"{node.label}<{node_id}>" if node else node_id)
    return labels


def strip_suffix(value: str) -> str:
    for suffix in (".py", ".pyi", ".js", ".jsx", ".ts", ".tsx", ".rs", ".go", ".java", ".c", ".h", ".hpp", ".cpp", ".cs", ".md", ".rst", ".txt", ".json", ".yaml", ".yml", ".toml"):
        if value.lower().endswith(suffix):
            return value[: -len(suffix)]
    return value


def write(rows: list[dict[str, object]], *, max_nodes: int, frontend: str) -> None:
    fields = [
        "project", "status", "error", "task_kind", "query_class", "query",
        "expected_nodes", "hits", "node_recall", "returned_nodes", "returned_edges",
        "irrelevant_ratio", "packet", "tokens", "tokens_per_hit", "missing",
    ]
    with RESULTS_CSV.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})

    ok_rows = [row for row in rows if row.get("status") == "ok"]
    eval_rows = [row for row in rows if row.get("status") in {"ok", "recall_fail"}]
    failures = [row for row in rows if row.get("status") == "recall_fail"]
    by_project: dict[str, list[dict[str, object]]] = {}
    for row in eval_rows:
        by_project.setdefault(str(row["project"]), []).append(row)

    lines = [
        "# Cross-Repo Anchor Stress",
        "",
        "Fixed-policy synthetic anchor recall over scanned local projects and cloned resources.",
        "",
        f"Frontend: `{frontend}`",
        f"Max scan nodes: `{max_nodes}`",
        f"Tasks: `{len(eval_rows)}`",
        f"Pass: `{len(ok_rows)}/{len(eval_rows)}`",
        f"Avg recall: `{avg(eval_rows, 'node_recall'):.3f}`",
        f"Avg tokens: `{avg(eval_rows, 'tokens'):.1f}`",
        f"Avg irrelevant ratio: `{avg(eval_rows, 'irrelevant_ratio'):.3f}`",
        "",
        "| Project | Tasks | Pass | Avg recall | Avg tokens | Tokens/hit | Irrelevant ratio | Avg nodes | Avg edges |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for project, items in sorted(by_project.items()):
        passed = len([row for row in items if row.get("status") == "ok"])
        lines.append(
            f"| {project} | {len(items)} | {passed} | {avg(items, 'node_recall'):.3f} | "
            f"{avg(items, 'tokens'):.1f} | {avg(items, 'tokens_per_hit'):.1f} | "
            f"{avg(items, 'irrelevant_ratio'):.3f} | {avg(items, 'returned_nodes'):.1f} | {avg(items, 'returned_edges'):.1f} |"
        )
    by_kind: dict[str, list[dict[str, object]]] = {}
    for row in eval_rows:
        by_kind.setdefault(str(row["task_kind"]), []).append(row)
    lines.extend([
        "",
        "## By Task Kind",
        "",
        "| Kind | Tasks | Pass | Avg recall | Avg tokens | Tokens/hit | Irrelevant ratio |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ])
    for kind, items in sorted(by_kind.items()):
        passed = len([row for row in items if row.get("status") == "ok"])
        lines.append(
            f"| {kind} | {len(items)} | {passed} | {avg(items, 'node_recall'):.3f} | "
            f"{avg(items, 'tokens'):.1f} | {avg(items, 'tokens_per_hit'):.1f} | {avg(items, 'irrelevant_ratio'):.3f} |"
        )

    worst_noise = sorted(eval_rows, key=lambda row: (float(row.get("irrelevant_ratio", 0)), float(row.get("tokens", 0))), reverse=True)[:10]
    lines.extend([
        "",
        "## Noisiest Passing/Failing Cases",
        "",
        "| Project | Kind | Class | Query | Recall | Tokens | Irrelevant ratio |",
        "| --- | --- | --- | --- | ---: | ---: | ---: |",
    ])
    for row in worst_noise:
        lines.append(
            f"| {row['project']} | {row['task_kind']} | {row['query_class']} | {row['query']} | "
            f"{row['node_recall']} | {row['tokens']} | {row['irrelevant_ratio']} |"
        )
    if failures:
        lines.extend([
            "",
            "## Failures",
            "",
            "| Project | Kind | Class | Query | Recall | Missing |",
            "| --- | --- | --- | --- | ---: | --- |",
        ])
        for row in failures[:30]:
            lines.append(
                f"| {row['project']} | {row['task_kind']} | {row['query_class']} | {row['query']} | "
                f"{row['node_recall']} | {row['missing']} |"
            )
    lines.extend([
        "",
        "## Read",
        "",
        "- This holds the current production policy fixed; it does not tune per repository.",
        "- Failures indicate anchor/search generalization gaps, not packet-format losses.",
        f"- CSV: `{RESULTS_CSV.relative_to(ROOT)}`",
    ])
    SUMMARY_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def avg(rows: list[dict[str, object]], key: str) -> float:
    values = [float(row[key]) for row in rows if row.get(key) not in {"", None}]
    return sum(values) / max(1, len(values))


def safe_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in value)


if __name__ == "__main__":
    main()
