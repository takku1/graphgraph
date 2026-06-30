from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from graphgraph.io import save_graph  # noqa: E402
from graphgraph.ontology import is_weak_relation  # noqa: E402
from graphgraph.packets import render_packet  # noqa: E402
from graphgraph.scanner import scan_directory  # noqa: E402
from graphgraph.validate import validate_packet  # noqa: E402


OUT = ROOT / "benchmarks" / "context_graph" / "out" / "live"
REPORT_JSON = OUT / "cross_project_live_shape.json"
REPORT_MD = OUT / "cross_project_live_shape.md"

DEFAULT_REPOS = (ROOT,)

DEFAULT_SKIP_DIRS = (
    ".code-review-graph",
    ".git",
    ".graphgraph",
    ".pytest_cache",
    "__pycache__",
    "benchmarks/context_graph/out",
    "dist",
    "build",
    "graphify-out",
    "node_modules",
    "target",
    "tmp",
    "vendor",
    ".lake",
)

SOURCE_KINDS = {"python", "typescript", "javascript", "rust", "go", "java", "c", "cpp", "header", "lean"}
SYMBOL_KINDS = {"function", "method", "class", "struct", "enum", "trait", "theorem"}
DOC_KINDS = {"markdown", "rst", "text", "section", "concept"}


@dataclass(frozen=True)
class RepoShape:
    name: str
    repo: str
    graph_path: str
    refreshed_project_graph: str
    ok: bool
    error: str
    nodes: int
    edges: int
    source_files: int
    symbol_nodes: int
    doc_nodes: int
    import_edges: int
    calls_edges: int
    explains_edges: int
    imports_per_source_file: float
    calls_per_symbol: float
    weak_edge_ratio: float
    doc_node_ratio: float
    zero_packet_valid: bool
    zero_packet_format: str
    top_node_kinds: list[tuple[str, int]]
    top_relations: list[tuple[str, int]]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Measure live GraphGraph scan shape for one selected repo.")
    parser.add_argument("--repo", type=Path, default=ROOT, help="Repo path to scan. Defaults to this graphgraph repo.")
    parser.add_argument("--max-nodes", type=int, default=1200)
    parser.add_argument("--frontend", default="auto", choices=["auto", "regex", "tree_sitter"])
    parser.add_argument(
        "--refresh-project-graph",
        action="store_true",
        help="Also write each rebuilt graph to <repo>/.graphgraph/graph.json.",
    )
    return parser.parse_args()


def safe_name(path: Path) -> str:
    return path.name.replace(" ", "_").replace(".", "_")


