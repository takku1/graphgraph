from __future__ import annotations

import re
from pathlib import Path

from ..core import Graph, Node
from ..io import find_graph_path, load_any
from .context import resolve_start_nodes


LINE_RE = re.compile(r"\bL(\d+)\b")


def render_source_snippets(
    *,
    starts: list[str],
    graph_path: Path | None = None,
    context_lines: int = 4,
    max_lines: int = 40,
) -> str:
    """Render bounded source excerpts for selected graph nodes.

    This is the second stage of the precision ladder: graph packets stay compact,
    and exact source is loaded only for nodes the caller selected.
    """
    resolved_graph_path = graph_path or find_graph_path()
    graph = load_any(resolved_graph_path)
    node_ids = resolve_start_nodes(graph, starts)
    if not node_ids:
        raise ValueError(f"No graph nodes matched the requested starts: {starts!r}")

    root = _graph_root(resolved_graph_path)
    blocks: list[str] = []
    seen: set[tuple[str, int, int]] = set()
    for node_id in node_ids:
        node = graph.nodes.get(node_id)
        if node is None:
            continue
        path = _resolve_source_path(root, node)
        if path is None:
            blocks.append(f"## {node.label} ({node_id})\n\nNo readable source path for node.")
            continue
        start_line = _node_line(node)
        source = _read_excerpt(path, start_line, context_lines=context_lines, max_lines=max_lines)
        key = (str(path), source[0], source[1])
        if key in seen:
            continue
        seen.add(key)
        rel = _display_path(root, path)
        blocks.append(
            "\n".join(
                [
                    f"## {node.label} ({node_id})",
                    f"`{rel}:{source[0]}`",
                    "",
                    "```text",
                    source[2],
                    "```",
                ]
            )
        )
    return "\n\n".join(blocks)


def _graph_root(graph_path: Path) -> Path:
    resolved = graph_path.resolve()
    if resolved.parent.name == ".graphgraph":
        return resolved.parent.parent
    return Path.cwd().resolve()


def _resolve_source_path(root: Path, node: Node) -> Path | None:
    if not node.path:
        return None
    raw = Path(node.path)
    candidates = [raw] if raw.is_absolute() else [root / raw, Path.cwd() / raw]
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if not raw.is_absolute() and not (_is_relative_to(resolved, root) or _is_relative_to(resolved, Path.cwd().resolve())):
            continue
        if resolved.exists() and resolved.is_file():
            return resolved
    return None


def _node_line(node: Node) -> int | None:
    match = LINE_RE.search(node.summary or "")
    if not match:
        return None
    try:
        return max(1, int(match.group(1)))
    except ValueError:
        return None


def _read_excerpt(path: Path, line: int | None, *, context_lines: int, max_lines: int) -> tuple[int, int, str]:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    if not lines:
        return 1, 1, ""
    max_lines = max(1, max_lines)
    if line is None:
        start = 1
        end = min(len(lines), max_lines)
    else:
        start = max(1, line - max(0, context_lines))
        end = min(len(lines), line + max(0, context_lines))
        if end - start + 1 > max_lines:
            end = start + max_lines - 1
    width = len(str(end))
    body = "\n".join(f"{idx:>{width}} | {lines[idx - 1]}" for idx in range(start, end + 1))
    return start, end, body


def _display_path(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
