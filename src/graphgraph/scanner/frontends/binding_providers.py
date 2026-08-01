"""Uniform local-binding providers for every scanner language.

Language adapters extract facts; they do not resolve graph targets. The shared
``BindingEnvironment`` owns precedence and ambiguity, while ``ScopeGraph``
owns visibility across type/inheritance scopes. Existing language-specific
parsers remain small fact producers behind this registry during migration.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping

from .cpp import cpp_class_field_types, cpp_local_types
from .csharp import csharp_class_field_types, csharp_local_types
from .go import go_local_types
from .model import SourceFile, _TsDef
from .python import _python_class_field_types, _python_local_types, _python_parameter_names
from .rust import (
    _rust_fields_in_range,
    _rust_local_call_return_types,
    _rust_local_types,
)
from .scope_graph import BindingEnvironment
from .type_facts import TypeFact
from .typescript import (
    _ts_class_field_types,
    _ts_local_call_return_types,
    _ts_local_types,
    _ts_parameter_names,
    _ts_this_aliases,
)

LOCAL_BINDING_PRIORITY = 200
FIELD_BINDING_PRIORITY = 100
DIRECT_FIELD_BINDING_PRIORITY = 110
ENCLOSING_INSTANCE_PRIORITY = 300


@dataclass(frozen=True)
class LocalBindingContext:
    """Language-neutral inputs available while resolving one callable."""

    language: str
    body: str
    source_rel: str
    owner: str = ""
    receiver_owner: str = ""
    binds_enclosing_receiver: bool = False
    structural_owners: frozenset[str] = frozenset()
    field_types: Mapping[tuple[str, str], str | TypeFact] = field(
        default_factory=dict
    )
    initial_facts: Mapping[str, TypeFact] = field(default_factory=dict)
    call_return_facts: Mapping[str, TypeFact] = field(default_factory=dict)
    unique_return_types: Mapping[str, str] = field(default_factory=dict)
    call_receiver_types: Mapping[str, str] = field(default_factory=dict)
    unique_fixture_return_types: Mapping[str, str] = field(default_factory=dict)


LocalBindingProvider = Callable[[LocalBindingContext], dict[str, str]]


def _typescript_bindings(context: LocalBindingContext) -> dict[str, str]:
    result = _ts_local_types(context.body)
    for binding, inferred in _ts_local_call_return_types(
        context.body,
        dict(context.unique_return_types),
    ).items():
        result.setdefault(binding, inferred)

    # Structural object owners are module-scoped identities, not global type
    # names. A parameter of the same name shadows the object binding.
    shadowing = (
        _ts_parameter_names(context.body)
        if context.structural_owners
        else set()
    )
    for owner_name in context.structural_owners - shadowing:
        result.setdefault(owner_name, f"{context.source_rel}::{owner_name}")

    if context.binds_enclosing_receiver and context.receiver_owner:
        for alias in _ts_this_aliases(context.body):
            result.setdefault(alias, context.receiver_owner)
    return result


def _rust_bindings(context: LocalBindingContext) -> dict[str, str]:
    result = _rust_local_types(context.body)
    for binding, inferred in _rust_local_call_return_types(
        context.body,
        dict(context.unique_return_types),
    ).items():
        result.setdefault(binding, inferred)
    for binding, inferred in context.call_receiver_types.items():
        result.setdefault(binding, inferred)
    return result


def _python_bindings(context: LocalBindingContext) -> dict[str, str]:
    result = _python_local_types(
        context.body,
        field_types=context.field_types,
        owner=context.owner,
        initial_facts=context.initial_facts,
        call_return_facts=context.call_return_facts,
    )
    normalized = "/" + context.source_rel.replace("\\", "/").casefold()
    if "/tests/" in normalized or Path(context.source_rel).name.casefold().startswith(
        "test_"
    ):
        for parameter in _python_parameter_names(context.body):
            if inferred := context.unique_fixture_return_types.get(parameter):
                result.setdefault(parameter, inferred)
    return result


def _csharp_bindings(context: LocalBindingContext) -> dict[str, str]:
    return csharp_local_types(context.body)


def _cpp_bindings(context: LocalBindingContext) -> dict[str, str]:
    return cpp_local_types(context.body)


def _go_bindings(context: LocalBindingContext) -> dict[str, str]:
    return go_local_types(context.body)


def _empty_local_bindings(_context: LocalBindingContext) -> dict[str, str]:
    return {}

LOCAL_BINDING_PROVIDERS: Mapping[str, LocalBindingProvider] = {
    "c": _empty_local_bindings,
    "cpp": _cpp_bindings,
    "csharp": _csharp_bindings,
    "go": _go_bindings,
    "java": _csharp_bindings,
    "javascript": _typescript_bindings,
    "kotlin": _empty_local_bindings,
    "php": _empty_local_bindings,
    "python": _python_bindings,
    "ruby": _empty_local_bindings,
    "rust": _rust_bindings,
    "scala": _empty_local_bindings,
    "swift": _empty_local_bindings,
    "tsx": _typescript_bindings,
    "typescript": _typescript_bindings,
}


def local_bindings(context: LocalBindingContext) -> BindingEnvironment:
    """Run the registered provider and normalize its output into typed facts."""

    environment = BindingEnvironment()
    provider = LOCAL_BINDING_PROVIDERS.get(context.language, _empty_local_bindings)
    environment.bind_types(
        provider(context),
        evidence_kind=f"{context.language}_local_binding",
        evidence_source=f"{context.source_rel}:{context.owner or '<module>'}",
        priority=LOCAL_BINDING_PRIORITY,
    )
    return environment


@dataclass(frozen=True)
class FieldBindingContext:
    """Inputs available to a language adapter while collecting type fields."""

    source: SourceFile
    definitions: tuple[_TsDef, ...]
    root: Any


FieldBindingProvider = Callable[
    [FieldBindingContext],
    dict[tuple[str, str], str],
]


def _rust_field_bindings(
    context: FieldBindingContext,
) -> dict[tuple[str, str], str]:
    text = context.source.text.encode("utf-8", errors="replace")
    fields: dict[tuple[str, str], str] = {}
    for struct in (
        item for item in context.definitions if item.kind == "struct"
    ):
        for field_name, field_type, _line in _rust_fields_in_range(
            context.root,
            text,
            struct.start,
            struct.end,
        ):
            if field_type:
                fields[(struct.name, field_name)] = field_type
    return fields


def _python_field_bindings(
    context: FieldBindingContext,
) -> dict[tuple[str, str], str]:
    return dict(_python_class_field_types(context.source.text))


def _typescript_field_bindings(
    context: FieldBindingContext,
) -> dict[tuple[str, str], str]:
    return dict(_ts_class_field_types(context.source.text))


def _csharp_field_bindings(
    context: FieldBindingContext,
) -> dict[tuple[str, str], str]:
    return dict(csharp_class_field_types(context.source.text))


def _cpp_field_bindings(
    context: FieldBindingContext,
) -> dict[tuple[str, str], str]:
    return dict(cpp_class_field_types(context.source.text))


def _empty_field_bindings(
    _context: FieldBindingContext,
) -> dict[tuple[str, str], str]:
    return {}


FIELD_BINDING_PROVIDERS: Mapping[str, FieldBindingProvider] = {
    "c": _empty_field_bindings,
    "cpp": _cpp_field_bindings,
    "csharp": _csharp_field_bindings,
    "go": _empty_field_bindings,
    "java": _csharp_field_bindings,
    "javascript": _typescript_field_bindings,
    "kotlin": _empty_field_bindings,
    "php": _empty_field_bindings,
    "python": _python_field_bindings,
    "ruby": _empty_field_bindings,
    "rust": _rust_field_bindings,
    "scala": _empty_field_bindings,
    "swift": _empty_field_bindings,
    "tsx": _typescript_field_bindings,
    "typescript": _typescript_field_bindings,
}


def field_bindings(
    language: str,
    context: FieldBindingContext,
) -> dict[tuple[str, str], str]:
    """Collect field declarations through the uniform language registry."""

    provider = FIELD_BINDING_PROVIDERS.get(language, _empty_field_bindings)
    return provider(context)
