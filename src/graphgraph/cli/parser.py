import argparse

# Every name below comes from `graphgraph.surface`, which imports nothing.
# Reading them from their defining modules loaded the packet renderers, the
# planner, the platform stack, and the scanner (and through it `pathspec` and
# `asyncio`) before argparse had seen a single argument. See `surface` for the
# drift test that keeps the copies honest.
from ..surface import (
    DEFAULT_SCAN_MAX_NODES,
    PACKET_FORMAT_NAMES,
    QUERY_CLASS_NAMES,
    REPRESENTATION_DEFAULT,
    REPRESENTATION_DESCRIPTION,
    REPRESENTATION_NAMES,
)

_SOURCE_MODE_HELP = (
    "Evidence-source mode: auto consumes only current indexes with a ready backend "
    "and never builds or initializes FastEmbed; off is structural-only; all "
    "explicitly permits semantic rebuild/warmup."
)


def _add_source_mode_argument(command) -> None:
    command.add_argument(
        "--source-mode",
        choices=("auto", "off", "all"),
        default="auto",
        help=_SOURCE_MODE_HELP,
    )


class _LazyVersionAction(argparse.Action):
    """Resolve the version only when `--version` is actually used.

    `version.package_version` defers `importlib.metadata` on purpose, but
    argparse's built-in `version` action wants the string at parser-build time,
    which called it on every single invocation. Reading installed package
    metadata pulls in `email`, `zipfile`, and `socket` -- about 43 ms in front
    of every command, to answer a question almost none of them ask.
    """

    def __call__(self, parser, namespace, values, option_string=None):
        from ..version import package_version

        parser.exit(message=f"{parser.prog} {package_version()}\n")


def _add_representation_arguments(command) -> None:
    # Wording is shared with `representation_schema`, so the CLI help and any
    # machine tool schema cannot drift into describing the policy differently.
    command.add_argument(
        "--representation",
        choices=REPRESENTATION_NAMES,
        default=REPRESENTATION_DEFAULT,
        help=f"{REPRESENTATION_DESCRIPTION} Experimental: not yet promoted by any tournament gate.",
    )
    command.add_argument(
        "--representation-budget",
        type=int,
        help="Proxy-token budget for --representation hybrid (default: 4096).",
    )


def _lazy_cmd(module: str, name: str):
    """Defer importing a command handler until its subcommand actually runs, so
    building the parser (and every unrelated command) does not pay for every
    handler's import chain -- e.g. a plain `query` no longer pulls the scanner or
    benchmarking stacks in via `diagnostics`."""

    def _run(args):
        import importlib

        handler = getattr(importlib.import_module(f".{module}", __package__), name)
        return handler(args)

    _run.__name__ = name
    return _run


def _add_plan_command(sub) -> None:
    plan = sub.add_parser("plan")
    plan.add_argument("--query-class", required=True, choices=QUERY_CLASS_NAMES)
    plan.add_argument("--query", default="")
    plan.set_defaults(func=_lazy_cmd("planning_commands", "cmd_plan"))


