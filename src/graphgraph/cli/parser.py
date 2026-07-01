import argparse

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
    cmd_render,
    cmd_scan,
    cmd_status,
    cmd_traversal,
    cmd_validate,
    cmd_validate_graph,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="graphgraph")
    sub = parser.add_subparsers(dest="cmd", required=True)

    plan = sub.add_parser("plan")
    plan.add_argument("--query-class", required=True)
    plan.add_argument("--query", default="")
    plan.set_defaults(func=cmd_plan)

    render = sub.add_parser("render")
    render.add_argument("--graph")
    render.add_argument("--query-class", required=True)
    render.add_argument("--starts", nargs="+", required=True)
    render.add_argument("--max-nodes", type=int, help="Expanded node budget. Default: measured by query class.")
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
    final.add_argument("--max-nodes", type=int, default=None, help="Expanded node budget. Default: measured by query class; stable skeleton uses 100.")
    final.add_argument("--packet", choices=["lowlevel", "sql", "hybrid", "semantic_arrow", "gg_max", "gg_max_hybrid", "gg_lex", "gg_lex_hybrid", "svo", "doc_summary"])
    final.set_defaults(func=cmd_final)

    query = sub.add_parser("query", help="Retrieve a query-specific graph context packet without preselecting node IDs.")
    query.add_argument("query", help="Natural-language query used to find graph anchors.")
    query.add_argument("--graph")
    query.add_argument("--query-class", default="blast_radius")
    query.add_argument("--packet", choices=["lowlevel", "sql", "hybrid", "semantic_arrow", "gg_max", "gg_max_hybrid", "gg_lex", "gg_lex_hybrid", "svo", "doc_summary"])
    query.add_argument("--hops", type=int)
    query.add_argument("--anchor-limit", type=int, help="Max anchor nodes before expansion. Default: adaptive by query class.")
    query.add_argument("--max-nodes", type=int, help="Expanded node budget. Default: measured by query class.")
    query.add_argument("--scope", action="append", default=[], help="Restrict retrieval to node scope/path prefix. Repeatable.")
    query.add_argument("--show-anchors", action="store_true")
    query.set_defaults(func=cmd_query)

    context = sub.add_parser("context", help="One-step native workflow: ensure a graph exists, then render query context.")
    context.add_argument("query", help="Natural-language query used to find graph anchors.")
    context.add_argument("--directory", "-d", help="Root directory to scan if a graph must be built (default: cwd).")
    context.add_argument("--graph", help="Graph JSON path to read/write (default: .graphgraph/graph.json).")
    context.add_argument("--rebuild", action="store_true", help="Force a graph rebuild before querying.")
    context.add_argument("--scan-max-nodes", type=int, default=2000, help="Max files/nodes collected during auto-build (default: 2000).")
    context.add_argument("--query-class", default="subsystem_summary")
    context.add_argument("--packet", choices=["lowlevel", "sql", "hybrid", "semantic_arrow", "gg_max", "gg_max_hybrid", "gg_lex", "gg_lex_hybrid", "svo", "doc_summary"])
    context.add_argument("--anchor-limit", type=int, help="Max anchor nodes before expansion. Default: adaptive by query class.")
    context.add_argument("--max-nodes", type=int, help="Expanded node budget. Default: measured by query class.")
    context.add_argument("--scope", action="append", default=[], help="Restrict retrieval to node scope/path prefix. Repeatable.")
    context.add_argument("--skip-dirs", nargs="*", metavar="DIR", help="Additional directory names to skip during auto-build.")
    context.add_argument("--exclude", nargs="*", metavar="DIR", dest="exclude_dirs", help="Alias: extra directory names to exclude during auto-build.")
    context.add_argument("--show-anchors", action="store_true")
    context.add_argument("--show-stats", action="store_true", help="Print graph load/build shape metrics to stderr.")
    context.set_defaults(func=cmd_context)

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
    validate_graph.add_argument("--graph", help="Graph JSON path. Auto-detected from .graphgraph if omitted.")
    validate_graph.set_defaults(func=cmd_validate_graph)

    scan = sub.add_parser("scan", help="Scan a directory and build a graph from import relationships.")
    scan.add_argument("--directory", "-d", help="Root directory to scan (default: cwd).")
    scan.add_argument("--output", "-o", help="Output graph JSON path (default: .graphgraph/graph.json).")
    scan.add_argument("--max-nodes", type=int, default=2000, help="Max nodes to collect (default: 2000).")
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
    scan.add_argument("--depth", choices=["files", "symbols"], default="files",
                      help="'files' (default): one node per file. 'symbols': adds function/class/struct nodes.")
    scan.add_argument("--frontend", choices=["auto", "regex", "tree_sitter"], default="auto",
                      help="Symbol extraction frontend for --depth symbols. auto prefers Tree-sitter when available.")
    scan.add_argument("--docs", action="store_true", help="Extract document sections and concept nodes.")
    scan.add_argument("--incremental", action="store_true", default=True, help="Use hash-based incremental scanner (default: True).")
    scan.add_argument("--no-incremental", action="store_false", dest="incremental", help="Disable incremental scanning.")
    scan.set_defaults(func=cmd_scan)

    ingest = sub.add_parser("ingest", help="Ingest any graph format (.gg, .json, .csv, .tsv) into .graphgraph/graph.json.")
    ingest.add_argument("--input", "-i", help="Input file (.gg, .json, .csv, .tsv). Auto-detected if omitted.")
    ingest.add_argument("--output", "-o", help="Output path (default: .graphgraph/graph.json).")
    ingest.set_defaults(func=cmd_ingest)

    export = sub.add_parser("export", help="Export current graph to native .gg adjacency-list format.")
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

    doctor = sub.add_parser("doctor", help="Run system diagnostics and verify environment, tools, credentials, and MCP configs.")
    doctor.set_defaults(func=cmd_doctor)

    cache_cmd = sub.add_parser("cache", help="Inspect or clear the topological KV packet cache.")
    cache_cmd.add_argument("--graph", help="Graph path (used to locate cache file). Defaults to .graphgraph/.")
    cache_cmd.add_argument("--clear", action="store_true", help="Delete all cached entries.")
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

    return parser
