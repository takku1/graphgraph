from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from collections import Counter

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from graphgraph.scanner import scan_directory
from graphgraph.ontology import is_weak_relation
from graphgraph.io import save_graph

OUT_DIR = ROOT / "benchmarks" / "context_graph" / "out" / "live"
REPORT_MD = OUT_DIR / "all_local_repos_report.md"
REPORT_JSON = OUT_DIR / "all_local_repos_report.json"

SKIP_DIRS = [
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
    ".venv",
    "venv",
    ".env",
    "env",
]

SOURCE_KINDS = {"python", "typescript", "javascript", "rust", "go", "java", "c", "cpp", "header", "lean"}
SYMBOL_KINDS = {"function", "method", "class", "struct", "enum", "trait", "theorem"}
DOC_KINDS = {"markdown", "rst", "text", "section", "concept"}

def check_is_valid_project(path: Path) -> bool:
    if not path.is_dir():
        return False
    if path.name.startswith("."):
        return False
    # Check if there are any code or doc files in the top directories
    try:
        for p in path.iterdir():
            if p.is_file() and p.suffix.lower() in {".py", ".rs", ".js", ".ts", ".go", ".java", ".cs", ".cpp", ".c", ".lean", ".md", ".rst", ".txt"}:
                return True
            if p.is_dir() and p.name not in SKIP_DIRS:
                # check one level deeper
                try:
                    for sub in p.iterdir():
                        if sub.is_file() and sub.suffix.lower() in {".py", ".rs", ".js", ".ts", ".go", ".java", ".cs", ".cpp", ".c", ".lean", ".md", ".rst", ".txt"}:
                            return True
                except Exception:
                    pass
    except Exception:
        pass
    return False

def scan_project(path: Path) -> dict:
    start_time = time.perf_counter()
    try:
        graph = scan_directory(
            path,
            max_nodes=300, # File budget of 300 files per project
            skip_dirs=SKIP_DIRS,
            depth="symbols",
            frontend="auto",
            docs=True,
        )
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        
        # Save scanned graph to live benchmarks folder for reference
        graph_save_path = OUT_DIR / f"local_scan_{path.name}.json"
        save_graph(graph, graph_save_path)
        
        node_kinds = Counter(n.kind for n in graph.nodes.values())
        relations = Counter(e.type for e in graph.edges if e.active)
        weak_edges = sum(1 for e in graph.edges if e.active and is_weak_relation(e.type))
        
        source_files = sum(1 for n in graph.nodes.values() if n.kind in SOURCE_KINDS)
        symbol_nodes = sum(1 for n in graph.nodes.values() if n.kind in SYMBOL_KINDS)
        doc_nodes = sum(1 for n in graph.nodes.values() if n.kind in DOC_KINDS)
        
        return {
            "name": path.name,
            "path": str(path),
            "ok": True,
            "error": "",
            "nodes": len(graph.nodes),
            "edges": len(graph.edges),
            "sources": source_files,
            "symbols": symbol_nodes,
            "docs": doc_nodes,
            "imports": relations.get("imports", 0),
            "calls": relations.get("calls", 0),
            "explains": relations.get("explains", 0),
            "weak_ratio": round(weak_edges / max(1, len(graph.edges)), 4),
            "doc_ratio": round(doc_nodes / max(1, len(graph.nodes)), 4),
            "time_ms": round(elapsed_ms, 2)
        }
    except Exception as exc:
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        return {
            "name": path.name,
            "path": str(path),
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "nodes": 0,
            "edges": 0,
            "sources": 0,
            "symbols": 0,
            "docs": 0,
            "imports": 0,
            "calls": 0,
            "explains": 0,
            "weak_ratio": 0.0,
            "doc_ratio": 0.0,
            "time_ms": round(elapsed_ms, 2)
        }

def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    
    projects_root = Path(os.environ.get("AIPROJECTS_ROOT", Path.home() / "aiprojects"))
    resources_root = Path(os.environ.get("RESOURCES_ROOT", projects_root / "resources"))
    roots = [projects_root, resources_root]
    
    project_paths = []
    seen_paths = set()
    
    for r in roots:
        if r.exists():
            for p in r.iterdir():
                resolved = p.resolve()
                if resolved in seen_paths:
                    continue
                if check_is_valid_project(resolved):
                    project_paths.append(resolved)
                    seen_paths.add(resolved)
                    
    print(f"Found {len(project_paths)} projects to scan.")
    
    results = []
    for idx, path in enumerate(project_paths, 1):
        print(f"[{idx}/{len(project_paths)}] Scanning {path.name} ({path.parent.name})...", flush=True)
        res = scan_project(path)
        res["source_group"] = path.parent.name
        results.append(res)
        
    # Write JSON results
    REPORT_JSON.write_text(json.dumps({"results": results}, indent=2), encoding="utf-8")
    
    # Render Markdown table
    lines = [
        "# All Local Codebases - Scan & Shape Metrics",
        "",
        "This report scans all valid projects found under `aiprojects` and `aiprojects/resources` directories.",
        "It provides empirical shape diagnostics on node density, doc coverage, calls/symbol ratio, and scan time.",
        "",
        "| Project | Group | OK | Nodes | Edges | Sources | Symbols | Docs | Imports | Calls | Weak Ratio | Doc Ratio | Time (ms) |",
        "| :--- | :--- | :---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"
    ]
    
    for res in sorted(results, key=lambda x: (x["source_group"], x["name"])):
        ok_indicator = "✅" if res["ok"] else f"❌ {res['error']}"
        lines.append(
            f"| `{res['name']}` | `{res['source_group']}` | {ok_indicator} | {res['nodes']} | {res['edges']} | "
            f"{res['sources']} | {res['symbols']} | {res['docs']} | {res['imports']} | {res['calls']} | "
            f"{res['weak_ratio']:.4f} | {res['doc_ratio']:.4f} | {res['time_ms']:.1f} |"
        )
        
    lines.extend([
        "",
        "## Diagnostic Insights",
        "",
        "1. **Missing imports/calls**: If a code-heavy repository (e.g. `requests`, `flask`) reports low calls or imports, it highlights missing parser features or intra-code topology scanning bugs.",
        "2. **Documentation Bloat**: High Doc Ratio indicates repositories where docs dominate. This is normal for specs (like `lean4` libraries or documentation folders) but increases retrieval noise in standard code projects.",
        "3. **Scan Latency**: Latency scales with AST complexities and file system sizes. High latency identifies candidates for incremental optimization."
    ])
    
    markdown_content = "\n".join(lines) + "\n"
    REPORT_MD.write_text(markdown_content, encoding="utf-8")
    print("\nScan completed successfully! Report generated at all_local_repos_report.md.")
    
if __name__ == "__main__":
    main()
