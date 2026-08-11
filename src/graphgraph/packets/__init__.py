"""Lazy public packet interface; importing metadata does not load renderers."""

from __future__ import annotations

import importlib

_EXPORTS = {
    "TARGET_NAMES": "..packet_targets",
    "TARGET_SPECS": "..packet_targets",
    "TARGET_TABLE": "..packet_targets",
    "FunctionRef": "..packet_targets",
    "TargetSpec": "..packet_targets",
    "TokenCostModel": "..packet_targets",
    "detect_target": "..packet_targets",
    "packet_format_markdown_table": "..packet_targets",
    "packet_format_schema": "..packet_targets",
    "target_spec": "..packet_targets",
    "estimate_tokens": ".metrics",
    "token_units": ".metrics",
    "DEFAULT_RELATION_ORDER": ".renderers",
    "render_doc_summary": ".renderers",
    "render_gg": ".renderers",
    "render_gg_lex": ".renderers",
    "render_gg_max": ".renderers",
    "render_hybrid": ".renderers",
    "render_lowlevel": ".renderers",
    "render_packet": ".renderers",
    "render_semantic_arrow": ".renderers",
    "render_sql": ".renderers",
    "render_svo": ".renderers",
    "ValidationResult": ".validation",
    "looks_like_graph_json": ".validation",
    "validate_any": ".validation",
    "validate_doc_summary": ".validation",
    "validate_gg_max": ".validation",
    "validate_graph_json": ".validation",
    "validate_graph_object": ".validation",
    "validate_hybrid": ".validation",
    "validate_lowlevel": ".validation",
    "validate_packet": ".validation",
    "validate_semantic_arrow": ".validation",
    "validate_sql": ".validation",
    "validate_svo": ".validation",
}


def __getattr__(name: str):
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(importlib.import_module(module_name, __name__), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(__all__)


__all__ = sorted(_EXPORTS)
