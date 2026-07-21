"""The Extractor implementations: regex fallback and the tree-sitter frontend."""

from __future__ import annotations

from typing import Any

from ...graph.core import Edge, Node
from ...graph.operations import dedupe_edges
from ..ast import _is_context_symbol, extract_symbols
from .edges import (
    _add_imports_from,
    _add_nested_contains,
    _add_returns,
    _add_tree_sitter_callback_references,
    _add_tree_sitter_calls,
    _add_tree_sitter_implements,
)
from .languages import (
    _SUFFIX_LANGUAGE,
    _parse_with_timeout,
    _parser_for_suffix,
    parser_unavailable_reason,
    tree_sitter_available,
)
from .model import (
    ExtractionResult,
    Extractor,
    SourceFile,
    _TsDef,
)
from .rust import (
    _add_rust_fields,
    _add_rust_method_owners,
    _add_rust_test_field_references,
    _add_rust_type_references,
)
from .syntax import (
    _collect_defs,
    _definition_node_id,
    _definition_qualified_name,
    _definition_summary,
)


class RegexExtractor:
    name = "regex"
    confidence = 0.75

    def extract_symbols(
        self,
        files: list[SourceFile],
        max_total_symbols: int,
        context_nodes: dict[str, Node] | None = None,
    ) -> ExtractionResult:
        tuples = [(f.path, f.rel, f.file_node_id, f.text) for f in files]
        nodes, edges, truncated = extract_symbols(tuples, max_total_symbols=max_total_symbols, context_nodes=context_nodes)
        return ExtractionResult(nodes=nodes, edges=edges, frontend=self.name, truncated=truncated)

