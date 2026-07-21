from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from ..analysis.eval import evaluate_graph, load_eval_tasks, results_to_json
from ..analysis.metrics import compare_graphs
from ..graph.ontology import DEFAULT_RELATIONS
from ..graph.traversal import POLICIES, traversal_policy
from ..io import (
    find_graph_path,
    find_policies_path,
    load_any,
    project_root_for_graph,
    save_gg,
    save_validated_graph,
    validate_graph_file,
)
from ..packets import render_packet
from ..packets.validation import validate_any
from ..planning import (
    compute_subgraph_stats,
    plan_context,
    profile_graph_shape,
    recommend_node_budget,
    refine_plan_for_subgraph,
)
from ..retrieval import apply_shape_budget
from ..runtime.cache import TopologicalKVCache, compute_cache_key
from ..scanner import DEFAULT_SCAN_MAX_NODES
from ..scanner.frontends import available_frontends
from ..services import (
    FullGraphTooLargeError,
    render_final_packet,
    render_full_graph,
    render_query_context,
    render_source_snippets,
    render_stable_skeleton,
)
from ..services.context import resolve_start_nodes
from ..services.native import (
    build_project_status,
    graph_shape,
    inspect_saved_graph_freshness,
    remove_paths_validated_graph,
    render_native_context,
    scan_validated_graph,
    update_paths_validated_graph,
)
from .install import cmd_install as cmd_install


def _installed_skill_artifact_status(home: Path) -> tuple[dict[str, object], ...]:
    """Compare published Codex skill files with this package's canonical assets."""
    assets = Path(__file__).resolve().parents[1] / "assets"
    skill_root = home / ".codex" / "skills" / "graphgraph"
    artifacts = (
        ("skill contract", skill_root / "SKILL.md", assets / "graphgraph_skill.md"),
        (
            "live validator",
            skill_root / "scripts" / "validate_live.py",
            assets / "validate_live.py",
        ),
    )
    status: list[dict[str, object]] = []
    for label, installed, canonical in artifacts:
        state = (
            "missing"
            if not installed.is_file()
            else "current"
            # Path.write_text uses the platform newline convention. Compare
            # decoded content so an LF asset installed as CRLF on Windows is
            # not misreported as stale.
            if installed.read_text(encoding="utf-8")
            == canonical.read_text(encoding="utf-8")
            else "stale"
        )
        status.append({
            "label": label,
            "path": installed,
            "state": state,
        })
    return tuple(status)


def cmd_plan(args: argparse.Namespace) -> None:
    plan = plan_context(args.query_class, getattr(args, "query", ""))
    print(
        f"{plan.hops}hop {plan.direction} {plan.packet} "
        f"n={plan.node_budget} anchors={plan.anchor_limit}: {plan.reason}"
    )


def cmd_select(args: argparse.Namespace) -> None:
    from ..retrieval.predicates import parse_criteria, select_symbols

    graph_path = Path(args.graph) if args.graph else find_graph_path()
    graph = load_any(graph_path)
    try:
        criteria = parse_criteria(args.predicate, limit=args.limit)
    except ValueError as exc:
        raise SystemExit(f"graphgraph select: {exc}") from exc
    result = select_symbols(graph, criteria, mode=args.mode)

    if args.json:
        print(json.dumps({
            "mode": result.mode,
            "total": result.total,
            "exists": result.exists,
            "truncated": result.truncated,
            "criteria": result.criteria_detail,
            "caller_evidence": result.caller_evidence,
            "caller_evidence_complete": result.caller_evidence_complete,
            "symbols": result.symbols,
        }, indent=2))
        return

    if args.mode == "exists":
        print("yes" if result.exists else "no")
    elif args.mode == "count":
        print(result.total)
    else:
        for symbol in result.symbols:
            location = f"{symbol['path']}:{symbol['line']}" if symbol["line"] else symbol["path"]
            marker = " [test]" if symbol["is_test"] else ""
            print(
                f"{symbol['label']}  ({symbol['kind']}) {location}"
                f"  callers={symbol['callers']} production={symbol['production_callers']}{marker}"
            )
        print(f"-- {result.total} match(es){', truncated' if result.truncated else ''}")

    print(f"-- where {result.criteria_detail}")
    if not result.caller_evidence_complete:
        # A zero-caller answer is only as strong as call resolution, and this
        # surface exists precisely to stop people publishing wrong counts.
        print(f"-- CAVEAT: {result.caller_evidence}")


def cmd_profile(args: argparse.Namespace) -> None:
    graph_path = Path(args.graph) if args.graph else find_graph_path()
    graph = load_any(graph_path)
    shape = profile_graph_shape(graph)
    query = getattr(args, "query", "")
    report = {
        "graph": str(graph_path),
        "shape": shape.__dict__,
        "frontend_quality": {
            "member_calls": {
                "resolved": int(graph.metadata.get("member_calls_resolved", "0")),
                "ambiguous": int(graph.metadata.get("member_calls_ambiguous", "0")),
                "unresolved": int(graph.metadata.get("member_calls_unresolved", "0")),
                "scope": graph.metadata.get("member_call_telemetry_scope", "unavailable"),
            },
            "fallback_files": int(graph.metadata.get("frontend_fallback_count", "0")),
            "failed_files": int(graph.metadata.get("frontend_failure_count", "0")),
        },
        "budget_candidates": [
            recommend_node_budget(query_class, query, shape).__dict__
            for query_class in (
                "direct_lookup",
                "reverse_lookup",
                "multi_hop_path",
                "blast_radius",
                "subsystem_summary",
                "negative_query",
            )
        ],
    }
    print(json.dumps(report, indent=2))


