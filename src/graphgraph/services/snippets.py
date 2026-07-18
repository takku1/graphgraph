from __future__ import annotations

from pathlib import Path

from ..graph.core import Graph, Node
from ..io import find_graph_path, load_any
from .context import resolve_start_nodes

# Kinds that never have a source-file location -- a label match against one
# of these is not a "missing file" problem, it's a doc/concept/metadata node
# that source_snippets structurally cannot show code for.
_NO_SOURCE_KINDS = {"concept", "section", "paragraph", "decision_trace", "policy", "commit"}


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
    no_source_blocks: list[str] = []
    seen: set[tuple[str, int, int]] = set()
    for node_id in node_ids:
        node = graph.nodes.get(node_id)
        if node is None:
            continue
        path = _resolve_source_path(graph, root, node)
        if path is None:
            if node.kind in _NO_SOURCE_KINDS:
                no_source_blocks.append(
                    f"## {node.label} ({node_id})\n\n"
                    f"(a {node.kind} node -- no source file to show; not a missing-file error, "
                    "this label also matched a doc/metadata node alongside any real code match)"
                )
            else:
                no_source_blocks.append(f"## {node.label} ({node_id})\n\nNo readable source path for node.")
            continue
        start_line = node.line
        source = _read_excerpt(
            path,
            start_line,
            end_line=_node_end_line(graph, node) if context_lines > 0 else None,
            context_lines=context_lines,
            max_lines=max_lines,
        )
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
    # Prefer real source: a label that matched both a code symbol and a
    # doc/concept node with the same name shouldn't clutter the response
    # with a confusing "no source" block when the code match already
    # answered the request. Only surface the no-source blocks if nothing
    # resolved to real code at all, so the response is never silently empty.
    return "\n\n".join(blocks) if blocks else "\n\n".join(no_source_blocks)


def _graph_root(graph_path: Path) -> Path:
    resolved = graph_path.resolve()
    if resolved.parent.name == ".graphgraph":
        return resolved.parent.parent
    return Path.cwd().resolve()


def _resolve_source_path(graph: Graph, root: Path, node: Node) -> Path | None:
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
    fallback = _resolve_descendant_source_path(graph, root, node)
    if fallback is not None:
        return fallback
    return None


def _resolve_descendant_source_path(graph: Graph, root: Path, node: Node) -> Path | None:
    if not node.path:
        return None
    prefix = node.path.replace("\\", "/").strip("/")
    if not prefix:
        return None
    prefix = prefix.rstrip("/") + "/"
    candidates: list[tuple[int, int, int, str, Path]] = []
    for other in graph.nodes.values():
        if not other.active or not other.path:
            continue
        other_path = other.path.replace("\\", "/").strip("/")
        if not other_path.startswith(prefix):
            continue
        resolved = _resolve_direct_path(root, other.path)
        if resolved is None:
            continue
        rel = other_path[len(prefix) :]
        basename = Path(other_path).name.casefold()
        priority = 0 if basename.startswith("index.") else 1 if basename.startswith("main.") else 2
        candidates.append((priority, rel.count("/"), len(other_path), other_path, resolved))
    if not candidates:
        return None
    candidates.sort()
    return candidates[0][4]


def _resolve_direct_path(root: Path, raw_path: str) -> Path | None:
    raw = Path(raw_path)
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


def _node_end_line(graph: Graph, node: Node) -> int | None:
    """Use the next symbol boundary as a language-neutral definition extent."""
    if node.line is None or not node.path:
        return None
    later_lines = [
        other.line
        for other in graph.nodes.values()
        if other.id != node.id
        and other.path == node.path
        and other.line is not None
        and other.line > node.line
    ]
    return min(later_lines) - 1 if later_lines else None


def _read_excerpt(
    path: Path,
    line: int | None,
    *,
    end_line: int | None = None,
    context_lines: int,
    max_lines: int,
) -> tuple[int, int, str]:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    if not lines:
        return 1, 1, ""
    max_lines = max(1, max_lines)
    if line is None:
        start = 1
        end = min(len(lines), max_lines)
    else:
        start = max(1, line - max(0, context_lines))
        symbol_end = (
            end_line
            if end_line is not None
            else _infer_definition_end(lines, line)
            if context_lines > 0
            else line
        )
        end = min(len(lines), max(line + max(0, context_lines), symbol_end))
        if end - start + 1 > max_lines:
            end = start + max_lines - 1
    width = len(str(end))
    body = "\n".join(f"{idx:>{width}} | {lines[idx - 1]}" for idx in range(start, end + 1))
    return start, end, body


def _infer_definition_end(lines: list[str], line: int) -> int:
    """Best-effort body extent for the final symbol in a file."""
    start_index = max(0, line - 1)
    head = lines[start_index]
    if "{" in head:
        depth = 0
        opened = False
        for index in range(start_index, len(lines)):
            depth += lines[index].count("{") - lines[index].count("}")
            opened = opened or "{" in lines[index]
            if opened and depth <= 0:
                return index + 1
    if head.rstrip().endswith(":"):
        base_indent = len(head) - len(head.lstrip())
        end = line
        for index in range(start_index + 1, len(lines)):
            candidate = lines[index]
            if not candidate.strip():
                end = index + 1
                continue
            indent = len(candidate) - len(candidate.lstrip())
            if indent <= base_indent and not candidate.lstrip().startswith(("#", "@")):
                break
            end = index + 1
        return end
    return line


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