def scan_repo(repo: Path, *, max_nodes: int, frontend: str, refresh_project_graph: bool) -> RepoShape:
    repo = repo.resolve()
    graph_path = OUT / f"cross_project_{safe_name(repo)}.graph.json"
    try:
        graph = scan_directory(
            repo,
            max_nodes=max_nodes,
            skip_dirs=list(DEFAULT_SKIP_DIRS),
            depth="symbols",
            frontend=frontend,
            docs=True,
            previous_graph_path=None,
            manifest_path=None,
        )
        save_graph(graph, graph_path)
        refreshed_project_graph = ""
        if refresh_project_graph:
            project_graph_path = repo / ".graphgraph" / "graph.json"
            project_graph_path.parent.mkdir(parents=True, exist_ok=True)
            save_graph(graph, project_graph_path)
            refreshed_project_graph = str(project_graph_path)
        node_kinds = Counter(node.kind for node in graph.nodes.values())
        relations = Counter(edge.type for edge in graph.edges if edge.active)
        weak_edges = sum(1 for edge in graph.edges if edge.active and is_weak_relation(edge.type))
        source_files = sum(1 for node in graph.nodes.values() if node.kind in SOURCE_KINDS)
        symbol_nodes = sum(1 for node in graph.nodes.values() if node.kind in SYMBOL_KINDS)
        doc_nodes = sum(1 for node in graph.nodes.values() if node.kind in DOC_KINDS)
        zero_packet = render_packet(graph, {next(iter(graph.nodes))} if graph.nodes else set(), [], "semantic_arrow")
        zero_validation = validate_packet(zero_packet)
        import_edges = relations.get("imports", 0)
        calls_edges = relations.get("calls", 0)
        explains_edges = relations.get("explains", 0)
        return RepoShape(
            name=repo.name,
            repo=str(repo),
            graph_path=str(graph_path),
            refreshed_project_graph=refreshed_project_graph,
            ok=True,
            error="",
            nodes=len(graph.nodes),
            edges=len(graph.edges),
            source_files=source_files,
            symbol_nodes=symbol_nodes,
            doc_nodes=doc_nodes,
            import_edges=import_edges,
            calls_edges=calls_edges,
            explains_edges=explains_edges,
            imports_per_source_file=round(import_edges / max(1, source_files), 4),
            calls_per_symbol=round(calls_edges / max(1, symbol_nodes), 4),
            weak_edge_ratio=round(weak_edges / max(1, len(graph.edges)), 4),
            doc_node_ratio=round(doc_nodes / max(1, len(graph.nodes)), 4),
            zero_packet_valid=zero_validation.ok,
            zero_packet_format=zero_validation.format,
            top_node_kinds=node_kinds.most_common(8),
            top_relations=relations.most_common(8),
        )
    except Exception as exc:
        return RepoShape(
            name=repo.name,
            repo=str(repo),
            graph_path=str(graph_path),
            refreshed_project_graph="",
            ok=False,
            error=f"{type(exc).__name__}: {exc}",
            nodes=0,
            edges=0,
            source_files=0,
            symbol_nodes=0,
            doc_nodes=0,
            import_edges=0,
            calls_edges=0,
            explains_edges=0,
            imports_per_source_file=0.0,
            calls_per_symbol=0.0,
            weak_edge_ratio=0.0,
            doc_node_ratio=0.0,
            zero_packet_valid=False,
            zero_packet_format="",
            top_node_kinds=[],
            top_relations=[],
        )


def render_markdown(rows: list[RepoShape]) -> str:
    lines = [
        "# Cross-Project Live Shape",
        "",
        "This report scans one selected repo with the current live scanner. It is for",
        "calibrating thresholds and finding scanner gaps, not for promotion by itself.",
        "Existing project `.graphgraph` directories are ignored during measurement.",
        "",
        "| Repo | OK | Nodes | Edges | Sources | Symbols | Docs | Imports/source | Calls/symbol | Weak ratio | Doc ratio | Zero gate | Refreshed |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    for row in rows:
        gate = f"{row.zero_packet_format}:{row.zero_packet_valid}" if row.ok else row.error
        lines.append(
            f"| `{row.name}` | `{row.ok}` | {row.nodes} | {row.edges} | {row.source_files} | "
            f"{row.symbol_nodes} | {row.doc_nodes} | {row.imports_per_source_file:.4f} | "
            f"{row.calls_per_symbol:.4f} | {row.weak_edge_ratio:.4f} | {row.doc_node_ratio:.4f} | `{gate}` |"
            f" {'yes' if row.refreshed_project_graph else 'no'} |"
        )

    lines.extend([
        "",
        "## Reads",
        "",
        "- Low imports/source on code-heavy repos suggests missing import resolver coverage.",
        "- Low calls/symbol suggests symbol extraction without useful intra-code topology.",
        "- High doc ratio is acceptable for documentation repos but a noise risk for code retrieval.",
        "- Failed rows should be treated as scanner compatibility bugs or skip-rule gaps.",
    ])
    return "\n".join(lines) + "\n"


def main() -> None:
    args = parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    repos = [args.repo or DEFAULT_REPOS[0]]
    rows = [
        scan_repo(
            repo,
            max_nodes=args.max_nodes,
            frontend=args.frontend,
            refresh_project_graph=args.refresh_project_graph,
        )
        for repo in repos
    ]
    REPORT_JSON.write_text(json.dumps({"repos": [row.__dict__ for row in rows]}, indent=2), encoding="utf-8")
    report = render_markdown(rows)
    REPORT_MD.write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