def cmd_doctor(args: argparse.Namespace) -> None:
    import os
    import platform
    import sys
    from pathlib import Path

    from ..version import package_version
    
    print("GraphGraph Doctor - System Diagnostic Utility")
    print("=============================================")
    print(f"Version: {package_version()}")
    
    # 1. Environment and Python Checks
    print("\n[Environment]")
    print(f"  Python Version: {sys.version.split()[0]} ({'OK' if sys.version_info >= (3, 10) else 'FAIL (>=3.10 required)'})")
    print(f"  Platform: {platform.system()} {platform.release()}")
    in_venv = sys.prefix != sys.base_prefix or 'VIRTUAL_ENV' in os.environ
    print(f"  Virtual Environment Active: {in_venv}")
    
    # 2. Package Dependency Checks
    print("\n[Dependencies]")
    try:
        import tree_sitter  # noqa: F401
        import tree_sitter_language_pack  # noqa: F401
        print("  tree-sitter: Installed (OK)")
        capability = next(cap for cap in available_frontends() if cap.name == "tree_sitter")
        print(f"  Tree-sitter grammars ready: {', '.join(capability.ready_languages) or 'none'}")
        if capability.unavailable_languages:
            print(
                "  Tree-sitter grammars unavailable: "
                + ", ".join(capability.unavailable_languages)
            )
    except ImportError:
        print("  tree-sitter: Missing (WARN - AST symbols scanning disabled)")

    try:
        import keyring
        print("  keyring: Installed (OK - optional external benchmark credential storage available)")
    except ImportError:
        print("  keyring: Missing (OK - only needed for optional external benchmark credentials)")

    try:
        import tiktoken  # noqa: F401
        print("  tiktoken: Installed (OK)")
    except ImportError:
        print("  tiktoken: Missing (WARN - using approximate token count)")

    # The skill is an executable public contract. A current package with a
    # stale user-level wrapper silently exercises old behavior, so report the
    # two artifacts independently and provide one deterministic repair.
    print("\n[Installed Skill Artifacts]")
    artifact_status = _installed_skill_artifact_status(Path.home())
    for artifact in artifact_status:
        state = str(artifact["state"])
        display = "Current (OK)" if state == "current" else state.upper()
        print(f"  Codex {artifact['label']}: {display}  [{artifact['path']}]")
    if any(artifact["state"] != "current" for artifact in artifact_status):
        print("  Repair: graphgraph install --platform codex")

    # 3. Optional provider credentials. GraphGraph's local skill/MCP/CLI
    # workflow does not need these; they only matter for paid external model
    # benchmark scripts.
    print("\n[Optional External Benchmark Credentials]")
    print("  Local GraphGraph scan/query/packet workflows do not require provider API keys.")
    try:
        import keyring
        openai_key = keyring.get_password("OpenAI", "API_KEY")
        if openai_key:
            masked = openai_key[:7] + "..." + openai_key[-4:] if len(openai_key) > 10 else "..."
            print(f"  OpenAI API Key: Found for optional benchmarks ({masked})")
        else:
            env_key = os.environ.get("OPENAI_API_KEY")
            if env_key:
                masked = env_key[:7] + "..." + env_key[-4:] if len(env_key) > 10 else "..."
                print(f"  OpenAI API Key: Found in environment for optional benchmarks ({masked})")
            else:
                print("  OpenAI API Key: Not configured (OK; external OpenAI benchmarks will be skipped)")
                
        gemini_key = keyring.get_password("Gemini", "API_KEY")
        if gemini_key:
            masked = gemini_key[:7] + "..." + gemini_key[-4:] if len(gemini_key) > 10 else "..."
            print(f"  Gemini API Key: Found for optional benchmarks ({masked})")
        else:
            env_key = os.environ.get("GEMINI_API_KEY")
            if env_key:
                masked = env_key[:7] + "..." + env_key[-4:] if len(env_key) > 10 else "..."
                print(f"  Gemini API Key: Found in environment for optional benchmarks ({masked})")
            else:
                print("  Gemini API Key: Not configured (OK; external Gemini benchmarks will be skipped)")
    except Exception as e:
        print(f"  Credential lookup skipped/failed (OK for local GraphGraph use): {e}")
        
    # 4. Local Graph File Checks
    print("\n[Graph Files]")
    try:
        graph_path = find_graph_path()
        print(f"  Active Graph: Found at {graph_path}")
        try:
            graph = load_any(graph_path)
            nodes = list(graph.nodes.values())
            edges = graph.edges
            print(f"    - Nodes: {len(nodes)}  |  Edges: {len(edges)}")
            has_symbols = any(n.kind in ("function", "class", "struct", "method") for n in nodes)
            print(f"    - Symbol-level scanner info: {'Yes (OK)' if has_symbols else 'No (Files only)'}")

            # Kind breakdown
            kind_counts: dict[str, int] = {}
            for n in nodes:
                kind_counts[n.kind] = kind_counts.get(n.kind, 0) + 1
            top = sorted(kind_counts.items(), key=lambda kv: -kv[1])[:10]
            print(f"    - Node kinds: {', '.join(f'{k}={v}' for k, v in top)}")

            source_kinds = {"python", "typescript", "tsx", "javascript", "jsx", "go", "rust",
                            "java", "csharp", "cpp", "c", "header", "ruby", "php", "swift",
                            "kotlin", "scala", "haskell", "lean", "function", "class",
                            "struct", "method", "interface"}
            source_count = sum(v for k, v in kind_counts.items() if k in source_kinds)
            if source_count == 0:
                print("    - [!] WARNING: No source-code nodes found in graph.")
                print("      The scanner may have missed your source directory due to:")
                print(f"      * max_nodes cap (default {DEFAULT_SCAN_MAX_NODES} -- try --max-nodes {DEFAULT_SCAN_MAX_NODES * 4})")
                print("      * Source dir is inside a skipped directory (repos/, references/, etc.)")
                print("      * Files are staged but not committed (re-scan after git add)")
                print("      Rescan with: graphgraph scan --depth symbols --docs")
            else:
                print(f"    - Source nodes: {source_count} (OK)")
            if graph.metadata.get("files_truncated") == "true":
                matched = graph.metadata.get("files_total_matched", "?")
                print(
                    f"    - [!] WARNING: file scan was truncated -- only some of {matched} matching "
                    "files were read. Rescan with a higher --max-nodes for full coverage."
                )
            if graph.metadata.get("symbols_truncated") == "true":
                cap = graph.metadata.get("symbols_cap", "?")
                print(
                    f"    - [!] WARNING: symbol extraction hit its cap ({cap}) -- some scanned files "
                    "may have zero extracted functions/classes. Rescan with a higher --max-nodes."
                )
        except Exception as e:
            print(f"    - Error loading graph: {e}")
    except FileNotFoundError:
        print("  Active Graph: No native graph file found in .graphgraph/")
        print("    - Build one with: graphgraph scan --directory . --depth symbols --docs --output .graphgraph/graph.gg")
        print("    - Import external graphs explicitly with: graphgraph ingest --input <path> --output .graphgraph/graph.gg")


    # 5. MCP Settings Verification (per client, not a single generic "OK").
    print("\n[MCP Server Integration]")

    def _report_mcp_client(label: str, config_path: Path | None, missing_hint: str) -> bool:
        """Print whether the graphgraph MCP server is registered for one client."""
        if config_path is None:
            print(f"  {label}: config location unavailable on this platform")
            return False
        if not config_path.exists():
            print(f"  {label}: not configured ({missing_hint})")
            return False
        try:
            data = json.loads(config_path.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"  {label}: found config but failed to parse: {e}")
            return False
        servers = data.get("mcpServers", {})
        if "graphgraph" in servers:
            print(f"  {label}: Configured (OK)  [{config_path}]")
            print(f"    - Command: {servers['graphgraph'].get('command')}")
            return True
        print(f"  {label}: config present but 'graphgraph' server not registered ({missing_hint})")
        return False

    home = Path.home()
    appdata = os.environ.get("APPDATA")
    desktop_cfg = (Path(appdata) / "Claude" / "claude_desktop_config.json") if appdata else None

    code_global = _report_mcp_client(
        "Claude Code (user ~/.claude.json)",
        home / ".claude.json",
        "run: graphgraph install --platform claude-code",
    )
    code_project = _report_mcp_client(
        "Claude Code (project ./.mcp.json)",
        Path(".mcp.json"),
        "run: graphgraph install --project --platform claude-code",
    )
    desktop = _report_mcp_client(
        "Claude Desktop",
        desktop_cfg,
        "run: graphgraph install --platform claude-desktop",
    )
    codex_project = _report_mcp_client(
        "Codex plugin bundle (project ./plugins/graphgraph/.mcp.json)",
        Path("plugins/graphgraph/.mcp.json"),
        "run: graphgraph install --project --platform codex",
    )
    if codex_project:
        print(
            "    - Bundle registration does not prove this running Codex session loaded "
            "the MCP server."
        )
        print(
            "    - Reinstall/repair: graphgraph install --project --platform codex; "
            "then start a fresh Codex session and verify graphgraph/query_context is exposed."
        )
    cursor_project = _report_mcp_client(
        "Cursor (project ./.cursor/mcp.json)",
        Path(".cursor/mcp.json"),
        "run: graphgraph install --project --platform cursor",
    )
    cursor_global = _report_mcp_client(
        "Cursor (user ~/.cursor/mcp.json)",
        home / ".cursor" / "mcp.json",
        "run: graphgraph install --platform cursor",
    )
    gemini_proj_1 = _report_mcp_client(
        "Gemini/Antigravity (project ./.gemini/settings.json)",
        Path(".gemini/settings.json"),
        "run: graphgraph install --project --platform gemini",
    )
    gemini_proj_2 = _report_mcp_client(
        "Gemini/Antigravity (project ./.agents/mcp_config.json)",
        Path(".agents/mcp_config.json"),
        "run: graphgraph install --project --platform gemini",
    )
    gemini_project = gemini_proj_1 or gemini_proj_2

    gemini_glob_1 = _report_mcp_client(
        "Gemini/Antigravity (user ~/.gemini/settings.json)",
        home / ".gemini" / "settings.json",
        "run: graphgraph install --platform gemini",
    )
    gemini_glob_2 = _report_mcp_client(
        "Gemini/Antigravity (user ~/.gemini/config/mcp_config.json)",
        home / ".gemini" / "config" / "mcp_config.json",
        "run: graphgraph install --platform gemini",
    )
    gemini_glob_3 = _report_mcp_client(
        "Gemini/Antigravity (user ~/.gemini/antigravity-cli/mcp_config.json)",
        home / ".gemini" / "antigravity-cli" / "mcp_config.json",
        "run: graphgraph install --platform gemini",
    )
    gemini_global = gemini_glob_1 or gemini_glob_2 or gemini_glob_3

    if not (
        code_global or code_project or desktop
        or codex_project or cursor_project or cursor_global
        or gemini_project or gemini_global
    ):
        print("  [!] No client has the graphgraph MCP server registered.")
        print("      In a Claude Code session, MCP tools will be unavailable; use the `graphgraph` CLI instead.")