def _add_retrieval_commands(sub) -> None:
    render = sub.add_parser("render")
    render.add_argument("--graph")
    render.add_argument("--query-class", required=True, choices=QUERY_CLASS_NAMES)
    render.add_argument("--starts", nargs="+", required=True)
    render.add_argument(
        "--max-nodes", type=int, help="Expanded node budget. Default: dynamic by query class and graph shape."
    )
    render.set_defaults(func=_lazy_cmd("retrieval", "cmd_render"))

    final = sub.add_parser("final")
    final.add_argument("--graph")
    final.add_argument("--policies")
    final.add_argument("--query", default="")
    final.add_argument("--query-class", required=False, choices=("auto", *QUERY_CLASS_NAMES))
    final.add_argument("--starts", nargs="+", required=False)
    final.add_argument("--path", action="append", default=[])
    final.add_argument("--tag", action="append", default=[])
    final.add_argument(
        "--stable-skeleton",
        action="store_true",
        help="Compile a stable, PageRank-based skeleton of top architectural nodes to use as a static prompt cache prefix.",
    )
    final.add_argument(
        "--full-graph",
        action="store_true",
        help="Render every active node/edge with no query/budget -- an explicit escape hatch, not the default path. Refuses over --full-graph-max-tokens unless raised or disabled.",
    )
    final.add_argument(
        "--full-graph-max-tokens",
        type=int,
        default=20_000,
        help="Token guard for --full-graph (default: 20000). Pass 0 to disable.",
    )
    final.add_argument(
        "--max-nodes",
        type=int,
        default=None,
        help="Expanded node budget. Default: dynamic by query class and graph shape; stable skeleton uses 100.",
    )
    final.add_argument("--packet", choices=PACKET_FORMAT_NAMES)
    _add_representation_arguments(final)
    final.set_defaults(func=_lazy_cmd("retrieval", "cmd_final"))

    query = sub.add_parser(
        "query", help="Retrieve a query-specific graph context packet without preselecting node IDs."
    )
    query.add_argument("query", help="Natural-language query used to find graph anchors.")
    query.add_argument("--directory", "-d", help="Project root used for graph discovery (default: cwd).")
    query.add_argument("--graph")
    query.add_argument(
        "--operator",
        choices=("auto", "context", "relations", "select", "search", "status"),
        default="auto",
        help="Typed operator override; auto chooses the cheapest lossless read-only operator.",
    )
    query.add_argument("--target", default="", help="Explicit target for relations/search override.")
    query.add_argument("--direction", choices=("callers", "callees"))
    query.add_argument("--predicate", default="", help="Explicit typed predicate for select override.")
    query.add_argument(
        "--result-mode",
        choices=("select", "count", "exists"),
        default="select",
    )
    query.add_argument("--limit", type=int, default=20, help="Specialized operator result limit.")
    query.add_argument(
        "--sync",
        choices=("none", "git"),
        default="none",
        help="Optionally refresh Git-dirty paths before executing the query.",
    )
    query.add_argument(
        "--query-class",
        choices=("auto", *QUERY_CLASS_NAMES),
        default="auto",
        help="Routing policy (default: auto; explicit classes remain supported).",
    )
    query.add_argument("--packet", choices=PACKET_FORMAT_NAMES)
    _add_representation_arguments(query)
    query.add_argument("--hops", type=int)
    query.add_argument(
        "--anchor-limit", type=int, help="Max anchor nodes before expansion. Default: adaptive by query class."
    )
    query.add_argument(
        "--max-nodes", type=int, help="Expanded node budget. Default: dynamic by query class and graph shape."
    )
    query.add_argument(
        "--scope", action="append", default=[], help="Restrict retrieval to node scope/path prefix. Repeatable."
    )
    query.add_argument(
        "--scope-mode",
        choices=["strict", "expand"],
        default="strict",
        help="strict keeps every result in scope; expand permits structurally connected boundary crossings.",
    )
    query.add_argument("--show-anchors", action="store_true")
    _add_source_mode_argument(query)
    query.add_argument("--memory-scope", action="append", default=[])
    query.add_argument(
        "--show-stats",
        action="store_true",
        help="Print graph load shape metrics and the execution receipt (anchor route, gates) to stderr.",
    )
    query.add_argument(
        "--json",
        action="store_true",
        help="Emit the full envelope (packet, anchors, control receipt, retrieval metrics) as compact JSON instead of the bare packet.",
    )
    query.add_argument(
        "--pretty",
        action="store_true",
        help="Indent --json output for reading by eye. Costs ~26%% more tokens; omit for machine consumption.",
    )
    query.set_defaults(func=_lazy_cmd("retrieval", "cmd_query"))

    relations = sub.add_parser(
        "relations",
        help="Fast exact one-hop callers/callees as low-token tuple IR.",
    )
    relations.add_argument("target", help="Exact node id, symbol label, or path::symbol.")
    relations.add_argument("--direction", required=True, choices=["callers", "callees"])
    relations.add_argument("--graph", help="Graph path. Auto-detected if omitted.")
    relations.add_argument("--limit", type=int, default=20)
    relations.add_argument("--include-tests", action="store_true")
    relations.add_argument("--include-external", action="store_true")
    relations.add_argument(
        "--sync",
        choices=["none", "git"],
        default="none",
        help="Optionally refresh stale Git worktree paths before lookup; default keeps the lowest-latency unchecked path.",
    )
    relations.add_argument("--detailed", action="store_true", help="Emit explicit object rows and edge evidence.")
    relations.add_argument("--pretty", action="store_true", help="Indent JSON for human inspection.")
    relations.set_defaults(func=_lazy_cmd("retrieval", "cmd_relations"))

    context = sub.add_parser(
        "context", help="One-step native workflow: ensure a graph exists, then render query context."
    )
    context.add_argument("query", help="Natural-language query used to find graph anchors.")
    context.add_argument("--directory", "-d", help="Root directory to scan if a graph must be built (default: cwd).")
    context.add_argument("--graph", help="Graph path to read/write (default: .graphgraph/graph.gg).")
    context.add_argument("--rebuild", action="store_true", help="Force a graph rebuild before querying.")
    context.add_argument(
        "--scan-max-nodes",
        type=int,
        default=DEFAULT_SCAN_MAX_NODES,
        help=f"Auto-build file cap; symbol extraction has a separate proportional cap (default: {DEFAULT_SCAN_MAX_NODES} files).",
    )
    context.add_argument(
        "--query-class",
        choices=("auto", *QUERY_CLASS_NAMES),
        default="auto",
        help="Routing policy (default: auto; explicit classes remain supported).",
    )
    context.add_argument("--packet", choices=PACKET_FORMAT_NAMES)
    _add_representation_arguments(context)
    context.add_argument(
        "--anchor-limit", type=int, help="Max anchor nodes before expansion. Default: adaptive by query class."
    )
    context.add_argument(
        "--max-nodes", type=int, help="Expanded node budget. Default: dynamic by query class and graph shape."
    )
    context.add_argument(
        "--scope", action="append", default=[], help="Restrict retrieval to node scope/path prefix. Repeatable."
    )
    context.add_argument(
        "--scope-mode",
        choices=["strict", "expand"],
        default="strict",
        help="strict keeps every result in scope; expand permits structurally connected boundary crossings.",
    )
    context.add_argument(
        "--skip-dirs", nargs="*", metavar="DIR", help="Additional directory names to skip during auto-build."
    )
    context.add_argument(
        "--exclude",
        nargs="*",
        metavar="DIR",
        dest="exclude_dirs",
        help="Alias: extra directory names to exclude during auto-build.",
    )
    context.add_argument(
        "--include",
        nargs="*",
        metavar="DIR",
        help="Directory names to keep even though a default skip rule would drop them.",
    )
    context.add_argument(
        "--depth",
        choices=["files", "symbols"],
        default="symbols",
        help="'files': one node per file. 'symbols' (default): adds function/class/struct nodes.",
    )
    context.add_argument(
        "--frontend",
        choices=["auto", "regex", "tree_sitter"],
        default="auto",
        help="Symbol extraction frontend for --depth symbols.",
    )
    context.add_argument(
        "--docs",
        action="store_true",
        default=True,
        help="Extract document sections and concept nodes during auto-build (default: true).",
    )
    context.add_argument(
        "--no-docs",
        action="store_false",
        dest="docs",
        help="Disable document section/concept extraction during auto-build.",
    )
    context.add_argument(
        "--history",
        action="store_true",
        default=False,
        help="Link qualifying bug-fix commits to the files they touched during auto-build. "
        "Opt-in; requires a git repo. Default: False.",
    )
    context.add_argument(
        "--generic-mentions",
        action="store_true",
        default=False,
        help="Add weak references edges for files that mention another file's stem.",
    )
    context.add_argument(
        "--incremental",
        action="store_true",
        default=True,
        help="Use hash-based incremental scanner during auto-build (default: true).",
    )
    context.add_argument(
        "--no-incremental",
        action="store_false",
        dest="incremental",
        help="Disable incremental scanning during auto-build.",
    )
    context.add_argument(
        "--sync",
        choices=["none", "git"],
        default="none",
        help="Before querying, refresh only stale Git-changed paths by comparing them with the manifest.",
    )
    context.add_argument(
        "--changed",
        "--changed-files",
        nargs="*",
        default=[],
        metavar="PATH",
        dest="changed",
        help="Explicit edited/created paths to splice before querying.",
    )
    context.add_argument(
        "--deleted",
        "--deleted-files",
        nargs="*",
        default=[],
        metavar="PATH",
        dest="deleted",
        help="Explicit deleted/renamed-away paths to remove before querying.",
    )
    context.add_argument("--show-anchors", action="store_true")
    _add_source_mode_argument(context)
    context.add_argument("--memory-scope", action="append", default=[])
    context.add_argument(
        "--json",
        action="store_true",
        help="Emit compact actionable refresh/query/validation JSON.",
    )
    context.add_argument(
        "--details",
        action="store_true",
        help="With --json, include the full packet, anchors, and provenance-heavy retrieval receipt.",
    )
    context.add_argument(
        "--validate", action="store_true", help="Print the already-enforced packet validation receipt."
    )
    context.add_argument("--show-stats", action="store_true", help="Print graph load/build shape metrics to stderr.")
    context.set_defaults(func=_lazy_cmd("retrieval", "cmd_context"))

    snippets = sub.add_parser(
        "snippets", help="Render bounded source excerpts for selected graph node IDs, labels, or paths."
    )
    snippets.add_argument("--graph", help="Graph JSON path. Auto-detected from .graphgraph if omitted.")
    snippets.add_argument("--starts", nargs="+", required=True, help="Node IDs, labels, or paths to load source for.")
    snippets.add_argument("--context-lines", type=int, default=4, help="Lines before/after symbol line. Default: 4.")
    snippets.add_argument("--max-lines", type=int, default=40, help="Maximum lines per excerpt. Default: 40.")
    snippets.set_defaults(func=_lazy_cmd("retrieval", "cmd_snippets"))


