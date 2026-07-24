"""Deterministic, machine-native subsystem maps.

Subsystem boundaries come from source layout, while PageRank is used only to
choose a few representative symbols inside each boundary.  This keeps the map
stable, cheap, and grounded: centrality may identify an API surface, but it
cannot invent an architectural boundary.
"""

from __future__ import annotations

import re
from collections import defaultdict

from ..graph.core import Graph, Node

_ARCHITECTURE_OVERVIEW = re.compile(
    r"\b(?:"
    r"main|major|top[- ]level|overall|whole|all"
    r")\s+(?:subsystems?|components?|packages?|modules?|architecture)\b"
    r"|\b(?:architecture|codebase|project)\s+(?:overview|map|layout|structure)\b"
    r"|\bwhat\s+are\s+the\s+(?:subsystems?|components?|packages?|modules?)\b",
    re.IGNORECASE,
)

_CODE_KINDS = frozenset({
    "class",
    "enum",
    "function",
    "interface",
    "method",
    "struct",
    "trait",
    "type",
})
_CODE_SUFFIXES = frozenset({
    ".c", ".cc", ".cpp", ".cs", ".go", ".h", ".hpp", ".java", ".js",
    ".jsx", ".kt", ".kts", ".lua", ".php", ".py", ".rb", ".rs", ".scala",
    ".swift", ".ts", ".tsx",
})
_EXCLUDED_ROOTS = frozenset({
    "assets",
    "bench",
    "benchmark",
    "benches",
    "benchmarks",
    "docs",
    "examples",
    "fixtures",
    "resources",
    "scripts",
    "test",
    "tests",
})
_COLLECTION_ROOTS = frozenset({
    "apps",
    "crates",
    "libs",
    "modules",
    "packages",
    "plugins",
    "services",
    "subprojects",
})
_SOURCE_ROOTS = frozenset({"lib", "source", "sources", "src"})
_REPRESENTATIVE_NOISE = frozenset({
    "bool",
    "content",
    "count",
    "dict",
    "float",
    "get",
    "int",
    "lines",
    "list",
    "main",
    "node",
    "put",
    "run",
    "set",
    "str",
    "tuple",
})


def wants_subsystem_map(query: str, query_class: str) -> bool:
    """Whether a query asks for the project-wide architecture map."""

    return query_class == "subsystem_summary" and bool(_ARCHITECTURE_OVERVIEW.search(query))


def subsystem_for_path(path: str) -> str | None:
    """Return a stable source-layout subsystem, or ``None`` for non-product code."""

    normalized = path.replace("\\", "/").strip("/")
    if not normalized:
        return None
    parts = [part for part in normalized.split("/") if part]
    if not parts or any(part.casefold() in _EXCLUDED_ROOTS for part in parts[:-1]):
        return None

    root = parts[0].casefold()
    if root in _COLLECTION_ROOTS:
        return parts[1] if len(parts) > 1 else None
    if root in _SOURCE_ROOTS:
        if len(parts) < 2:
            return None
        # src/<package>/<subsystem>/file.py -> subsystem.  Direct package
        # modules remain in the package/root subsystem.
        if len(parts) >= 4:
            return parts[2]
        return parts[1]
    return parts[0] if len(parts) > 1 else "root"


def _eligible(node: Node) -> bool:
    if not node.active or node.kind not in _CODE_KINDS:
        return False
    path = node.path.replace("\\", "/")
    suffix = "." + path.rsplit(".", 1)[-1].casefold() if "." in path.rsplit("/", 1)[-1] else ""
    subsystem = subsystem_for_path(path)
    return suffix in _CODE_SUFFIXES and subsystem not in {None, "root"}


def build_subsystem_map(
    graph: Graph,
    *,
    max_subsystems: int = 20,
    representatives_per_subsystem: int = 2,
) -> dict[str, object]:
    """Build a compact path-partitioned map with central API representatives.

    The deliberately terse field names reduce receipt tokens on the agent path:
    ``n`` is the number of eligible code symbols and ``api`` contains labels of
    the highest-PageRank symbols in that subsystem.
    """

    groups: dict[str, list[str]] = defaultdict(list)
    for node_id, node in graph.nodes.items():
        if not _eligible(node):
            continue
        subsystem = subsystem_for_path(node.path)
        if subsystem is not None:
            groups[subsystem].append(node_id)

    ranks = graph.pagerank() if groups else {}
    rows: list[dict[str, object]] = []
    for name, node_ids in groups.items():
        ranked = sorted(
            node_ids,
            key=lambda node_id: (
                -ranks.get(node_id, 0.0),
                graph.nodes[node_id].label.casefold(),
                node_id,
            ),
        )
        representative_ids = [
            node_id
            for node_id in ranked
            if (
                len(graph.nodes[node_id].label) >= 4
                and not graph.nodes[node_id].label.startswith("_")
                and graph.nodes[node_id].label.casefold() not in _REPRESENTATIVE_NOISE
            )
        ]
        representative_ids.extend(
            node_id for node_id in ranked if node_id not in representative_ids
        )
        api = [
            graph.nodes[node_id].label
            for node_id in representative_ids[:representatives_per_subsystem]
        ]
        rows.append({
            "subsystem": name,
            "n": len(node_ids),
            "api": api,
            "_rank": sum(ranks.get(node_id, 0.0) for node_id in node_ids),
        })

    rows.sort(key=lambda row: (-float(row["_rank"]), -int(row["n"]), str(row["subsystem"])))
    omitted = max(0, len(rows) - max_subsystems)
    emitted = [
        {key: value for key, value in row.items() if key != "_rank"}
        for row in rows[:max_subsystems]
    ]
    return {
        "method": "source_path+pagerank",
        "subsystems": emitted,
        "omitted": omitted,
    }