def cmd_render(args: argparse.Namespace) -> None:
    graph_path = Path(args.graph) if args.graph else find_graph_path()
    graph = load_any(graph_path)
    starts = resolve_start_nodes(graph, args.starts)
    plan = plan_context(args.query_class, max_nodes=args.max_nodes)
    if args.max_nodes is None:
        plan = apply_shape_budget(graph, plan, getattr(args, "query", ""))
    nodes, edges = graph.expand(starts, hops=plan.hops, max_nodes=plan.node_budget, direction=plan.direction)
    plan = refine_plan_for_subgraph(plan, compute_subgraph_stats(graph, nodes, edges))
    cache = TopologicalKVCache()
    cache_key = compute_cache_key(args.starts, args.query_class, plan.hops, f"{plan.packet}|render|{plan.planner_version}|{plan.node_budget}|{plan.direction}")
    cached_packet = cache.get(graph_path, cache_key)
    if cached_packet:
        print(cached_packet)
        return

    packet = render_packet(graph, nodes, edges, plan.packet)
    cache.set(
        graph_path,
        cache_key,
        packet,
        node_ids=nodes,
        paths=[graph.nodes[node_id].path for node_id in nodes if node_id in graph.nodes and graph.nodes[node_id].path],
    )
    print(packet)


def cmd_final(args: argparse.Namespace) -> None:
    graph_path = Path(args.graph) if args.graph else find_graph_path()
    policies_path = Path(args.policies) if args.policies else find_policies_path()

    if getattr(args, "stable_skeleton", False):
        max_nodes = getattr(args, "max_nodes", 100) or 100
        print(render_stable_skeleton(graph_path, max_nodes=max_nodes, packet=getattr(args, "packet", "gg") or "gg"))
        return

    if getattr(args, "full_graph", False):
        max_tokens = getattr(args, "full_graph_max_tokens", 20_000)
        try:
            print(render_full_graph(
                graph_path,
                packet=getattr(args, "packet", "gg") or "gg",
                max_tokens=max_tokens if max_tokens else None,
            ))
        except FullGraphTooLargeError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)
        return

    if not args.starts:
        print("Error: --starts is required unless --stable-skeleton or --full-graph is specified.", file=sys.stderr)
        sys.exit(1)
    if not args.query_class:
        print("Error: --query-class is required unless --stable-skeleton or --full-graph is specified.", file=sys.stderr)
        sys.exit(1)

    print(
        render_final_packet(
            starts=args.starts,
            query_class=args.query_class,
            query_text=args.query,
            graph_path=graph_path,
            policies_path=policies_path,
            paths=tuple(args.path),
            tags=tuple(args.tag),
            max_nodes=args.max_nodes,
            cache_namespace="cli_final",
            packet=getattr(args, "packet", None),
        )
    )


