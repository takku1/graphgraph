"""Public service interfaces, loaded only when a caller selects one."""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

_LAZY_EXPORTS = {
    "FullGraphTooLargeError": "context",
    "build_project_atlas": "project_atlas",
    "execute_query": "query",
    "query": "query",
    "render_final_packet": "context",
    "render_full_graph": "context",
    "render_source_snippets": "snippets",
    "render_stable_skeleton": "context",
}


def __getattr__(name: str):
    module_name = _LAZY_EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = importlib.import_module(f".{module_name}", __name__)
    value = getattr(module, name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(__all__)


if TYPE_CHECKING:
    from .context import (
        FullGraphTooLargeError,
        render_final_packet,
        render_full_graph,
        render_stable_skeleton,
    )
    from .project_atlas import build_project_atlas
    from .query import execute_query, query
    from .snippets import render_source_snippets


__all__ = [
    "FullGraphTooLargeError",
    "build_project_atlas",
    "execute_query",
    "query",
    "render_final_packet",
    "render_full_graph",
    "render_source_snippets",
    "render_stable_skeleton",
]