def _add_status_command(sub) -> None:
    orient = sub.add_parser(
        "orient",
        help="Build a source-grounded project atlas: system card, subsystems, coupling, tests, and coverage receipts.",
    )
    orient.add_argument("--directory", "-d", help="Project root directory (default: cwd).")
    orient.add_argument("--graph", help="Graph path. Auto-detected from native .graphgraph if omitted.")
    orient.add_argument("--max-subsystems", type=int, help="Optional hard cap; default is budget-selected.")
    orient.add_argument("--representatives", type=int, default=1, help="Grounded API representatives per subsystem.")
    orient.add_argument("--max-couplings", type=int, help="Optional hard cap; default is budget-selected.")
    orient.add_argument(
        "--evidence-budget-chars",
        type=int,
        default=8000,
        help="Exact serialized evidence-view budget used by dynamic coverage selection (default: 8000).",
    )
    orient.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    orient.add_argument("--pretty", action="store_true", help="Indent --json output for human inspection.")
    orient.set_defaults(func=_lazy_cmd("diagnostics", "cmd_orient"))

    status = sub.add_parser(
        "status", help="Summarize graph validity, code/doc balance, package metadata, and optional runtime probes."
    )
    status.add_argument("--directory", "-d", help="Project root directory (default: cwd).")
    status.add_argument("--graph", help="Graph JSON path. Auto-detected from native .graphgraph if omitted.")
    status.add_argument(
        "--probe",
        action="store_true",
        help="Run lightweight python -m/import probes with src-layout PYTHONPATH when needed.",
    )
    status.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    status.set_defaults(func=_lazy_cmd("diagnostics", "cmd_status"))


