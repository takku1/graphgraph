from __future__ import annotations

import argparse
import json
from pathlib import Path


def configure(repo_root: Path) -> dict:
    root = repo_root.resolve()
    mcp_path = root / "plugins" / "graphgraph" / ".mcp.json"
    if not mcp_path.exists():
        raise FileNotFoundError(f"Missing Codex MCP config: {mcp_path}")

    data = json.loads(mcp_path.read_text(encoding="utf-8"))
    server = data.setdefault("mcpServers", {}).setdefault("graphgraph", {})
    args = list(server.get("args", []))
    if "--project" in args:
        idx = args.index("--project")
        if idx + 1 >= len(args):
            args.append(root.as_posix())
        else:
            args[idx + 1] = root.as_posix()
    else:
        args = ["run", "--project", root.as_posix(), "graphgraph-mcp"]
    if not args or args[-1] != "graphgraph-mcp":
        args.append("graphgraph-mcp")

    server["command"] = server.get("command") or "uv"
    server["args"] = args
    server["cwd"] = root.as_posix()
    server.setdefault("startup_timeout_sec", 20)
    server.setdefault("tool_timeout_sec", 120)

    mcp_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return {
        "repo_root": str(root),
        "mcp_path": str(mcp_path),
        "command": server["command"],
        "args": args,
        "cwd": server["cwd"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Configure GraphGraph's Codex plugin for this checkout.")
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    result = configure(args.repo_root)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