class TreeSitterExtractor:
    name = "tree_sitter"
    confidence = 0.95

    def __init__(self, *, fallback_on_error: bool = False, parse_timeout_micros: int = 2_000_000) -> None:
        self.fallback_on_error = fallback_on_error
        self.parse_timeout_micros = max(0, parse_timeout_micros)

    def extract_symbols(
        self,
        files: list[SourceFile],
        max_total_symbols: int,
        context_nodes: dict[str, Node] | None = None,
    ) -> ExtractionResult:
        context_ids = set((context_nodes or {}).keys())
        nodes: dict[str, Node] = dict(context_nodes or {})
        edges: list[Edge] = []
        defs_by_file: list[tuple[SourceFile, list[_TsDef], Any]] = []
        name_to_symbols: dict[str, list[str]] = {}
        total = 0
        truncated = False
        fallback_sources: list[SourceFile] = []
        failed_files: list[str] = []
        unsupported_files: list[str] = []
        grammar_errors: list[str] = []
        timeout_files: list[str] = []
        parse_error_files: list[str] = []

        for node_id, node in nodes.items():
            if _is_context_symbol(node):
                name_to_symbols.setdefault(node.label, []).append(node_id)

        for source in files:
            parser = _parser_for_suffix(source.path.suffix.lower())
            if parser is None:
                language = _SUFFIX_LANGUAGE.get(source.path.suffix.lower(), "")
                reason = parser_unavailable_reason(source.path.suffix)
                if self.fallback_on_error:
                    fallback_sources.append(source)
                    unsupported_files.append(source.rel)
                    if language:
                        grammar_errors.append(f"{source.rel}:{reason}")
                    continue
                detail = f" ({language})" if language else ""
                raise RuntimeError(
                    f"Tree-sitter grammar unavailable for {source.rel}{detail}: {reason}"
                )
            text_bytes = source.text.encode("utf-8", errors="replace")
            try:
                tree = _parse_with_timeout(parser, text_bytes, self.parse_timeout_micros)
                if tree is None:
                    raise TimeoutError(f"Tree-sitter parse timed out after {self.parse_timeout_micros} microseconds")
            except Exception as exc:
                try:
                    parser.reset()
                except Exception:
                    pass
                if not self.fallback_on_error:
                    raise RuntimeError(f"Tree-sitter failed for {source.rel}: {exc}") from exc
                fallback_sources.append(source)
                failed_files.append(f"{source.rel}:{type(exc).__name__}")
                if isinstance(exc, TimeoutError):
                    timeout_files.append(source.rel)
                else:
                    parse_error_files.append(source.rel)
                continue
            root = tree.root_node
            defs = _collect_defs(source, root, text_bytes)
            defs_by_file.append((source, defs, root))
            seen_ids: set[str] = set()
            for d in defs:
                if total >= max_total_symbols:
                    truncated = True
                    break
                node_id = _definition_node_id(source, d)
                if d.kind == "impl_block" or node_id in seen_ids:
                    continue
                seen_ids.add(node_id)
                summary = _definition_summary(source.text, d.line)
                qualified_name = _definition_qualified_name(d)
                if qualified_name:
                    summary = f"{summary} [{qualified_name}]"
                nodes[node_id] = Node(
                    id=node_id,
                    label=d.name,
                    kind=d.kind,
                    path=source.rel,
                    summary=summary,
                    facts=d.facts,
                    source=str(source.path),
                    confidence=self.confidence,
                )
                edges.append(Edge(
                    source.file_node_id,
                    node_id,
                    "contains",
                    confidence=self.confidence,
                    provenance="tree_sitter",
                    source_location=f"{source.rel}:{d.line}",
                ))
                if len(d.name) > 2:
                    name_to_symbols.setdefault(d.name, []).append(node_id)
                total += 1

        _add_tree_sitter_implements(defs_by_file, name_to_symbols, edges, nodes)
        _add_rust_method_owners(defs_by_file, nodes, name_to_symbols, edges)
        _add_nested_contains(defs_by_file, nodes, edges)
        _add_rust_fields(defs_by_file, nodes, edges)
        _add_returns(defs_by_file, nodes, name_to_symbols, edges)
        _add_imports_from(defs_by_file, nodes, name_to_symbols, edges)
        member_call_stats = _add_tree_sitter_calls(defs_by_file, nodes, name_to_symbols, edges)
        _add_rust_type_references(defs_by_file, nodes, name_to_symbols, edges)
        _add_rust_test_field_references(defs_by_file, nodes, edges)
        _add_tree_sitter_callback_references(defs_by_file, nodes, name_to_symbols, edges)

        if fallback_sources:
            remaining = max(0, max_total_symbols - total)
            fallback = RegexExtractor().extract_symbols(
                fallback_sources,
                max_total_symbols=remaining,
                context_nodes=nodes,
            )
            nodes.update(fallback.nodes)
            edges.extend(fallback.edges)
            truncated = truncated or fallback.truncated

        new_nodes = {node_id: node for node_id, node in nodes.items() if node_id not in context_ids}
        frontend = "tree_sitter+regex" if fallback_sources else self.name
        return ExtractionResult(
            nodes=new_nodes,
            edges=dedupe_edges(edges),
            frontend=frontend,
            truncated=truncated,
            fallback_files=tuple(source.rel for source in fallback_sources),
            failed_files=tuple(failed_files),
            unsupported_files=tuple(unsupported_files),
            grammar_errors=tuple(grammar_errors),
            timeout_files=tuple(timeout_files),
            parse_error_files=tuple(parse_error_files),
            resolved_member_calls=member_call_stats.resolved,
            ambiguous_member_calls=member_call_stats.ambiguous,
            unknown_receiver_member_calls=member_call_stats.unknown_receiver,
            unresolved_member_calls=member_call_stats.unresolved,
            unknown_receiver_classes=member_call_stats.unknown_receiver_classes,
        )

def select_extractor(prefer: str = "auto") -> Extractor:
    if prefer == "tree_sitter":
        if not tree_sitter_available():
            raise RuntimeError("tree_sitter is not installed.")
        return TreeSitterExtractor()
    if prefer == "auto" and tree_sitter_available():
        return TreeSitterExtractor(fallback_on_error=True)
    return RegexExtractor()