def _add_graph_validation_commands(sub) -> None:
    validate = sub.add_parser("validate", help="Validate a rendered graph packet; empty input fails closed.")
    validate.add_argument("--packet", help="Rendered packet file, graph JSON file, or omitted to read stdin.")
    validate.set_defaults(func=_lazy_cmd("graph_io", "cmd_validate"))

    validate_graph = sub.add_parser("validate-graph", help="Validate a saved GraphGraph JSON graph file.")
    validate_graph.add_argument("path", nargs="?", help="Graph path (positional shorthand for --graph).")
    validate_graph.add_argument("--graph", help="Graph JSON path. Auto-detected from .graphgraph if omitted.")
    validate_graph.set_defaults(func=_lazy_cmd("graph_io", "cmd_validate_graph"))


def _add_lifecycle_commands(sub) -> None:
    scan = sub.add_parser("scan", help="Scan a directory and build a graph from import relationships.")
    scan.add_argument("--directory", "-d", help="Root directory to scan (default: cwd).")
    scan.add_argument(
        "--output",
        "-o",
        help="Output graph path (default: reuse the single existing native graph; otherwise .graphgraph/graph.gg).",
    )
    scan.add_argument(
        "--max-nodes",
        type=int,
        default=DEFAULT_SCAN_MAX_NODES,
        help=f"File collection cap (default: {DEFAULT_SCAN_MAX_NODES}); with --depth symbols, the symbol cap is 20x this value.",
    )
    scan.add_argument(
        "--generic-mentions",
        action="store_true",
        default=False,
        help="Add weak 'references' edges for any file that mentions another file's stem name.",
    )
    scan.add_argument(
        "--skip-dirs",
        nargs="*",
        metavar="DIR",
        help="Additional directory names to skip (e.g. --skip-dirs spikes test-inputs).",
    )
    scan.add_argument(
        "--exclude",
        nargs="*",
        metavar="DIR",
        dest="exclude_dirs",
        help="Alias: extra directory names to exclude (same as --skip-dirs). E.g. --exclude repos references_temp.",
    )
    scan.add_argument(
        "--include",
        nargs="*",
        metavar="DIR",
        help="Directory names to keep even though a default skip rule would drop them "
        "(e.g. a real project dir named 'build' or 'out'). E.g. --include build out.",
    )
    scan.add_argument(
        "--depth",
        choices=["files", "symbols"],
        default=None,
        help="Scan depth. Reuses the existing graph setting when omitted; new graphs default to files.",
    )
    scan.add_argument(
        "--frontend",
        choices=["auto", "regex", "tree_sitter"],
        default=None,
        help="Symbol frontend. Reuses the existing graph setting when omitted; new graphs default to auto.",
    )
    scan.add_argument(
        "--docs",
        action="store_true",
        default=None,
        help="Extract document sections and concept nodes; reuses the existing graph setting when omitted.",
    )
    scan.add_argument(
        "--no-docs",
        action="store_false",
        dest="docs",
        help="Disable document extraction even when the existing graph enabled it.",
    )
    scan.add_argument(
        "--history",
        action="store_true",
        default=None,
        help="Link qualifying bug-fix commits (git log, regex-classified) to the files they "
        "touched via a 'fixes' edge. Reuses the existing graph setting when omitted.",
    )
    scan.add_argument(
        "--no-history",
        action="store_false",
        dest="history",
        help="Disable history extraction even when the existing graph enabled it.",
    )
    scan.add_argument(
        "--force",
        action="store_true",
        default=False,
        help="Allow a scan that discards more than half the existing graph at --output. Without it, such a write is refused as probable data loss (usually a wrong --directory).",
    )
    scan.add_argument(
        "--incremental", action="store_true", default=True, help="Use hash-based incremental scanner (default: True)."
    )
    scan.add_argument(
        "--no-incremental", action="store_false", dest="incremental", help="Disable incremental scanning."
    )
    scan.set_defaults(func=_lazy_cmd("lifecycle", "cmd_scan"))

    update = sub.add_parser(
        "update",
        help="Re-extract exactly the given files and splice into the existing graph. "
        "No directory walk, no hashing of untouched files -- cost scales with "
        "--files, not repo size. Requires a prior 'scan'.",
    )
    update.add_argument(
        "--files",
        nargs="+",
        required=True,
        metavar="PATH",
        help="File(s) that changed (relative to --directory or absolute).",
    )
    update.add_argument("--directory", "-d", help="Root directory (default: cwd).")
    update.add_argument("--output", "-o", help="Existing graph path to update (default: .graphgraph/graph.gg).")
    update.add_argument(
        "--max-nodes",
        type=int,
        default=DEFAULT_SCAN_MAX_NODES,
        help=f"Max symbols per file batch (default: {DEFAULT_SCAN_MAX_NODES}).",
    )
    update.add_argument("--depth", choices=["files", "symbols"], default="symbols")
    update.add_argument("--frontend", choices=["auto", "regex", "tree_sitter"], default="auto")
    update.add_argument(
        "--docs",
        action="store_true",
        default=None,
        help="Extract document sections and concept nodes for doc files among --files. Reuses the existing graph setting when omitted.",
    )
    update.add_argument(
        "--no-docs", action="store_false", dest="docs", help="Disable document extraction for this splice."
    )
    update.add_argument(
        "--force",
        action="store_true",
        default=False,
        help="Allow a rebuild that discards more than half the existing graph. Without it, such a write is refused as probable data loss.",
    )
    update.add_argument("--history", action="store_true", default=False)
    update.set_defaults(func=_lazy_cmd("lifecycle", "cmd_update"))

    remove = sub.add_parser(
        "remove",
        help="Drop the given files (deleted/renamed away) from the existing graph. "
        "No re-extraction, no directory walk. Requires a prior 'scan'.",
    )
    remove.add_argument(
        "--files",
        nargs="+",
        required=True,
        metavar="PATH",
        help="File(s) that no longer exist (relative to --directory or absolute).",
    )
    remove.add_argument("--directory", "-d", help="Root directory (default: cwd).")
    remove.add_argument("--output", "-o", help="Existing graph path to update (default: .graphgraph/graph.gg).")
    remove.add_argument("--max-nodes", type=int, default=DEFAULT_SCAN_MAX_NODES)
    remove.add_argument("--depth", choices=["files", "symbols"], default="symbols")
    remove.add_argument("--frontend", choices=["auto", "regex", "tree_sitter"], default="auto")
    remove.add_argument("--docs", action="store_true")
    remove.add_argument(
        "--force",
        action="store_true",
        default=False,
        help="Allow a rebuild that discards more than half the existing graph. Without it, such a write is refused as probable data loss.",
    )
    remove.add_argument("--history", action="store_true", default=False)
    remove.set_defaults(func=_lazy_cmd("lifecycle", "cmd_remove"))


