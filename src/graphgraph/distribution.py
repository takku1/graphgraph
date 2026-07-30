"""Canonical, deterministic GraphGraph distribution artifacts."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

FILE_BACKED_SOURCES = (
    "graphgraph_skill.md",
    "mcp_server_settings.json",
    "validate_live.py",
)


@dataclass(frozen=True)
class DistributionArtifactStatus:
    path: Path
    source: str
    current: bool


@dataclass(frozen=True)
class _Artifact:
    source: str
    content: str


def codex_plugin_manifest() -> dict[str, object]:
    return {
        "name": "graphgraph",
        "version": "0.1.0",
        "description": "Codex integration for GraphGraph codebase context retrieval, packet validation, and MCP tools.",
        "author": {"name": "GraphGraph"},
        "license": "MIT",
        "keywords": ["codex", "mcp", "codebase-context", "graph-rag", "retrieval"],
        "skills": "./skills/",
        "mcpServers": "./.mcp.json",
        "interface": {
            "displayName": "GraphGraph",
            "shortDescription": "Use compact graph packets for codebase context in Codex.",
            "longDescription": (
                "GraphGraph bundles a Codex skill and MCP server configuration for scanning repositories, "
                "finding graph anchors, rendering final context packets, and validating compressed codebase graph evidence."
            ),
            "developerName": "GraphGraph",
            "category": "Productivity",
            "capabilities": ["Codebase context", "MCP tools", "Local retrieval"],
            "defaultPrompt": [
                "Use GraphGraph to explain this subsystem.",
                "Find the blast radius with GraphGraph.",
                "Validate a GraphGraph packet.",
            ],
            "brandColor": "#2563EB",
        },
    }


def portable_mcp_config() -> dict[str, object]:
    return {"mcpServers": {"graphgraph": {"command": "graphgraph-mcp"}}}


def codex_marketplace_entry(plugin_name: str = "graphgraph") -> dict[str, object]:
    return {
        "name": plugin_name,
        "source": {"source": "local", "path": f"./plugins/{plugin_name}"},
        "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
        "category": "Productivity",
    }


def codex_marketplace() -> dict[str, object]:
    return {
        "name": "graphgraph-local",
        "interface": {"displayName": "GraphGraph Local"},
        "plugins": [codex_marketplace_entry()],
    }


def _json_text(value: object) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False) + "\n"


def _asset_text(name: str) -> str:
    return (Path(__file__).resolve().parent / "assets" / name).read_text(encoding="utf-8")


def _normalized_artifact_bytes(content: bytes) -> bytes:
    """Compare tracked text artifacts independently of checkout newlines."""
    return content.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def _artifact_matches(target: Path, expected: bytes) -> bool:
    return target.exists() and _normalized_artifact_bytes(target.read_bytes()) == _normalized_artifact_bytes(expected)


def distribution_artifacts() -> dict[Path, _Artifact]:
    skill = _asset_text("graphgraph_skill.md")
    validator = _asset_text("validate_live.py")
    example = _asset_text("mcp_server_settings.json")
    portable_mcp = _json_text(portable_mcp_config())
    return {
        Path(".agents/mcp_config.json"): _Artifact("generator:portable_mcp_config", portable_mcp),
        Path(".agents/plugins/marketplace.json"): _Artifact("generator:codex_marketplace", _json_text(codex_marketplace())),
        Path(".agents/skills/graphgraph/SKILL.md"): _Artifact("asset:graphgraph_skill.md", skill),
        Path(".agents/skills/graphgraph/examples/mcp_server_settings.json"): _Artifact("asset:mcp_server_settings.json", example),
        Path(".agents/skills/graphgraph/scripts/validate_live.py"): _Artifact("asset:validate_live.py", validator),
        Path("plugins/graphgraph/.codex-plugin/plugin.json"): _Artifact("generator:codex_plugin_manifest", _json_text(codex_plugin_manifest())),
        Path("plugins/graphgraph/.mcp.json"): _Artifact("generator:portable_mcp_config", portable_mcp),
        Path("plugins/graphgraph/skills/graphgraph/SKILL.md"): _Artifact("asset:graphgraph_skill.md", skill),
        Path("plugins/graphgraph/skills/graphgraph/examples/mcp_server_settings.json"): _Artifact("asset:mcp_server_settings.json", example),
        Path("plugins/graphgraph/skills/graphgraph/scripts/validate_live.py"): _Artifact("asset:validate_live.py", validator),
    }


def distribution_artifact_status(root: Path) -> tuple[DistributionArtifactStatus, ...]:
    rows = []
    for path, artifact in distribution_artifacts().items():
        target = root / path
        current = _artifact_matches(target, artifact.content.encode("utf-8"))
        rows.append(DistributionArtifactStatus(path, artifact.source, current))
    return tuple(rows)


def sync_distribution_artifacts(root: Path) -> tuple[Path, ...]:
    changed = []
    for path, artifact in distribution_artifacts().items():
        target = root / path
        encoded = artifact.content.encode("utf-8")
        if _artifact_matches(target, encoded):
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(encoded)
        changed.append(path)
    return tuple(changed)
