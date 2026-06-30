from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "benchmarks" / "context_graph" / "out" / "codex"
REPORT_JSON = OUT / "codex_integration_check.json"
REPORT_MD = OUT / "codex_integration_check.md"

PLUGIN = ROOT / "plugins" / "graphgraph"
PLUGIN_JSON = PLUGIN / ".codex-plugin" / "plugin.json"
MCP_JSON = PLUGIN / ".mcp.json"
SKILL_MD = PLUGIN / "skills" / "graphgraph" / "SKILL.md"
MARKETPLACE_JSON = ROOT / ".agents" / "plugins" / "marketplace.json"
CONFIGURATOR = ROOT / "scripts" / "configure_codex_plugin.py"


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    checks: list[Check] = []

    plugin = load_json(PLUGIN_JSON) if PLUGIN_JSON.exists() else {}
    mcp = load_json(MCP_JSON) if MCP_JSON.exists() else {}
    marketplace = load_json(MARKETPLACE_JSON) if MARKETPLACE_JSON.exists() else {}
    skill_text = SKILL_MD.read_text(encoding="utf-8", errors="replace") if SKILL_MD.exists() else ""

    checks.append(Check("plugin_manifest_present", PLUGIN_JSON.exists(), str(PLUGIN_JSON.relative_to(ROOT))))
    checks.append(Check("plugin_name", plugin.get("name") == "graphgraph", str(plugin.get("name"))))
    checks.append(Check("plugin_has_skill", plugin.get("skills") == "./skills/" and SKILL_MD.exists(), str(plugin.get("skills"))))
    checks.append(Check("plugin_has_mcp", plugin.get("mcpServers") == "./.mcp.json" and MCP_JSON.exists(), str(plugin.get("mcpServers"))))
    checks.append(Check("skill_mentions_codex", "Codex" in skill_text and "GraphGraph" in skill_text, f"{len(skill_text)} chars"))
    checks.append(Check("skill_anti_cheating", "Do not use expected answer keys" in skill_text, "answer-key guardrail present"))

    servers = mcp.get("mcpServers", {}) if isinstance(mcp.get("mcpServers"), dict) else {}
    graphgraph_server = servers.get("graphgraph", {}) if isinstance(servers.get("graphgraph"), dict) else {}
    args = graphgraph_server.get("args", [])
    cwd_value = graphgraph_server.get("cwd", "")
    command = graphgraph_server.get("command", "")
    project_arg = args[args.index("--project") + 1] if "--project" in args and args.index("--project") + 1 < len(args) else ""
    project_path = Path(project_arg) if project_arg else Path()
    cwd_path = Path(cwd_value) if cwd_value else Path()

    checks.append(Check("mcp_server_declared", bool(graphgraph_server), ",".join(sorted(servers))))
    checks.append(Check("mcp_command_available", bool(command and shutil.which(command)), command))
    checks.append(Check("mcp_project_path_exists", bool(project_arg and project_path.exists()), project_arg))
    checks.append(Check("mcp_cwd_exists", bool(cwd_value and cwd_path.exists()), cwd_value))
    checks.append(Check("mcp_cwd_matches_project", bool(cwd_value and project_arg and cwd_path.resolve() == project_path.resolve()), f"cwd={cwd_value}; project={project_arg}"))
    checks.append(Check("mcp_project_matches_repo", bool(project_arg and project_path.resolve() == ROOT.resolve()), project_arg))
    checks.append(Check("mcp_entrypoint", args[-1:] == ["graphgraph-mcp"], " ".join(str(item) for item in args)))
    checks.append(Check("codex_configurator_present", CONFIGURATOR.exists(), str(CONFIGURATOR.relative_to(ROOT))))

    marketplace_plugins = marketplace.get("plugins", []) if isinstance(marketplace.get("plugins"), list) else []
    entry = next((item for item in marketplace_plugins if item.get("name") == "graphgraph"), {})
    source = entry.get("source", {}) if isinstance(entry.get("source"), dict) else {}
    source_path = ROOT / str(source.get("path", "")).replace("./", "", 1)
    checks.append(Check("marketplace_present", MARKETPLACE_JSON.exists(), str(MARKETPLACE_JSON.relative_to(ROOT))))
    checks.append(Check("marketplace_name", marketplace.get("name") == "graphgraph-local", str(marketplace.get("name"))))
    checks.append(Check("marketplace_entry", bool(entry), f"{len(marketplace_plugins)} entries"))
    checks.append(Check("marketplace_source_path_exists", source_path.exists(), str(source.get("path"))))
    checks.append(Check("marketplace_policy", entry.get("policy", {}).get("installation") == "AVAILABLE", json.dumps(entry.get("policy", {}))))

    launch_ms, launch_ok, launch_detail = doctor_probe(command, args, cwd_path if cwd_path.exists() else ROOT)
    checks.append(Check("mcp_launch_probe", launch_ok, launch_detail))

    portability_ms, portability_ok, portability_detail = configurator_probe()
    checks.append(Check("configurator_temp_copy_probe", portability_ok, portability_detail))

    metrics = {
        "ok": all(check.ok for check in checks),
        "plugin_path": str(PLUGIN),
        "marketplace_path": str(MARKETPLACE_JSON),
        "mcp_command": command,
        "mcp_args": args,
        "mcp_cwd": cwd_value,
        "mcp_launch_ms": launch_ms,
        "configurator_probe_ms": portability_ms,
        "checks": [check.__dict__ for check in checks],
    }
    REPORT_JSON.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    REPORT_MD.write_text(render_markdown(metrics), encoding="utf-8")
    print(REPORT_MD.read_text(encoding="utf-8"))
    if not metrics["ok"]:
        raise SystemExit("Codex integration check failed")