def _add_graph_io_commands(sub) -> None:
    ingest = sub.add_parser(
        "ingest",
        help=(
            "Migrate or ingest .gg, legacy .ggb, JSON, CSV, or TSV into the single native .graphgraph/graph.gg store."
        ),
    )
    ingest.add_argument(
        "--input",
        "-i",
        help="Explicit input file (.gg, .ggb, .json, .csv, .tsv).",
    )
    ingest.add_argument("--output", "-o", help="Output path (default: .graphgraph/graph.gg).")
    ingest.set_defaults(func=_lazy_cmd("graph_io", "cmd_ingest"))

    export = sub.add_parser("export", help="Export current graph to native binary .gg format.")
    export.add_argument("--graph", help="Source graph path. Auto-detected if omitted.")
    export.add_argument("--output", "-o", help="Output .gg path (default: same dir as source).")
    export.set_defaults(func=_lazy_cmd("graph_io", "cmd_export"))


def _add_ontology_command(sub) -> None:
    ontology = sub.add_parser("ontology", help="List native relation ontology and traversal weights.")
    ontology.add_argument("--family", help="Filter by relation family.")
    ontology.set_defaults(func=_lazy_cmd("descriptions", "cmd_ontology"))


def _add_compare_command(sub) -> None:
    compare = sub.add_parser("compare", help="Compare two graph files by size, relation types, and overlap.")
    compare.add_argument("--left", required=True)
    compare.add_argument("--right", required=True)
    compare.set_defaults(func=_lazy_cmd("graph_io", "cmd_compare"))


