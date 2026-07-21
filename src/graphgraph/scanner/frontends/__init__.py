"""Source-extraction frontends.

Split into layers (model -> languages -> syntax -> rust/python -> edges ->
extractors). This module re-exports the full former surface so
``graphgraph.scanner.frontends`` stays the stable import path.
"""


# ruff: noqa: F401


from __future__ import annotations

from .edges import (
    _add_imports_from,
    _add_nested_contains,
    _add_returns,
    _add_tree_sitter_callback_references,
    _add_tree_sitter_calls,
    _add_tree_sitter_implements,
)
from .extractors import (
    RegexExtractor,
    TreeSitterExtractor,
    select_extractor,
)
from .languages import (
    _LANGUAGE_MODULES,
    _SUFFIX_LANGUAGE,
    _language_available,
    _language_for_name,
    _parse_with_timeout,
    _parser_for_language,
    _parser_for_suffix,
    available_frontends,
    parse_with_timeout,
    parser_for_suffix,
    parser_unavailable_reason,
    tree_sitter_available,
)
from .model import (
    ExtractionResult,
    Extractor,
    FrontendCapability,
    SourceFile,
    _CallSite,
    _MemberCallStats,
    _TsDef,
)
from .python import (
    _python_assignment_names,
    _python_body_nodes,
    _python_class_field_types,
    _python_local_types,
    _python_type_name,
    _python_value_type,
)
from .rust import (
    _add_rust_fields,
    _add_rust_method_owners,
    _add_rust_test_field_references,
    _add_rust_type_references,
    _rust_field_accesses_in_range,
    _rust_fields_in_range,
    _rust_local_call_return_types,
    _rust_local_types,
    _rust_macro_bare_call_names_in_range,
    _rust_type_name,
    _rust_type_names_in_range,
)
from .syntax import (
    _CALL_NAME_FIELDS,
    _CALL_NODE_TYPES,
    _DEF_TYPES,
    _LANGUAGE_CACHE,
    _LANGUAGE_LOAD_ERRORS,
    _NAME_NODE_TYPES,
    _NESTED_NAME_PARENT_TYPES,
    _PARSER_CACHE,
    _PARSER_LOAD_ERRORS,
    _PATH_QUALIFIED_CALL_TYPES,
    _PYTHON_BUILTIN_TYPES,
    DEFINITION_NODE_TYPES,
    NAME_NODE_TYPES,
    _attach_lexical_method_owners,
    _call_name,
    _call_sites_in_range,
    _callback_arg_names_in_range,
    _collect_defs,
    _definition_facts,
    _definition_impl_qualifier,
    _definition_node_id,
    _definition_qualified_name,
    _definition_summary,
    _identifier,
    _imported_symbol_names,
    _imported_symbol_sources,
    _method_owner,
    _name_node,
    _node_text,
    _node_text_range,
    _normalized_path_part,
    _reexported_symbols,
    _resolve_member_call,
    _resolve_path_qualified_target,
    _return_type_name,
    _return_type_names,
    _rust_impl_def,
    _rust_qualified_type_receiver,
    _select_import_target,
    _select_owner_type,
    _syntax_text_without_literals,
)

__all__ = [
    "FrontendCapability",
    "SourceFile",
    "ExtractionResult",
    "Extractor",
    "RegexExtractor",
    "TreeSitterExtractor",
    "DEFINITION_NODE_TYPES",
    "NAME_NODE_TYPES",
    "tree_sitter_available",
    "available_frontends",
    "parse_with_timeout",
    "parser_for_suffix",
    "parser_unavailable_reason",
    "select_extractor",
]
