from __future__ import annotations

import json
import re

from ..graph.core import Graph

_PATH_RE = re.compile(r"(?:[A-Za-z]:)?[\w./\\-]+\.[A-Za-z0-9]{1,8}(?::\d+)?")
_SYMBOL_RE = re.compile(r"(?:in|at|function|method|class)\s+([A-Za-z_][A-Za-z0-9_.]*)", re.IGNORECASE)


def build_repair_context(graph: Graph, issue: str, *, max_nodes: int = 30, hops: int = 2) -> dict[str, object]:
    """Ground an issue/stack trace in code, tests, config, and likely blast radius."""
    paths = {
        re.sub(r":\d+$", "", match.replace("\\", "/")).casefold()
        for match in _PATH_RE.findall(issue)
    }
    symbols = {match.rsplit(".", 1)[-1].casefold() for match in _SYMBOL_RE.findall(issue)}
    tokens = {token.casefold() for token in re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", issue)}
    scored = []
    for node in graph.nodes.values():
        if not node.active:
            continue
        normalized_path = node.path.replace("\\", "/").casefold()
        score = 0.0
        if any(normalized_path.endswith(path) or path.endswith(normalized_path) for path in paths if normalized_path):
            score += 10.0
        if node.label.casefold() in symbols:
            score += 7.0
        node_tokens = set(re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", f"{node.label} {node.path} {node.summary}".casefold()))
        score += len(tokens & node_tokens) / max(1, len(tokens))
        if score:
            scored.append((score, node.id))
    scored.sort(key=lambda item: (-item[0], item[1]))
    anchors = [node_id for _score, node_id in scored[:8]]
    selected = set(anchors)
    ordered = list(anchors)
    support = set()
    for edge in graph.edges:
        if not edge.active:
            continue
        if edge.target in selected and edge.source in graph.nodes:
            candidate = graph.nodes[edge.source]
            if _is_test(candidate.path) or _is_config(candidate.path):
                support.add(candidate.id)
        if edge.source in selected and edge.target in graph.nodes:
            candidate = graph.nodes[edge.target]
            if _is_test(candidate.path) or _is_config(candidate.path):
                support.add(candidate.id)
    for node_id in sorted(support):
        if node_id not in selected and len(ordered) < max_nodes:
            selected.add(node_id)
            ordered.append(node_id)
    frontier = set(anchors)
    adjacency: dict[str, set[str]] = {}
    for edge in graph.edges:
        if edge.active:
            adjacency.setdefault(edge.source, set()).add(edge.target)
            adjacency.setdefault(edge.target, set()).add(edge.source)
    for _ in range(max(0, hops)):
        frontier = {target for source in frontier for target in adjacency.get(source, ())} - selected
        for node_id in sorted(frontier):
            if node_id not in selected and len(ordered) < max_nodes:
                ordered.append(node_id)
        selected.update(frontier)
        if len(selected) >= max_nodes:
            break
    selected = set(ordered[:max_nodes])
    tests = sorted({node.path for node in graph.nodes.values() if node.id in selected and _is_test(node.path)})
    configs = sorted({node.path for node in graph.nodes.values() if node.id in selected and _is_config(node.path)})
    return {
        "issue": issue,
        "anchors": anchors,
        "nodes": [
            {
                "id": node.id, "label": node.label, "kind": node.kind,
                "path": node.path, "line": node.line, "summary": node.summary,
            }
            for node in graph.nodes.values() if node.id in selected
        ],
        "edges": [
            {"source": edge.source, "type": edge.type, "target": edge.target, "evidence": edge.evidence}
            for edge in graph.edges if edge.active and edge.source in selected and edge.target in selected
        ],
        "tests": tests,
        "configs": configs,
        "receipt": {"grounded": bool(anchors), "node_count": len(selected), "hop_limit": hops},
    }


def repair_context_json(graph: Graph, issue: str, **kwargs) -> str:
    return json.dumps(build_repair_context(graph, issue, **kwargs), indent=2, ensure_ascii=False)


def _is_test(path: str) -> bool:
    value = "/" + path.replace("\\", "/").casefold() + "/"
    return "/test/" in value or "/tests/" in value or value.rsplit("/", 2)[-2].startswith("test_")


def _is_config(path: str) -> bool:
    name = path.replace("\\", "/").rsplit("/", 1)[-1].casefold()
    return name in {"pyproject.toml", "package.json", "cargo.toml", "go.mod", "dockerfile"} or name.startswith(("config.", "settings."))