def cmd_query(args: argparse.Namespace) -> None:
    graph_path = Path(args.graph) if args.graph else find_graph_path()
    freshness = inspect_saved_graph_freshness(
        directory=project_root_for_graph(graph_path),
        output_path=graph_path,
    )
    if not freshness["fresh"]:
        print(
            f"GraphGraph WARNING: graph is stale for {freshness['changed_count']} changed and "
            f"{freshness['deleted_count']} deleted path(s); use `context --sync git`.",
            file=sys.stderr,
        )
    output = render_query_context(
        query=args.query,
        query_class=args.query_class,
        graph_path=graph_path,
        packet=args.packet,
        hops=args.hops,
        anchor_limit=args.anchor_limit,
        max_nodes=args.max_nodes,
        scopes=tuple(args.scope),
        scope_mode=args.scope_mode,
        show_anchors=args.show_anchors,
        cache_namespace="cli_query",
        source_mode=args.source_mode,
        memory_scopes=tuple(args.memory_scope) or ("project", "session"),
    )
    if getattr(args, "show_stats", False):
        shape = graph_shape(load_any(graph_path))
        print(
            (
                f"GraphGraph query: {graph_path} "
                f"nodes={shape['nodes']} edges={shape['edges']} "
                f"source={shape['source_nodes']} docs={shape['doc_nodes']} other={shape['other_nodes']}"
            ),
            file=sys.stderr,
        )
    print(output)


