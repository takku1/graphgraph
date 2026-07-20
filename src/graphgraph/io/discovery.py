from __future__ import annotations

from pathlib import Path

_NATIVE_GRAPH_CANDIDATES = [
    ".graphgraph/graph.gg",
]

_LEGACY_GRAPH_CANDIDATES = [
    ".graphgraph/graph.ggb",
    ".graphgraph/graph.json",
]

_EXTERNAL_GRAPH_CANDIDATES = [
    ".code-review-graph/graph.json",
    "graphify-out/graph.json",
    ".graphify/graph.json",
    "graphify/graph.json",
]

def project_root_for_graph(graph_path: Path) -> Path:
    """Resolve the project that owns a graph artifact.

    Native graphs and validation snapshots may sit below ``.graphgraph``.
    Walking to that boundary prevents an explicit foreign graph path from
    inheriting Git state, semantic caches, policies, or lessons from the
    caller's current working directory.
    """
    resolved = graph_path.resolve()
    graphgraph_dir = next(
        (parent for parent in resolved.parents if parent.name == ".graphgraph"),
        None,
    )
    return graphgraph_dir.parent if graphgraph_dir is not None else resolved.parent


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
    existing = [candidate for candidate in candidates if candidate.exists()]
    if len(existing) == 1:
        return existing[0]
    if len(existing) > 1:
        raise RuntimeError(
            "Multiple GraphGraph files are present; refusing ambiguous auto-detection: "
            f"{[str(path) for path in existing]}. Specify --graph/--output explicitly or remove the stale artifact."
        )
    legacy = [
        workspace_root / candidate
        for candidate in _LEGACY_GRAPH_CANDIDATES
        if (workspace_root / candidate).exists()
    ]
    if legacy:
        raise FileNotFoundError(
            "Found legacy GraphGraph store(s), but automatic discovery only accepts "
            f".graphgraph/graph.gg: {[str(path) for path in legacy]}. Migrate explicitly "
            "with `graphgraph ingest --input <legacy-path> --output .graphgraph/graph.gg`, "
            "or pass the legacy path through --graph for a read-only operation."
        )
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
