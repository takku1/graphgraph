"""CLI project diagnostics and status reporting."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..io import (
    find_graph_path,
    load_any,
)
from ..scanner import DEFAULT_SCAN_MAX_NODES
from ..scanner.frontends import available_frontends
from ..services.project_atlas import build_project_atlas
from ..services.project_status import build_project_status


def _skill_root_artifact_status(
    skill_root: Path,
    *,
    label_prefix: str = "",
) -> tuple[dict[str, object], ...]:
    """Compare one installed/generated skill root with canonical package assets."""
    assets = Path(__file__).resolve().parents[1] / "assets"
    prefix = f"{label_prefix} " if label_prefix else ""
    artifacts = (
        (f"{prefix}skill contract", skill_root / "SKILL.md", assets / "graphgraph_skill.md"),
        (
            f"{prefix}live validator",
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


def _installed_skill_artifact_status(home: Path) -> tuple[dict[str, object], ...]:
    """Compare the published user-level Codex skill with canonical assets."""
    return _skill_root_artifact_status(home / ".codex" / "skills" / "graphgraph")


def _project_skill_artifact_status(directory: Path) -> tuple[dict[str, object], ...]:
    """Compare project agent/plugin skill bundles with canonical assets."""
    roots = (
        ("Agent", directory / ".agents" / "skills" / "graphgraph"),
        ("Plugin", directory / "plugins" / "graphgraph" / "skills" / "graphgraph"),
    )
    return tuple(
        artifact
        for label, root in roots
        for artifact in _skill_root_artifact_status(root, label_prefix=label)
    )



def cmd_doctor(args: argparse.Namespace) -> None:
    import os
    import platform
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
    print("\n[Semantic Retrieval]")
    try:
        from ..platform import active_backend_name

        backend = active_backend_name()
        if backend == "hash":
            print("  Backend: hash (offline lexical fallback — no paraphrase recall)")
            print(f"  Enable real embeddings by setting ${'GRAPHGRAPH_EMBED_URL'}.")
        else:
            print(f"  Backend: {backend} (real embeddings active)")
    except Exception as exc:  # noqa: BLE001 - diagnostics must never crash
        print(f"  Backend: unavailable ({exc})")

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

    print("\n[Project Skill Artifacts]")
    project_artifact_status = _project_skill_artifact_status(Path.cwd())
    for artifact in project_artifact_status:
        state = str(artifact["state"])
        display = "Current (OK)" if state == "current" else state.upper()
        print(f"  {artifact['label']}: {display}  [{artifact['path']}]")
    if any(artifact["state"] != "current" for artifact in project_artifact_status):
        print("  Repair: graphgraph install --project --platform codex")

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


def cmd_orient(args: argparse.Namespace) -> None:
    report = build_project_atlas(
        directory=Path(args.directory) if args.directory else Path("."),
        graph_path=Path(args.graph) if args.graph else None,
        max_subsystems=int(args.max_subsystems) if args.max_subsystems is not None else None,
        representatives_per_subsystem=int(args.representatives),
        max_couplings=int(args.max_couplings) if args.max_couplings is not None else None,
        evidence_budget_chars=int(args.evidence_budget_chars),
    )
    if args.json:
        print(json.dumps(
            report,
            indent=2 if args.pretty else None,
            ensure_ascii=False,
            separators=None if args.pretty else (",", ":"),
        ))
        return
    print("GraphGraph Project Atlas")
    print("========================")
    if report.get("status") != "ready":
        print(report["message"])
        return
    project = report["project"]
    languages = report["languages"]
    print(f"Project: {project['name']} {project['version']} ({project['root']})")
    print("Languages: " + ", ".join(f"{row['language']}={row['files']}" for row in languages))
    if report["entry_points"]:
        print("Entry points:")
        for row in report["entry_points"]:
            print(f"  {row['name']}: {row['target']} [{row['kind']}]")
    print("Subsystems:")
    for row in report["subsystems"]:
        representatives = ", ".join(
            f"{item['label']}@{item['path']}" for item in row["representatives"]
        )
        print(f"  {row['name']} ({row['symbols']} symbols): {representatives or 'no representative'}")
    if report["couplings"]:
        print("Strongest cross-subsystem coupling:")
        for row in report["couplings"]:
            relations = ", ".join(f"{name}={count}" for name, count in row["relations"].items())
            print(f"  {row['from']} -> {row['to']}: {row['edges']} ({relations})")
    tests = report["tests"]
    commands = ", ".join(item["command"] for item in tests["commands"])
    print(f"Tests: {tests['files']} indexed file(s)" + (f"; candidates: {commands}" if commands else ""))
    limitations = report["coverage"]["limitations"]
    print("Coverage: " + ("; ".join(limitations) if limitations else "no recorded truncation or staleness"))


def cmd_status(args: argparse.Namespace) -> None:
    report = build_project_status(
        directory=Path(args.directory) if args.directory else Path("."),
        graph_path=Path(args.graph) if args.graph else None,
        run_probes=bool(args.probe),
    )
    from ..mcp.machine_contract import advertised_capability

    report["capability"] = advertised_capability("cli")
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return

    if report.get("status") in {"no_graph", "ambiguous_graph"}:
        print("GraphGraph Status")
        print("=================")
        print(report["message"])
        capability = report["capability"]
        print(
            f"Capability: transport={capability['transport']} "
            f"contract_id={capability['contract_id']} tools={capability['tool_count']}"
        )
        return

    graph = report["graph"]  # type: ignore[index]
    package = report["package"]  # type: ignore[index]
    validation = graph["validation"]  # type: ignore[index]
    shape = graph["shape"]  # type: ignore[index]
    print("GraphGraph Status")
    print("=================")
    print(f"Graph: {graph['path']}")
    capability = report["capability"]
    print(
        f"Capability: transport={capability['transport']} "
        f"contract_id={capability['contract_id']} tools={capability['tool_count']}"
    )
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
        f"(external_resolved={member_calls.get('external_resolved', 0)} "
        f"unmatched={member_calls.get('unmatched', 0)}"
        f"{'' if member_calls.get('external_unmatched_split') == 'available' else ' UNSPLIT:rescan'}) "
        f"scope={member_calls.get('scope', 'unavailable')} "
        f"trust={member_calls.get('trust', 'unavailable')} "
        f"coverage={member_calls.get('coverage', 'unavailable')}"
    )
    if member_calls.get("warning"):
        print(f"  !  WARNING: {member_calls['warning']}")
    fresh = graph.get("freshness") or {}
    if fresh.get("fresh") is False:
        print(
            f"  !  STALE GRAPH: {fresh.get('changed_count', 0)} changed and "
            f"{fresh.get('deleted_count', 0)} deleted path(s) since the last scan; "
            "run `graphgraph context --sync git` or re-scan"
        )
    receiver_classes = member_calls.get("unknown_receiver_classes") or {}
    if receiver_classes:
        # Which shapes are unresolved, not just how many.
        print(
            "  Unresolved receivers by shape: "
            + "  ".join(f"{name}={count}" for name, count in receiver_classes.items())
        )
    if member_calls.get("staleness_note"):
        # The headline counts above are a carried-forward snapshot. Say so
        # here, or a resolver change reads as having done nothing.
        print(f"  !  STALE: {member_calls['staleness_note']}")
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