def cmd_snippets(args: argparse.Namespace) -> None:
    graph_path = Path(args.graph) if args.graph else find_graph_path()
    print(
        render_source_snippets(
            starts=list(args.starts),
            graph_path=graph_path,
            context_lines=args.context_lines,
            max_lines=args.max_lines,
        )
    )


def cmd_context(args: argparse.Namespace) -> None:
    skip_dirs: list[str] = list(args.skip_dirs or [])
    exclude_dirs: list[str] = list(getattr(args, "exclude_dirs", None) or [])
    all_skip = tuple(skip_dirs + [d for d in exclude_dirs if d not in skip_dirs])
    include_dirs: list[str] = list(getattr(args, "include", None) or [])
    graph_path = Path(args.graph) if args.graph else None
    directory = (
        Path(args.directory)
        if args.directory
        else project_root_for_graph(graph_path)
        if graph_path is not None
        else Path(".")
    )
    output, status = render_native_context(
        query=args.query,
        query_class=args.query_class,
        directory=directory,
        graph_path=graph_path,
        rebuild=args.rebuild,
        max_nodes=args.max_nodes,
        scan_max_nodes=args.scan_max_nodes,
        packet=args.packet,
        anchor_limit=args.anchor_limit,
        scopes=tuple(args.scope),
        scope_mode=args.scope_mode,
        skip_dirs=all_skip,
        include_dirs=tuple(include_dirs),
        depth=args.depth,
        frontend=args.frontend,
        docs=args.docs,
        history=args.history,
        generic_mentions=args.generic_mentions,
        incremental=args.incremental,
        show_anchors=args.show_anchors,
        changed_paths=tuple(args.changed),
        deleted_paths=tuple(args.deleted),
        sync_git=args.sync == "git",
        json_output=args.json,
        json_details=args.details,
        source_mode=args.source_mode,
        memory_scopes=tuple(args.memory_scope) or ("project", "session"),
    )
    if args.show_stats:
        shape = graph_shape(status.graph)
        action = "refreshed" if status.changed_paths or status.deleted_paths else ("built" if status.built else "loaded")
        print(
            (
                f"GraphGraph context {action}: {status.path} "
                f"nodes={shape['nodes']} edges={shape['edges']} "
                f"source={shape['source_nodes']} docs={shape['doc_nodes']} other={shape['other_nodes']}"
            ),
            file=sys.stderr,
        )
        if status.changed_paths or status.deleted_paths:
            print(
                f"GraphGraph sync changed={len(status.changed_paths)} deleted={len(status.deleted_paths)}",
                file=sys.stderr,
            )
    if args.validate and not args.json:
        validation = validate_any(output)
        print(
            f"Packet structural validation: {'PASS' if validation.ok else 'FAIL'} {validation.format} "
            f"nodes={validation.node_count} edges={validation.edge_count}",
            file=sys.stderr,
        )
    print(output)