def _add_eval_command(sub) -> None:
    navigation = sub.add_parser(
        "navigation-eval",
        help="Score rg/source-read, GraphGraph, or hybrid navigation traces under equal line/action/token/time budgets.",
    )
    navigation.add_argument("--tasks", required=True, help="Frozen task/qrel JSON.")
    navigation.add_argument("--runs", required=True, help="Recorded strategy trace JSON.")
    navigation.add_argument("--profile", help="Optional explicit navigation-loss weight profile JSON.")
    navigation.add_argument("--pretty", action="store_true")
    navigation.set_defaults(func=_lazy_cmd("evaluation", "cmd_navigation_eval"))

    eval_cmd = sub.add_parser("eval", help="Evaluate retrieval recall and packet token cost against task expectations.")
    eval_cmd.add_argument("--graph", required=True)
    eval_cmd.add_argument("--tasks", required=True)
    eval_cmd.add_argument("--max-nodes", type=int)
    _add_source_mode_argument(eval_cmd)
    eval_cmd.add_argument(
        "--calibration",
        action="store_true",
        help="Include a calibration receipt pairing answerability confidence with labeled task recall.",
    )
    eval_cmd.add_argument(
        "--calibration-bins",
        type=int,
        default=10,
        help="Equal-width reliability bins used with --calibration (default: 10).",
    )
    eval_cmd.add_argument(
        "--complete-recall",
        type=float,
        default=1.0,
        help="Minimum recall in every declared dimension for a complete answer (default: 1.0).",
    )
    eval_cmd.add_argument(
        "--report",
        action="store_true",
        help="Emit results plus overall and per-class/split/stratum metrics.",
    )
    eval_cmd.add_argument(
        "--abstain-threshold",
        type=float,
        default=0.5,
        help="Confidence below which stratified reporting treats a result as abstained (default: 0.5).",
    )
    eval_cmd.add_argument(
        "--baseline-results",
        help="Saved result JSON to compare with the current run by stable task id.",
    )
    eval_cmd.add_argument(
        "--compare-metric",
        choices=("node_recall", "edge_recall", "mrr", "ndcg_at_5", "ndcg_at_10", "facet_completeness"),
        default="ndcg_at_10",
    )
    eval_cmd.add_argument("--minimum-effect", type=float, default=0.02)
    eval_cmd.add_argument("--bootstrap-samples", type=int, default=10_000)
    eval_cmd.add_argument("--bootstrap-seed", type=int, default=1337)
    eval_cmd.set_defaults(func=_lazy_cmd("evaluation", "cmd_eval"))


