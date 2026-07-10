from __future__ import annotations

from pathlib import Path

_NATIVE_GRAPH_CANDIDATES = [
    ".graphgraph/graph.gg",
    ".graphgraph/graph.ggb",
    ".graphgraph/graph.json",
]

_EXTERNAL_GRAPH_CANDIDATES = [
    ".code-review-graph/graph.json",
    "graphify-out/graph.json",
    ".graphify/graph.json",
    "graphify/graph.json",
]


def find_external_graph_path(workspace_root: Path = Path(".")) -> Path | None:
    """Find a non-native graph that can be ingested explicitly.

    External graphs are explicit interop inputs. They are deliberately excluded
    from default graph discovery so generated exports do not silently pollute
    native scans.
    """
    for c in _EXTERNAL_GRAPH_CANDIDATES:
        p = workspace_root / c
        if p.exists():
            return p
    return None


def find_graph_path(workspace_root: Path = Path("."), *, include_external: bool = False) -> Path:
    candidates = [workspace_root / c for c in _NATIVE_GRAPH_CANDIDATES]
    if include_external:
        candidates.extend(workspace_root / c for c in _EXTERNAL_GRAPH_CANDIDATES)
    for c in candidates:
        if c.exists():
            return c
    raise FileNotFoundError(
        "Could not find a native GraphGraph file in default paths: "
        f"{[str(c) for c in candidates]}. Run `graphgraph scan --output .graphgraph/graph.gg` "
        "or specify a graph path explicitly. External graphs must be passed to `graphgraph ingest --input ...`."
    )


def find_policies_path(workspace_root: Path = Path(".")) -> Path | None:
    candidates = [
        workspace_root / ".graphgraph" / "policies.json",
        workspace_root / "policies.json",
        workspace_root / ".code-review-graph" / "policies.json",
        workspace_root / ".agents" / "policies.json",
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


def find_lessons_path(workspace_root: Path = Path(".")) -> Path | None:
    candidates = [
        workspace_root / ".graphgraph" / "lessons.md",
        workspace_root / ".graphgraph" / "reflections" / "LESSONS.md",
        workspace_root / "lessons.md",
    ]
    for c in candidates:
        if c.exists():
            return c
    return None