def cmd_status(args: argparse.Namespace) -> None:
    report = build_project_status(
        directory=Path(args.directory) if args.directory else Path("."),
        graph_path=Path(args.graph) if args.graph else None,
        run_probes=bool(args.probe),
    )
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return

    if report.get("status") in {"no_graph", "ambiguous_graph"}:
        print("GraphGraph Status")
        print("=================")
        print(report["message"])
        return

    graph = report["graph"]  # type: ignore[index]
    package = report["package"]  # type: ignore[index]
    validation = graph["validation"]  # type: ignore[index]
    shape = graph["shape"]  # type: ignore[index]
    print("GraphGraph Status")
    print("=================")
    print(f"Graph: {graph['path']}")
    print(
        f"Structural validation: {'PASS' if validation['ok'] else 'FAIL'} "
        f"{validation['format']} nodes={validation['nodes']} edges={validation['edges']}"
    )
    print(
        f"Shape: source={shape['source_nodes']} docs={shape['doc_nodes']} "
        f"other={shape['other_nodes']} total={shape['nodes']}"
    )
    print("Top kinds: " + ", ".join(f"{k}={v}" for k, v in graph["top_kinds"].items()))
    member_calls = graph.get("member_calls") or {}
    print(
        "Member calls: "
        f"resolved={member_calls.get('resolved', 0)} "
        f"ambiguous={member_calls.get('ambiguous', 0)} "
        f"unknown_receiver={member_calls.get('unknown_receiver', 0)} "
        f"external_or_unmatched={member_calls.get('external_or_unmatched', member_calls.get('unresolved', 0))} "
        f"scope={member_calls.get('scope', 'unavailable')} "
        f"trust={member_calls.get('trust', 'unavailable')} "
        f"coverage={member_calls.get('coverage', 'unavailable')}"
    )
    if member_calls.get("warning"):
        print(f"  !  WARNING: {member_calls['warning']}")
    last_update = member_calls.get("last_update") or {}
    if last_update and last_update.get("scope") != member_calls.get("scope"):
        print(
            "  Last update: "
            f"resolved={last_update.get('resolved', 0)} "
            f"ambiguous={last_update.get('ambiguous', 0)} "
            f"unknown_receiver={last_update.get('unknown_receiver', 0)} "
            f"external_or_unmatched={last_update.get('external_or_unmatched', last_update.get('unresolved', 0))} "
            f"scope={last_update.get('scope', 'unavailable')}"
        )
    concept_linking = graph.get("concept_linking") or {}
    if concept_linking:
        print(
            "Concept linking: "
            f"linked={concept_linking.get('linked_nodes', 0)}/{concept_linking.get('eligible_nodes', 0)} "
            f"coverage={concept_linking.get('coverage_ratio', 0):.2%} "
            f"facts={concept_linking.get('typed_fact_links', 0)} "
            f"aliases={concept_linking.get('exact_alias_links', 0)} "
            f"concepts={concept_linking.get('linked_concepts', 0)} "
            f"mode={concept_linking.get('mode', 'unavailable')} "
            f"scope={concept_linking.get('scope', 'unavailable')} "
            f"health={concept_linking.get('status', 'unavailable')}"
        )
        if concept_linking.get("diagnostic_reason"):
            print(f"  !  {concept_linking['diagnostic_reason']}")
        concept_update = concept_linking.get("last_update") or {}
        if concept_update.get("scope") not in {
            "",
            "unavailable",
            concept_linking.get("scope"),
        }:
            print(
                "  Last update: "
                f"linked={concept_update.get('linked_nodes', 0)}/"
                f"{concept_update.get('eligible_nodes', 0)} "
                f"coverage={concept_update.get('coverage_ratio', 0):.2%} "
                f"scope={concept_update.get('scope')}"
            )
    if graph.get("files_truncated"):
        print(
            f"  !  WARNING: file scan was truncated -- only some of "
            f"{graph.get('files_total_matched', '?')} matching files were read."
        )
    if graph.get("symbols_truncated"):
        print(f"  !  WARNING: symbol extraction hit its cap ({graph.get('symbols_cap', '?')}).")
    if package.get("name"):
        print(f"Package: {package['name']} {package.get('version') or ''}".rstrip())
        if package.get("module"):
            print(f"Module: {package['module']}")
    if package.get("ecosystems"):
        print("Ecosystems: " + ", ".join(package["ecosystems"]))
    rust = package.get("rust") or {}
    if rust:
        print(
            f"Rust {rust.get('kind', 'package')}: {rust.get('name', '(unknown)')}"
            + (f" members={len(rust.get('members', []))}" if rust.get("kind") == "workspace" else "")
        )
    if package.get("src_layout"):
        print(f"Runtime hint: {package['import_hint']}")
    scripts = package.get("scripts") or {}
    if scripts:
        print("Scripts: " + ", ".join(f"{name}={target}" for name, target in scripts.items()))
    probes = report.get("runtime_probes") or []
    notes = report.get("runtime_notes") or []
    if notes:
        print("Runtime notes:")
        for note in notes:
            print(f"  - {note}")
    if probes:
        print("Runtime probes:")
        for probe in probes:
            status = "PASS" if probe.get("ok") else "FAIL"
            label = probe.get("name") or "probe"
            env = probe.get("env") or ""
            print(f"  {status} {label} [{env}] {probe.get('command')} rc={probe.get('returncode', '')}")
            for line in probe.get("output", [])[:2]:
                print(f"    {line}")


def cmd_validate(args: argparse.Namespace) -> None:
    if args.packet:
        packet = Path(args.packet).read_text(encoding="utf-8")
    elif not sys.stdin.isatty():
        packet = sys.stdin.read()
    else:
        packet = ""

    # When no packet/stdin is supplied, honor the documented "auto-detect saved
    # graph JSON" behavior instead of failing on empty input.
    if not packet.strip():
        try:
            graph_path = find_graph_path()
        except FileNotFoundError:
            graph_path = None
        if graph_path is not None:
            print(f"No packet supplied; auto-detected saved graph: {graph_path}")
            result = validate_graph_file(graph_path)
            status = "PASS" if result.ok else "FAIL"
            print(
                f"STRUCTURAL {status} {result.format} "
                f"nodes={result.node_count} edges={result.edge_count} path={graph_path}"
            )
            for error in result.errors:
                print(f"- {error}")
            if not result.ok:
                sys.exit(1)
            return
        print("FAIL no input: pipe a packet via stdin, pass --packet <file>, or run `graphgraph validate-graph`.")
        print("  (no saved graph found under .graphgraph/ to auto-detect)")
        sys.exit(1)
        return

    result = validate_any(packet)
    status = "PASS" if result.ok else "FAIL"
    print(f"STRUCTURAL {status} {result.format} nodes={result.node_count} edges={result.edge_count}")
    for error in result.errors:
        print(f"- {error}")
    if not result.ok:
        sys.exit(1)


