"""Scanner public API, lazily loaded (PEP 562).

Importing the scanner package no longer eagerly pulls the tree-sitter frontends:
a caller that only needs ``DEFAULT_SCAN_MAX_NODES`` (e.g. building the CLI parser)
pays nothing for the extraction stack, while ``scan_directory`` and the frontend
types load their modules on first access.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

_LAZY_EXPORTS = {
    "extract_symbols": "ast",
    "remove_paths": "core",
    "scan_directory": "core",
    "update_paths": "core",
    "DocumentInput": "doc",
    "extract_document_context": "doc",
    "DEFAULT_SCAN_MAX_NODES": "files",
    "ExtractionResult": "frontends",
    "Extractor": "frontends",
    "FrontendCapability": "frontends",
    "RegexExtractor": "frontends",
    "SourceIR": "frontends",
    "TreeSitterExtractor": "frontends",
    "available_frontends": "frontends",
    "select_extractor": "frontends",
    "tree_sitter_available": "frontends",
    "CommitRecord": "history",
    "extract_commit_history": "history",
}


def __getattr__(name: str):
    module_path = _LAZY_EXPORTS.get(name)
    if module_path is not None:
        module = importlib.import_module(f".{module_path}", __name__)
        value = getattr(module, name)
        globals()[name] = value
        return value
    try:
        submodule = importlib.import_module(f".{name}", __name__)
    except ImportError:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from None
    globals()[name] = submodule
    return submodule


def __dir__() -> list[str]:
    return sorted(__all__)


if TYPE_CHECKING:
    from .ast import extract_symbols
    from .core import remove_paths, scan_directory, update_paths
    from .doc import DocumentInput, extract_document_context
    from .files import DEFAULT_SCAN_MAX_NODES
    from .frontends import (
        ExtractionResult,
        Extractor,
        FrontendCapability,
        RegexExtractor,
        SourceIR,
        TreeSitterExtractor,
        available_frontends,
        select_extractor,
        tree_sitter_available,
    )
    from .history import CommitRecord, extract_commit_history

__all__ = [
    "DEFAULT_SCAN_MAX_NODES",
    "scan_directory",
    "update_paths",
    "remove_paths",
    "extract_symbols",
    "DocumentInput",
    "extract_document_context",
    "CommitRecord",
    "extract_commit_history",
    "FrontendCapability",
    "SourceIR",
    "ExtractionResult",
    "Extractor",
    "RegexExtractor",
    "TreeSitterExtractor",
    "tree_sitter_available",
    "available_frontends",
    "select_extractor",
]