def _add_description_commands(sub) -> None:
    frontends = sub.add_parser("frontends", help="List extraction frontend capabilities.")
    frontends.set_defaults(func=_lazy_cmd("descriptions", "cmd_frontends"))

    traversal = sub.add_parser("traversal", help="List query-class traversal policies.")
    traversal.add_argument("--query-class")
    traversal.set_defaults(func=_lazy_cmd("descriptions", "cmd_traversal"))


def _add_analysis_commands(sub) -> None:
    profile = sub.add_parser("profile", help="Measure graph shape and show dynamic budget candidates.")
    profile.add_argument("--graph", help="Graph path. Auto-detected from native .graphgraph if omitted.")
    profile.add_argument("--query", default="", help="Optional query text for doc/query budget heuristics.")
    profile.set_defaults(func=_lazy_cmd("planning_commands", "cmd_profile"))

    select = sub.add_parser(
        "select",
        help="Answer a whole-graph set predicate (e.g. symbols with no production caller).",
    )
    select.add_argument(
        "predicate",
        help=(
            "Filter clauses joined by 'and', e.g. "
            '"production_callers = 0 and crate contains locus-engine and include_tests = false". '
            "Supported: production_callers/callers with = != > >= < <= (e.g. 'callers > 5'), kind=K, path|crate contains S, path|crate != S, label contains S, label in [a, b, c] for batch lookup, include_tests=BOOL."
        ),
    )
    select.add_argument("--graph", help="Graph path. Auto-detected from native .graphgraph if omitted.")
    select.add_argument(
        "--mode",
        choices=["select", "count", "exists"],
        default="select",
        help="select lists symbols; count returns an integer; exists returns a boolean. Default: select.",
    )
    select.add_argument("--limit", type=int, default=200, help="Max symbols listed in select mode. Default: 200.")
    select.add_argument("--json", action="store_true", help="Emit compact JSON instead of text.")
    select.add_argument(
        "--pretty",
        action="store_true",
        help="Indent --json output for reading by eye. Costs ~26%% more tokens; omit for machine consumption.",
    )
    select.set_defaults(func=_lazy_cmd("planning_commands", "cmd_select"))


