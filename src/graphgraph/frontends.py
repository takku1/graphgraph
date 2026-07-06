"""Compatibility facade re-exporting the modular scanner frontend API."""

from .scanner.frontends import (
    ExtractionResult,
    Extractor,
    FrontendCapability,
    RegexExtractor,
    SourceFile,
    TreeSitterExtractor,
    _imported_symbol_names,
    available_frontends,
    select_extractor,
    tree_sitter_available,
)

__all__ = [
    "FrontendCapability",
    "SourceFile",
    "ExtractionResult",
    "Extractor",
    "RegexExtractor",
    "TreeSitterExtractor",
    "tree_sitter_available",
    "available_frontends",
    "select_extractor",
    "_imported_symbol_names",
]
