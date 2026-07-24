"""CLI orchestration for graph scan, targeted update, and removal."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any, Callable

from ..io import GraphShrinkRefused, RemovalMatchedNothing, find_graph_path, load_any
from ..scanner import DEFAULT_SCAN_MAX_NODES
from ..services.lifecycle import (
    remove_paths_validated_graph,
    scan_validated_graph,
    update_paths_validated_graph,
)


def cmd_scan(args: argparse.Namespace) -> None:
    root = Path(args.directory) if args.directory else Path(".")
    existing_graph = None
    if args.output:
        output_path = Path(args.output)
    else:
        try:
            output_path = find_graph_path(root)
            existing_graph = load_any(output_path)
        except FileNotFoundError:
            output_path = root / ".graphgraph" / "graph.gg"
    if existing_graph is None and output_path.exists():
        existing_graph = load_any(output_path)
    existing_metadata = existing_graph.metadata if existing_graph is not None else {}
    depth = args.depth or existing_metadata.get("scan_depth", "files")
    frontend = args.frontend or existing_metadata.get("frontend", "auto")
    if frontend not in {"auto", "regex", "tree_sitter"}:
        frontend = "auto"
    docs = (
        str(existing_metadata.get("docs", "false")).casefold() == "true"
        if args.docs is None
        else args.docs
    )
    history = (
        str(existing_metadata.get("history", "false")).casefold() == "true"
        if args.history is None
        else args.history
    )
    skip_dirs: list[str] = list(args.skip_dirs or [])
    exclude_dirs: list[str] = list(getattr(args, "exclude_dirs", None) or [])
    all_skip = skip_dirs + [item for item in exclude_dirs if item not in skip_dirs]
    include_dirs: list[str] = list(getattr(args, "include", None) or [])
    started = time.monotonic()

    def report_progress(phase: str, detail: str) -> None:
        elapsed = time.monotonic() - started
        print(
            f"[graphgraph {elapsed:7.1f}s] {phase}: {detail}",
            file=sys.stderr,
            flush=True,
        )

    try:
        status = _run_scan(
            args,
            root,
            output_path,
            all_skip,
            include_dirs,
            depth,
            frontend,
            docs,
            history,
            report_progress,
        )
    except GraphShrinkRefused as exc:
        raise SystemExit(f"graphgraph scan: {exc}") from exc
    graph = status.graph
    validation = status.validation
    assert validation is not None

    total_nodes = len(graph.nodes)
    total_edges = len(graph.edges)
    kind_counts: dict[str, int] = {}
    for node in graph.nodes.values():
        kind_counts[node.kind] = kind_counts.get(node.kind, 0) + 1

    source_kinds = {
        "python", "typescript", "tsx", "javascript", "jsx", "go", "rust",
        "java", "csharp", "cpp", "c", "header", "ruby", "php", "swift",
        "kotlin", "scala", "haskell", "lean", "function", "class", "struct",
        "method", "interface",
    }
    doc_kinds = {"markdown", "rst", "html", "text", "concept", "section", "paragraph"}
    source_nodes = sum(value for kind, value in kind_counts.items() if kind in source_kinds)
    doc_nodes = sum(value for kind, value in kind_counts.items() if kind in doc_kinds)

    print(f"Scanned {total_nodes} nodes, {total_edges} edges  ->  {output_path}")
    print(
        f"  Structural validation: PASS {validation.format} "
        f"nodes={validation.node_count} edges={validation.edge_count}"
    )
    if status.repaired:
        print("  Repair       : incremental scan was invalid; promoted a clean full rebuild")
    print(
        f"  Source nodes : {source_nodes}  |  Doc nodes : {doc_nodes}  |  "
        f"Other : {total_nodes - source_nodes - doc_nodes}"
    )
    print(f"  Frontend     : {graph.metadata.get('frontend', 'files')}")
    if all_skip:
        print(f"  Excluded dirs: {', '.join(all_skip)}")
    if include_dirs:
        print(f"  Force-included: {', '.join(include_dirs)}")
    ignore_file_count = int(graph.metadata.get("ignore_rule_file_count", "0"))
    ignore_files = graph.metadata.get("ignore_rule_files", "")
    ignored_files = int(graph.metadata.get("ignored_by_rules", "0"))
    ignored_dirs = int(graph.metadata.get("ignore_pruned_dir_count", "0"))
    print(
        f"  Ignore rules : honored {ignore_file_count} file(s)"
        + (f" [{ignore_files}]" if ignore_files else " [none found]")
    )
    print(f"  Rule-excluded: {ignored_files} file(s), {ignored_dirs} directories pruned before descent")
    rule_pruned_sample = graph.metadata.get("ignore_pruned_dirs", "")
    if rule_pruned_sample:
        print(f"  Rule-pruned  : {rule_pruned_sample}")
    fallback_count = int(graph.metadata.get("frontend_fallback_count", "0"))
    if fallback_count:
        print(
            f"  Parse fallback: {fallback_count} file(s) used regex "
            f"(unsupported={graph.metadata.get('frontend_unsupported_count', '0')}, "
            f"timed_out={graph.metadata.get('frontend_timeout_count', '0')}, "
            f"parse_error={graph.metadata.get('frontend_parse_error_count', '0')})"
        )
        print(f"  Fallback files: {graph.metadata.get('frontend_fallback_files', '')}")
    if graph.metadata.get("frontend_grammar_errors"):
        print(f"  Grammar errors: {graph.metadata['frontend_grammar_errors']}")
    if graph.metadata.get("frontend_failures"):
        print(f"  Parse reasons : {graph.metadata['frontend_failures']}")
    if "member_calls_resolved" in graph.metadata:
        print(
            "  Member calls  : "
            f"resolved={graph.metadata.get('member_calls_resolved', '0')} "
            f"ambiguous={graph.metadata.get('member_calls_ambiguous', '0')} "
            f"unknown_receiver={graph.metadata.get('member_calls_unknown_receiver', '0')} "
            f"external_or_unmatched={graph.metadata.get('member_calls_unresolved', '0')} "
            f"scope={graph.metadata.get('member_call_telemetry_scope', 'unavailable')}"
        )
    if "docs_profile_ms" in graph.metadata:
        print(
            f"  Document phase: {float(graph.metadata['docs_profile_ms']):.1f} ms across "
            f"{graph.metadata.get('docs_profile_files', '0')} file(s); "
            f"truncated={graph.metadata.get('docs_truncated_count', '0')}"
        )
        if graph.metadata.get("docs_profile_slowest"):
            print(f"  Slowest docs  : {graph.metadata['docs_profile_slowest']}")
        if graph.metadata.get("docs_truncated_files"):
            print(f"  Truncated docs: {graph.metadata['docs_truncated_files']}")
    if "source_concepts_profile_ms" in graph.metadata:
        print(
            f"  Source concepts: {float(graph.metadata['source_concepts_profile_ms']):.1f} ms; "
            f"candidates={graph.metadata.get('source_concepts_candidates', '0')} "
            f"links={graph.metadata.get('source_concepts_links', '0')} "
            f"facts={graph.metadata.get('source_concepts_typed_fact_links', '0')} "
            f"aliases={graph.metadata.get('source_concepts_exact_alias_links', '0')}"
        )
    default_pruned_count = int(graph.metadata.get("default_pruned_dir_count", "0"))
    default_pruned_sample = graph.metadata.get("default_pruned_dirs", "")
    if default_pruned_count:
        print(
            f"  Default/explicit pruned: {default_pruned_count} directories"
            + (f" [{default_pruned_sample}]" if default_pruned_sample else "")
            + "  (--include only overrides a default skip name)"
        )
    top_kinds = sorted(kind_counts.items(), key=lambda item: -item[1])[:8]
    print("  Top kinds    : " + "  ".join(f"{kind}={count}" for kind, count in top_kinds))
    if source_nodes == 0:
        print()
        print("  !  WARNING: zero source nodes found. Possible causes:")
        print("     * All source files are inside excluded/skipped directories")
        print("     * The --directory flag points to the wrong root")
        print(
            "     * max_nodes cap hit before source files were reached "
            f"(try --max-nodes {DEFAULT_SCAN_MAX_NODES * 4})"
        )
        print()
        print("  Tip: run  graphgraph doctor  for a full environment check.")
    if graph.metadata.get("files_truncated") == "true":
        matched = graph.metadata.get("files_total_matched", "?")
        scanned = graph.metadata.get("files_scanned", str(total_nodes))
        print()
        print(
            f"  !  WARNING: this codebase has {matched} matching files, but only "
            f"{scanned} were scanned (--max-nodes cap). The remaining files were "
            "never read -- this graph is INCOMPLETE, not just small."
        )
        print(f"     Re-run with a higher --max-nodes (e.g. --max-nodes {matched}) for full coverage.")
    if graph.metadata.get("symbols_truncated") == "true":
        cap = graph.metadata.get("symbols_cap", "?")
        print()
        print(
            f"  !  WARNING: symbol extraction hit its cap ({cap} symbols). Some scanned "
            "files may have zero extracted functions/classes even though they were read -- "
            "this graph's call/reference edges are INCOMPLETE for a codebase this large."
        )
        print("     Re-run with a higher --max-nodes to raise the symbol cap proportionally.")


def _run_scan(
    args: argparse.Namespace,
    root: Path,
    output_path: Path,
    all_skip: list[str],
    include_dirs: list[str],
    depth: str,
    frontend: str,
    docs: bool,
    history: bool,
    report_progress: Callable[[str, str], None],
) -> Any:
    return scan_validated_graph(
        directory=root,
        output_path=output_path,
        max_nodes=args.max_nodes,
        generic_mentions=args.generic_mentions,
        skip_dirs=tuple(all_skip),
        include_dirs=tuple(include_dirs),
        depth=depth,
        frontend=frontend,
        docs=docs,
        history=history,
        incremental=args.incremental,
        force=getattr(args, "force", False),
        progress=report_progress,
    )


def cmd_update(args: argparse.Namespace) -> None:
    root = Path(args.directory) if args.directory else Path(".")
    output_path = Path(args.output) if args.output else Path(".graphgraph/graph.gg")
    existing_metadata: dict = {}
    if output_path.exists():
        try:
            existing_metadata = load_any(output_path).metadata or {}
        except Exception:  # noqa: BLE001 - a corrupt graph is handled downstream
            existing_metadata = {}
    docs = (
        str(existing_metadata.get("docs", "false")).casefold() == "true"
        if getattr(args, "docs", None) is None
        else args.docs
    )
    try:
        status = _run_update(args, root, output_path, docs)
    except GraphShrinkRefused as exc:
        raise SystemExit(f"graphgraph update: {exc}") from exc
    graph = status.graph
    validation = status.validation
    assert validation is not None
    print(
        f"Updated {len(args.files)} file(s), graph now {len(graph.nodes)} nodes, "
        f"{len(graph.edges)} edges  ->  {output_path}"
    )
    print(
        f"  Structural validation: PASS {validation.format} "
        f"nodes={validation.node_count} edges={validation.edge_count}"
    )
    if status.repaired:
        print(
            "  Repair       : no prior graph/manifest (or targeted update was invalid); "
            "promoted a clean full rebuild"
        )


def _run_update(
    args: argparse.Namespace,
    root: Path,
    output_path: Path,
    docs: bool,
) -> Any:
    return update_paths_validated_graph(
        directory=root,
        output_path=output_path,
        paths=args.files,
        max_nodes=args.max_nodes,
        depth=args.depth,
        frontend=args.frontend,
        docs=docs,
        history=args.history,
        force=getattr(args, "force", False),
    )


def cmd_remove(args: argparse.Namespace) -> None:
    root = Path(args.directory) if args.directory else Path(".")
    output_path = Path(args.output) if args.output else Path(".graphgraph/graph.gg")
    prior_nodes = None
    if output_path.exists():
        try:
            prior_nodes = len(load_any(output_path).nodes)
        except Exception:  # noqa: BLE001 - handled by the service layer
            prior_nodes = None
    try:
        status = remove_paths_validated_graph(
            directory=root,
            output_path=output_path,
            paths=args.files,
            max_nodes=args.max_nodes,
            depth=args.depth,
            frontend=args.frontend,
            docs=args.docs,
            history=args.history,
            force=getattr(args, "force", False),
        )
    except (GraphShrinkRefused, RemovalMatchedNothing) as exc:
        raise SystemExit(f"graphgraph remove: {exc}") from exc
    graph = status.graph
    validation = status.validation
    assert validation is not None
    dropped = "" if prior_nodes is None else f", dropped {prior_nodes - len(graph.nodes)} node(s)"
    print(
        f"Removed {len(args.files)} file(s){dropped}, graph now {len(graph.nodes)} nodes, "
        f"{len(graph.edges)} edges  ->  {output_path}"
    )
    print(
        f"  Structural validation: PASS {validation.format} "
        f"nodes={validation.node_count} edges={validation.edge_count}"
    )
    if status.repaired:
        print(
            "  Repair       : no prior graph/manifest (or removal was invalid); "
            "promoted a clean full rebuild"
        )