def _add_doctor_command(sub) -> None:
    doctor = sub.add_parser(
        "doctor",
        help="Run local diagnostics for graph files, CLI runtime, dependencies, optional benchmark credentials, and MCP configs.",
    )
    doctor.set_defaults(func=_lazy_cmd("diagnostics", "cmd_doctor"))


def _add_cache_command(sub) -> None:
    cache_cmd = sub.add_parser("cache", help="Inspect, clear, or rebuild query/ranking caches.")
    cache_cmd.add_argument("--graph", help="Graph path (used to locate cache file). Defaults to .graphgraph/.")
    cache_cmd.add_argument("--clear", action="store_true", help="Delete all cached entries.")
    cache_cmd.add_argument(
        "--recompute-centrality",
        action="store_true",
        help="Recompute PageRank from the current graph, persist it, and clear stale packet caches.",
    )
    cache_cmd.set_defaults(func=_lazy_cmd("cache", "cmd_cache"))


def _add_maintenance_commands(sub) -> None:
    artifacts = sub.add_parser(
        "artifacts",
        help="Synchronize or check tracked skill, plugin, and MCP distribution artifacts.",
    )
    artifacts.add_argument(
        "--check", action="store_true", help="Fail if any generated artifact differs from its canonical source."
    )
    artifacts.add_argument("--root", default=".", help="Repository root containing .agents and plugins (default: cwd).")
    artifacts.set_defaults(func=_lazy_cmd("install", "cmd_artifacts"))

    install = sub.add_parser(
        "install", help="Register/Install GraphGraph assistant skill, workspace rules, and MCP plugins."
    )
    install.add_argument(
        "--project",
        "-p",
        action="store_true",
        help="Install locally to the current project repository (.agents/ directory) instead of user home.",
    )
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
    install.set_defaults(func=_lazy_cmd("install", "cmd_install"))


def build_parser() -> argparse.ArgumentParser:
    """Assemble the top-level CLI parser.

    Each subcommand family is registered by a focused ``_add_*`` helper; the call
    order below is the subcommand order shown in ``--help`` and is preserved
    verbatim from when this was one flat function.
    """
    parser = argparse.ArgumentParser(prog="graphgraph")
    parser.add_argument(
        "--version",
        action=_LazyVersionAction,
        nargs=0,
        help="Show the installed graphgraph version and exit.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    _add_plan_command(sub)
    _add_retrieval_commands(sub)
    _add_status_command(sub)
    _add_graph_validation_commands(sub)
    _add_lifecycle_commands(sub)
    _add_graph_io_commands(sub)
    _add_ontology_command(sub)
    _add_compare_command(sub)
    _add_eval_command(sub)
    _add_description_commands(sub)
    _add_analysis_commands(sub)
    _add_doctor_command(sub)
    _add_cache_command(sub)
    _add_maintenance_commands(sub)
    # `cli.platform` reaches the io and platform stacks at module scope, so it is
    # imported here rather than at module scope: every other subcommand, and
    # bare `--help`, would otherwise pay for the whole platform surface.
    from .platform import add_platform_parser

    add_platform_parser(sub)

    return parser