def cmd_validate_graph(args: argparse.Namespace) -> None:
    requested_path = args.graph or getattr(args, "path", None)
    graph_path = Path(requested_path) if requested_path else find_graph_path()
    result = validate_graph_file(graph_path)
    status = "PASS" if result.ok else "FAIL"
    print(f"STRUCTURAL {status} {result.format} nodes={result.node_count} edges={result.edge_count} path={graph_path}")
    for error in result.errors:
        print(f"- {error}")
    if not result.ok:
        sys.exit(1)


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
    # Merge --skip-dirs and --exclude into a single list
    skip_dirs: list[str] = list(args.skip_dirs or [])
    exclude_dirs: list[str] = list(getattr(args, "exclude_dirs", None) or [])
    all_skip = skip_dirs + [d for d in exclude_dirs if d not in skip_dirs]
    include_dirs: list[str] = list(getattr(args, "include", None) or [])
    started = time.monotonic()

    def report_progress(phase: str, detail: str) -> None:
        elapsed = time.monotonic() - started
        print(f"[graphgraph {elapsed:7.1f}s] {phase}: {detail}", file=sys.stderr, flush=True)

    status = scan_validated_graph(
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
        progress=report_progress,
    )
    graph = status.graph
    validation = status.validation
    assert validation is not None

    # Rich diagnostic summary
    total_nodes = len(graph.nodes)
    total_edges = len(graph.edges)

    # Count nodes by kind
    kind_counts: dict[str, int] = {}
    for node in graph.nodes.values():
        kind_counts[node.kind] = kind_counts.get(node.kind, 0) + 1

    source_kinds = {"python", "typescript", "tsx", "javascript", "jsx", "go", "rust",
                    "java", "csharp", "cpp", "c", "header", "ruby", "php", "swift",
                    "kotlin", "scala", "haskell", "lean", "function", "class",
                    "struct", "method", "interface"}
    source_nodes = sum(v for k, v in kind_counts.items() if k in source_kinds)
    doc_nodes = sum(v for k, v in kind_counts.items() if k in {"markdown", "rst", "html", "text", "concept", "section", "paragraph"})

    print(f"Scanned {total_nodes} nodes, {total_edges} edges  ->  {output_path}")
    print(f"  Structural validation: PASS {validation.format} nodes={validation.node_count} edges={validation.edge_count}")
    if status.repaired:
        print("  Repair       : incremental scan was invalid; promoted a clean full rebuild")
    print(f"  Source nodes : {source_nodes}  |  Doc nodes : {doc_nodes}  |  Other : {total_nodes - source_nodes - doc_nodes}")
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
    # Reuse collection telemetry instead of walking the repository a second
    # time after the scan merely to discover which default rules fired.
    default_pruned_count = int(graph.metadata.get("default_pruned_dir_count", "0"))
    default_pruned_sample = graph.metadata.get("default_pruned_dirs", "")
    if default_pruned_count:
        print(
            f"  Default/explicit pruned: {default_pruned_count} directories"
            + (f" [{default_pruned_sample}]" if default_pruned_sample else "")
            + "  (--include only overrides a default skip name)"
        )
    top_kinds = sorted(kind_counts.items(), key=lambda kv: -kv[1])[:8]
    print("  Top kinds    : " + "  ".join(f"{k}={v}" for k, v in top_kinds))
    if source_nodes == 0:
        print()
        print("  !  WARNING: zero source nodes found. Possible causes:")
        print("     * All source files are inside excluded/skipped directories")
        print("     * The --directory flag points to the wrong root")
        print(f"     * max_nodes cap hit before source files were reached (try --max-nodes {DEFAULT_SCAN_MAX_NODES * 4})")
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


def cmd_update(args: argparse.Namespace) -> None:
    root = Path(args.directory) if args.directory else Path(".")
    output_path = Path(args.output) if args.output else Path(".graphgraph/graph.gg")

    status = update_paths_validated_graph(
        directory=root,
        output_path=output_path,
        paths=args.files,
        max_nodes=args.max_nodes,
        depth=args.depth,
        frontend=args.frontend,
        docs=args.docs,
        history=args.history,
    )
    graph = status.graph
    validation = status.validation
    assert validation is not None
    print(f"Updated {len(args.files)} file(s), graph now {len(graph.nodes)} nodes, {len(graph.edges)} edges  ->  {output_path}")
    print(f"  Structural validation: PASS {validation.format} nodes={validation.node_count} edges={validation.edge_count}")
    if status.repaired:
        print("  Repair       : no prior graph/manifest (or targeted update was invalid); promoted a clean full rebuild")