def doctor_probe(command: str, args: list[Any], cwd: Path) -> tuple[float, bool, str]:
    if not command or not args:
        return 0.0, False, "missing command or args"
    probe_args = [str(item) for item in args[:-1]] + ["graphgraph", "doctor"]
    start = time.perf_counter()
    proc = subprocess.run(
        [command, *probe_args],
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=60,
    )
    elapsed_ms = (time.perf_counter() - start) * 1000
    output = proc.stdout.strip()
    graph_found = "Active Graph: Found" in output
    dep_ok = "tree-sitter: Installed (OK)" in output
    detail = f"{elapsed_ms:.1f}ms; exit={proc.returncode}; graph_found={graph_found}; tree_sitter={dep_ok}"
    return elapsed_ms, proc.returncode == 0 and graph_found and dep_ok, detail


def configurator_probe() -> tuple[float, bool, str]:
    if not CONFIGURATOR.exists():
        return 0.0, False, "configurator missing"
    start = time.perf_counter()
    with tempfile.TemporaryDirectory() as tmp:
        temp_root = Path(tmp) / "graphgraph-copy"
        plugin_copy = temp_root / "plugins" / "graphgraph"
        plugin_copy.mkdir(parents=True)
        shutil.copytree(PLUGIN, plugin_copy, dirs_exist_ok=True)
        scripts_copy = temp_root / "scripts"
        scripts_copy.mkdir(parents=True)
        shutil.copy2(CONFIGURATOR, scripts_copy / CONFIGURATOR.name)
        proc = subprocess.run(
            [sys.executable, str(scripts_copy / CONFIGURATOR.name), "--repo-root", str(temp_root)],
            cwd=temp_root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=30,
        )
        elapsed_ms = (time.perf_counter() - start) * 1000
        if proc.returncode != 0:
            return elapsed_ms, False, f"{elapsed_ms:.1f}ms; exit={proc.returncode}; {proc.stdout.strip()[-200:]}"
        mcp = load_json(plugin_copy / ".mcp.json")
        server = mcp["mcpServers"]["graphgraph"]
        args = server.get("args", [])
        project = args[args.index("--project") + 1] if "--project" in args else ""
        ok = server.get("cwd") == temp_root.resolve().as_posix() and project == temp_root.resolve().as_posix()
        return elapsed_ms, ok, f"{elapsed_ms:.1f}ms; cwd={server.get('cwd')}; project={project}"


def render_markdown(metrics: dict[str, Any]) -> str:
    lines = [
        "# Codex Integration Check",
        "",
        f"Plugin: `{metrics['plugin_path']}`",
        f"Marketplace: `{metrics['marketplace_path']}`",
        f"MCP command: `{metrics['mcp_command']} {' '.join(str(item) for item in metrics['mcp_args'])}`",
        f"MCP cwd: `{metrics['mcp_cwd']}`",
        f"MCP launch probe: `{metrics['mcp_launch_ms']:.1f} ms`",
        f"Configurator temp-copy probe: `{metrics['configurator_probe_ms']:.1f} ms`",
        "",
        "| Check | Status | Detail |",
        "| --- | --- | --- |",
    ]
    for check in metrics["checks"]:
        status = "PASS" if check["ok"] else "FAIL"
        lines.append(f"| `{check['name']}` | `{status}` | {check['detail']} |")
    lines.extend([
        "",
        "## Read",
        "",
        "- This validates Codex packaging and MCP launch wiring only.",
        "- It does not prove Codex has installed the repo marketplace in the user's global config.",
        "- Run `graphgraph install --project --platform codex` to refresh the repo-local plugin for the current checkout.",
        "- `scripts/configure_codex_plugin.py` remains a repair path after copying the repo.",
    ])
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
