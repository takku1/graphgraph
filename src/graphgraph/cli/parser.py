import argparse

from ..scanner import DEFAULT_SCAN_MAX_NODES
from ..version import package_version
from .commands import (
    cmd_cache,
    cmd_compare,
    cmd_context,
    cmd_doctor,
    cmd_eval,
    cmd_export,
    cmd_final,
    cmd_frontends,
    cmd_ingest,
    cmd_install,
    cmd_ontology,
    cmd_plan,
    cmd_profile,
    cmd_query,
    cmd_remove,
    cmd_render,
    cmd_scan,
    cmd_snippets,
    cmd_status,
    cmd_traversal,
    cmd_update,
    cmd_validate,
    cmd_validate_graph,
)
from .platform import add_platform_parser


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="graphgraph")
    parser.add_argument("--version", action="version", version=f"%(prog)s {package_version()}")
    sub = parser.add_subparsers(dest="cmd", required=True)

    plan = sub.add_parser("plan")
    plan.add_argument("--query-class", required=True)
    plan.add_argument("--query", default="")
    plan.set_defaults(func=cmd_plan)

    render = sub.add_parser("render")
    render.add_argument("--graph")
    render.add_argument("--query-class", required=True)
    render.add_argument("--starts", nargs="+", required=True)
    render.add_argument("--max-nodes", type=int, help="Expanded node budget. Default: dynamic by query class and graph shape.")
    render.set_defaults(func=cmd_render)

    final = sub.add_parser("final")
    final.add_argument("--graph")
    final.add_argument("--policies")
    final.add_argument("--query", default="")
    final.add_argument("--query-class", required=False)
    final.add_argument("--starts", nargs="+", required=False)
    final.add_argument("--path", action="append", default=[])
    final.add_argument("--tag", action="append", default=[])
    final.add_argument("--stable-skeleton", action="store_true", help="Compile a stable, PageRank-based skeleton of top architectural nodes to use as a static prompt cache prefix.")
    final.add_argument("--full-graph", action="store_true", help="Render every active node/edge with no query/budget -- an explicit escape hatch, not the default path. Refuses over --full-graph-max-tokens unless raised or disabled.")
    final.add_argument("--full-graph-max-tokens", type=int, default=20_000, help="Token guard for --full-graph (default: 20000). Pass 0 to disable.")
    final.add_argument("--max-nodes", type=int, default=None, help="Expanded node budget. Default: dynamic by query class and graph shape; stable skeleton uses 100.")
    final.add_argument("--packet", choices=["lowlevel", "sql", "hybrid", "semantic_arrow", "gg", "gg_hybrid", "gg_lex", "gg_lex_hybrid", "svo", "doc_summary"])
    final.set_defaults(func=cmd_final)

    query = sub.add_parser("query", help="Retrieve a query-specific graph context packet without preselecting node IDs.")
    query.add_argument("query", help="Natural-language query used to find graph anchors.")
    query.add_argument("--graph")
    query.add_argument("--query-class", default="auto", help="Routing policy (default: auto; explicit classes remain supported).")
    query.add_argument("--packet", choices=["lowlevel", "sql", "hybrid", "semantic_arrow", "gg", "gg_hybrid", "gg_lex", "gg_lex_hybrid", "svo", "doc_summary"])
    query.add_argument("--hops", type=int)
    query.add_argument("--anchor-limit", type=int, help="Max anchor nodes before expansion. Default: adaptive by query class.")
    query.add_argument("--max-nodes", type=int, help="Expanded node budget. Default: dynamic by query class and graph shape.")
    query.add_argument("--scope", action="append", default=[], help="Restrict retrieval to node scope/path prefix. Repeatable.")
    query.add_argument("--scope-mode", choices=["strict", "expand"], default="strict",
                       help="strict keeps every result in scope; expand permits structurally connected boundary crossings.")
    query.add_argument("--show-anchors", action="store_true")
    query.add_argument("--source-mode", choices=["auto", "off", "all"], default="auto")
    query.add_argument("--memory-scope", action="append", default=[])
    query.add_argument("--show-stats", action="store_true", help="Print graph load shape metrics to stderr.")
    query.set_defaults(func=cmd_query)

    context = sub.add_parser("context", help="One-step native workflow: ensure a graph exists, then render query context.")
    context.add_argument("query", help="Natural-language query used to find graph anchors.")
    context.add_argument("--directory", "-d", help="Root directory to scan if a graph must be built (default: cwd).")
    context.add_argument("--graph", help="Graph path to read/write (default: .graphgraph/graph.gg).")
    context.add_argument("--rebuild", action="store_true", help="Force a graph rebuild before querying.")
    context.add_argument("--scan-max-nodes", type=int, default=DEFAULT_SCAN_MAX_NODES, help=f"Auto-build file cap; symbol extraction has a separate proportional cap (default: {DEFAULT_SCAN_MAX_NODES} files).")
    context.add_argument("--query-class", default="auto", help="Routing policy (default: auto; explicit classes remain supported).")
    context.add_argument("--packet", choices=["lowlevel", "sql", "hybrid", "semantic_arrow", "gg", "gg_hybrid", "gg_lex", "gg_lex_hybrid", "svo", "doc_summary"])
    context.add_argument("--anchor-limit", type=int, help="Max anchor nodes before expansion. Default: adaptive by query class.")
    context.add_argument("--max-nodes", type=int, help="Expanded node budget. Default: dynamic by query class and graph shape.")
    context.add_argument("--scope", action="append", default=[], help="Restrict retrieval to node scope/path prefix. Repeatable.")
    context.add_argument("--scope-mode", choices=["strict", "expand"], default="strict",
                         help="strict keeps every result in scope; expand permits structurally connected boundary crossings.")
    context.add_argument("--skip-dirs", nargs="*", metavar="DIR", help="Additional directory names to skip during auto-build.")
    context.add_argument("--exclude", nargs="*", metavar="DIR", dest="exclude_dirs", help="Alias: extra directory names to exclude during auto-build.")
    context.add_argument("--include", nargs="*", metavar="DIR",
                         help="Directory names to keep even though a default skip rule would drop them.")
    context.add_argument("--depth", choices=["files", "symbols"], default="symbols",
                         help="'files': one node per file. 'symbols' (default): adds function/class/struct nodes.")
    context.add_argument("--frontend", choices=["auto", "regex", "tree_sitter"], default="auto",
                         help="Symbol extraction frontend for --depth symbols.")
    context.add_argument("--docs", action="store_true", default=True,
                         help="Extract document sections and concept nodes during auto-build (default: true).")
    context.add_argument("--no-docs", action="store_false", dest="docs",
                         help="Disable document section/concept extraction during auto-build.")
    context.add_argument("--history", action="store_true", default=False,
                         help="Link qualifying bug-fix commits to the files they touched during auto-build. "
                              "Opt-in; requires a git repo. Default: False.")
    context.add_argument("--generic-mentions", action="store_true", default=False,
                         help="Add weak references edges for files that mention another file's stem.")
    context.add_argument("--incremental", action="store_true", default=True,
                         help="Use hash-based incremental scanner during auto-build (default: true).")
    context.add_argument("--no-incremental", action="store_false", dest="incremental",
                         help="Disable incremental scanning during auto-build.")
    context.add_argument("--sync", choices=["none", "git"], default="none",
                         help="Before querying, refresh only stale Git-changed paths by comparing them with the manifest.")
    context.add_argument("--changed", "--changed-files", nargs="*", default=[], metavar="PATH", dest="changed",
                         help="Explicit edited/created paths to splice before querying.")
    context.add_argument("--deleted", "--deleted-files", nargs="*", default=[], metavar="PATH", dest="deleted",
                         help="Explicit deleted/renamed-away paths to remove before querying.")
    context.add_argument("--show-anchors", action="store_true")
    context.add_argument("--source-mode", choices=["auto", "off", "all"], default="auto")
    context.add_argument("--memory-scope", action="append", default=[])
    context.add_argument("--json", action="store_true", help="Emit one machine-readable refresh/query/validation envelope.")
    context.add_argument("--validate", action="store_true", help="Print the already-enforced packet validation receipt.")
    context.add_argument("--show-stats", action="store_true", help="Print graph load/build shape metrics to stderr.")
    context.set_defaults(func=cmd_context)

    snippets = sub.add_parser("snippets", help="Render bounded source excerpts for selected graph node IDs, labels, or paths.")
    snippets.add_argument("--graph", help="Graph JSON path. Auto-detected from .graphgraph if omitted.")
    snippets.add_argument("--starts", nargs="+", required=True, help="Node IDs, labels, or paths to load source for.")
    snippets.add_argument("--context-lines", type=int, default=4, help="Lines before/after symbol line. Default: 4.")
    snippets.add_argument("--max-lines", type=int, default=40, help="Maximum lines per excerpt. Default: 40.")
    snippets.set_defaults(func=cmd_snippets)

    status = sub.add_parser("status", help="Summarize graph validity, code/doc balance, package metadata, and optional runtime probes.")
    status.add_argument("--directory", "-d", help="Project root directory (default: cwd).")
    status.add_argument("--graph", help="Graph JSON path. Auto-detected from native .graphgraph if omitted.")
    status.add_argument("--probe", action="store_true", help="Run lightweight python -m/import probes with src-layout PYTHONPATH when needed.")
    status.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    status.set_defaults(func=cmd_status)

    validate = sub.add_parser("validate", help="Validate a rendered graph packet, or auto-detect saved graph JSON.")
    validate.add_argument("--packet", help="Rendered packet file, graph JSON file, or omitted to read stdin.")
    validate.set_defaults(func=cmd_validate)

    validate_graph = sub.add_parser("validate-graph", help="Validate a saved GraphGraph JSON graph file.")
    validate_graph.add_argument("path", nargs="?", help="Graph path (positional shorthand for --graph).")
    validate_graph.add_argument("--graph", help="Graph JSON path. Auto-detected from .graphgraph if omitted.")
    validate_graph.set_defaults(func=cmd_validate_graph)

    scan = sub.add_parser("scan", help="Scan a directory and build a graph from import relationships.")
    scan.add_argument("--directory", "-d", help="Root directory to scan (default: cwd).")
    scan.add_argument(
        "--output",
        "-o",
        help="Output graph path (default: reuse the single existing native graph; otherwise .graphgraph/graph.gg).",
    )
    scan.add_argument("--max-nodes", type=int, default=DEFAULT_SCAN_MAX_NODES, help=f"File collection cap (default: {DEFAULT_SCAN_MAX_NODES}); with --depth symbols, the symbol cap is 20x this value.")
    scan.add_argument("--generic-mentions", action="store_true", default=False,
                      help="Add weak 'references' edges for any file that mentions another file's stem name.")
    scan.add_argument("--skip-dirs", nargs="*", metavar="DIR",
                      help="Additional directory names to skip (e.g. --skip-dirs spikes test-inputs).")
    scan.add_argument("--exclude", nargs="*", metavar="DIR", dest="exclude_dirs",
                      help="Alias: extra directory names to exclude (same as --skip-dirs). "
                           "E.g. --exclude repos references_temp.")
    scan.add_argument("--include", nargs="*", metavar="DIR",
                      help="Directory names to keep even though a default skip rule would drop them "
                           "(e.g. a real project dir named 'build' or 'out'). E.g. --include build out.")
    scan.add_argument("--depth", choices=["files", "symbols"], default=None,
                      help="Scan depth. Reuses the existing graph setting when omitted; new graphs default to files.")
    scan.add_argument("--frontend", choices=["auto", "regex", "tree_sitter"], default=None,
                      help="Symbol frontend. Reuses the existing graph setting when omitted; new graphs default to auto.")
    scan.add_argument("--docs", action="store_true", default=None,
                      help="Extract document sections and concept nodes; reuses the existing graph setting when omitted.")
    scan.add_argument("--no-docs", action="store_false", dest="docs",
                      help="Disable document extraction even when the existing graph enabled it.")
    scan.add_argument("--history", action="store_true", default=None,
                      help="Link qualifying bug-fix commits (git log, regex-classified) to the files they "
                           "touched via a 'fixes' edge. Reuses the existing graph setting when omitted.")
    scan.add_argument("--no-history", action="store_false", dest="history",
                      help="Disable history extraction even when the existing graph enabled it.")
    scan.add_argument("--incremental", action="store_true", default=True, help="Use hash-based incremental scanner (default: True).")
    scan.add_argument("--no-incremental", action="store_false", dest="incremental", help="Disable incremental scanning.")
    scan.set_defaults(func=cmd_scan)

    update = sub.add_parser(
        "update",
        help="Re-extract exactly the given files and splice into the existing graph. "
             "No directory walk, no hashing of untouched files -- cost scales with "
             "--files, not repo size. Requires a prior 'scan'.",
    )
    update.add_argument("--files", nargs="+", required=True, metavar="PATH",
                        help="File(s) that changed (relative to --directory or absolute).")
    update.add_argument("--directory", "-d", help="Root directory (default: cwd).")
    update.add_argument("--output", "-o", help="Existing graph path to update (default: .graphgraph/graph.gg).")
    update.add_argument("--max-nodes", type=int, default=DEFAULT_SCAN_MAX_NODES, help=f"Max symbols per file batch (default: {DEFAULT_SCAN_MAX_NODES}).")
    update.add_argument("--depth", choices=["files", "symbols"], default="symbols")
    update.add_argument("--frontend", choices=["auto", "regex", "tree_sitter"], default="auto")
    update.add_argument("--docs", action="store_true", help="Extract document sections and concept nodes for doc files among --files.")
    update.add_argument("--history", action="store_true", default=False)
    update.set_defaults(func=cmd_update)

    remove = sub.add_parser(
        "remove",
        help="Drop the given files (deleted/renamed away) from the existing graph. "
             "No re-extraction, no directory walk. Requires a prior 'scan'.",
    )
    remove.add_argument("--files", nargs="+", required=True, metavar="PATH",
                        help="File(s) that no longer exist (relative to --directory or absolute).")
    remove.add_argument("--directory", "-d", help="Root directory (default: cwd).")
    remove.add_argument("--output", "-o", help="Existing graph path to update (default: .graphgraph/graph.gg).")
    remove.add_argument("--max-nodes", type=int, default=DEFAULT_SCAN_MAX_NODES)
    remove.add_argument("--depth", choices=["files", "symbols"], default="symbols")
    remove.add_argument("--frontend", choices=["auto", "regex", "tree_sitter"], default="auto")
    remove.add_argument("--docs", action="store_true")
    remove.add_argument("--history", action="store_true", default=False)
    remove.set_defaults(func=cmd_remove)

    ingest = sub.add_parser("ingest", help="Ingest any graph format (.gg, .ggb, .json, .csv, .tsv) into .graphgraph/graph.gg.")
    ingest.add_argument("--input", "-i", help="Input file (.gg, .json, .csv, .tsv). Auto-detected if omitted.")
    ingest.add_argument("--output", "-o", help="Output path (default: .graphgraph/graph.gg).")
    ingest.set_defaults(func=cmd_ingest)

    export = sub.add_parser("export", help="Export current graph to native binary .gg format.")
    export.add_argument("--graph", help="Source graph path. Auto-detected if omitted.")
    export.add_argument("--output", "-o", help="Output .gg path (default: same dir as source).")
    export.set_defaults(func=cmd_export)

    ontology = sub.add_parser("ontology", help="List native relation ontology and traversal weights.")
    ontology.add_argument("--family", help="Filter by relation family.")
    ontology.set_defaults(func=cmd_ontology)

    compare = sub.add_parser("compare", help="Compare two graph files by size, relation types, and overlap.")
    compare.add_argument("--left", required=True)
    compare.add_argument("--right", required=True)
    compare.set_defaults(func=cmd_compare)

    eval_cmd = sub.add_parser("eval", help="Evaluate retrieval recall and packet token cost against task expectations.")
    eval_cmd.add_argument("--graph", required=True)
    eval_cmd.add_argument("--tasks", required=True)
    eval_cmd.add_argument("--max-nodes", type=int)
    eval_cmd.set_defaults(func=cmd_eval)

    frontends = sub.add_parser("frontends", help="List extraction frontend capabilities.")
    frontends.set_defaults(func=cmd_frontends)

    traversal = sub.add_parser("traversal", help="List query-class traversal policies.")
    traversal.add_argument("--query-class")
    traversal.set_defaults(func=cmd_traversal)

    profile = sub.add_parser("profile", help="Measure graph shape and show dynamic budget candidates.")
    profile.add_argument("--graph", help="Graph path. Auto-detected from native .graphgraph if omitted.")
    profile.add_argument("--query", default="", help="Optional query text for doc/query budget heuristics.")
    profile.set_defaults(func=cmd_profile)

    doctor = sub.add_parser("doctor", help="Run local diagnostics for graph files, CLI runtime, dependencies, optional benchmark credentials, and MCP configs.")
    doctor.set_defaults(func=cmd_doctor)

    cache_cmd = sub.add_parser("cache", help="Inspect, clear, or rebuild query/ranking caches.")
    cache_cmd.add_argument("--graph", help="Graph path (used to locate cache file). Defaults to .graphgraph/.")
    cache_cmd.add_argument("--clear", action="store_true", help="Delete all cached entries.")
    cache_cmd.add_argument(
        "--recompute-centrality",
        action="store_true",
        help="Recompute PageRank from the current graph, persist it, and clear stale packet caches.",
    )
    cache_cmd.set_defaults(func=cmd_cache)

    install = sub.add_parser("install", help="Register/Install GraphGraph assistant skill, workspace rules, and MCP plugins.")
    install.add_argument("--project", "-p", action="store_true", help="Install locally to the current project repository (.agents/ directory) instead of user home.")
    install.add_argument(
        "--platform",
        choices=[
            "codex",
            "claude",
            "claude-code",
            "claude-desktop",
            "cursor",
            "gemini",
            "antigravity",
            "agy",
            "all",
        ],
        default="all",
        help=(
            "Target AI assistant platform(s) to register on. 'claude' covers both Claude Code "
            "(project .mcp.json + .claude/skills, or global ~/.claude skill + ~/.claude.json) and "
            "Claude Desktop (global). Use 'claude-code' or 'claude-desktop' to target one. "
            "gemini/antigravity/agy use the existing .gemini skill path."
        ),
    )
    install.set_defaults(func=cmd_install)

    add_platform_parser(sub)

    return parser