def cmd_remove(args: argparse.Namespace) -> None:
    root = Path(args.directory) if args.directory else Path(".")
    output_path = Path(args.output) if args.output else Path(".graphgraph/graph.gg")

    status = remove_paths_validated_graph(
        directory=root,
        output_path=output_path,
        paths=args.files,
        max_nodes=args.max_nodes,
        depth=args.depth,
        frontend=args.frontend,
        docs=args.docs,
        history=args.history,
    )
    graph = status.graph
    validation = status.validation
    assert validation is not None
    print(f"Removed {len(args.files)} file(s), graph now {len(graph.nodes)} nodes, {len(graph.edges)} edges  ->  {output_path}")
    print(f"  Structural validation: PASS {validation.format} nodes={validation.node_count} edges={validation.edge_count}")
    if status.repaired:
        print("  Repair       : no prior graph/manifest (or removal was invalid); promoted a clean full rebuild")


def cmd_ingest(args: argparse.Namespace) -> None:
    if args.input:
        input_path = Path(args.input)
    else:
        try:
            input_path = find_graph_path()
        except FileNotFoundError:
            raise FileNotFoundError("Could not find input graph. Specify --input explicitly.")
    output_path = Path(args.output) if args.output else Path(".graphgraph/graph.gg")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    graph = load_any(input_path, normalize_external_refs=True)
    validation = save_validated_graph(graph, output_path)
    print(
        f"Ingested {len(graph.nodes)} nodes, {len(graph.edges)} edges from {input_path} -> {output_path} "
        f"(validation PASS {validation.format})"
    )


def cmd_export(args: argparse.Namespace) -> None:
    graph_path = Path(args.graph) if args.graph else find_graph_path()
    output_path = Path(args.output) if args.output else graph_path.with_suffix(".gg")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    graph = load_any(graph_path)
    save_gg(graph, output_path)
    print(f"Exported {len(graph.nodes)} nodes, {len(graph.edges)} edges -> {output_path}")


def cmd_ontology(args: argparse.Namespace) -> None:
    for name, spec in DEFAULT_RELATIONS.items():
        if args.family and spec.family != args.family:
            continue
        weak = " weak" if spec.weak else ""
        print(f"{name}: family={spec.family} strength={spec.strength:g} direction={spec.direction}{weak} - {spec.description}")


def cmd_compare(args: argparse.Namespace) -> None:
    left = load_any(Path(args.left))
    right = load_any(Path(args.right))
    comparison = compare_graphs(left, right)
    data = {
        "left": comparison.left.__dict__,
        "right": comparison.right.__dict__,
        "shared_node_paths": comparison.shared_node_paths,
        "shared_edge_keys": comparison.shared_edge_keys,
        "left_only_edge_keys": comparison.left_only_edge_keys,
        "right_only_edge_keys": comparison.right_only_edge_keys,
        "shared_normalized_edges": comparison.shared_normalized_edges,
    }
    print(json.dumps(data, indent=2, ensure_ascii=False))


def cmd_cache(args: argparse.Namespace) -> None:
    graph_path = Path(args.graph) if getattr(args, "graph", None) else None
    cache_file = (graph_path.parent / "kv_cache.json") if graph_path else Path(".graphgraph") / "kv_cache.json"
    cache = TopologicalKVCache(cache_file)
    if getattr(args, "recompute_centrality", False):
        resolved_graph_path = graph_path or find_graph_path()
        graph = load_any(resolved_graph_path)
        scores = graph.recompute_centrality()
        validation = save_validated_graph(graph, resolved_graph_path)
        n = cache.clear()
        activation_file = resolved_graph_path.parent / "activation_state.json"
        if activation_file.exists():
            activation_file.unlink()
        print(
            f"Recomputed PageRank for {len(scores)} active nodes in {resolved_graph_path}; "
            f"cleared {n} packet cache entries (validation PASS {validation.format})"
        )
    elif getattr(args, "clear", False):
        n = cache.clear()
        print(f"Cleared {n} cache entries from {cache_file}")
    else:
        s = cache.stats()
        print(f"Cache: {s['entries']}/{s['max_entries']} entries  hits={s['hits']}  misses={s['misses']}  hit_rate={s['hit_rate_pct']}%")
        print(f"File: {cache_file}")


def cmd_eval(args: argparse.Namespace) -> None:
    tasks = load_eval_tasks(Path(args.tasks))
    results = evaluate_graph(Path(args.graph), tasks, max_nodes=args.max_nodes)
    print(results_to_json(results))


def cmd_frontends(_args: argparse.Namespace) -> None:
    data = [cap.__dict__ for cap in available_frontends()]
    print(json.dumps(data, indent=2, ensure_ascii=False))


def cmd_traversal(args: argparse.Namespace) -> None:
    if args.query_class:
        print(json.dumps(traversal_policy(args.query_class).__dict__, indent=2, ensure_ascii=False))
        return
    print(json.dumps({name: policy.__dict__ for name, policy in POLICIES.items()}, indent=2, ensure_ascii=False))


