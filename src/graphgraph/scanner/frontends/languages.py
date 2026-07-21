"""Tree-sitter grammar discovery, parser construction, and frontend capability reporting."""

from __future__ import annotations

import warnings
from importlib import import_module
from importlib.util import find_spec
from typing import Any

from .model import (
    FrontendCapability,
)
from .syntax import (
    _LANGUAGE_CACHE,
    _LANGUAGE_LOAD_ERRORS,
    _PARSER_CACHE,
    _PARSER_LOAD_ERRORS,
)


def _parse_with_timeout(parser: Any, text: bytes, timeout_micros: int) -> Any | None:
    """Parse one file with Tree-sitter's native cancellation boundary.

    ``timeout_micros`` exists in supported py-tree-sitter releases but is
    deprecated in some newer bindings in favour of progress callbacks.  Keep
    the compatibility branch local so a binding without the attribute still
    parses correctly; it simply cannot provide the native timeout guarantee.
    """
    previous_timeout: Any = None
    # py-tree-sitter 0.25 still exposes the only usable parse-cancellation API
    # as ``timeout_micros`` while warning that a future release will replace it
    # with a progress callback. Isolate that compatibility warning here; once
    # the callback lands in the public parse signature this is the only helper
    # that needs to change.
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="Use the progress_callback in parse", category=DeprecationWarning)
        timeout_supported = timeout_micros > 0 and hasattr(parser, "timeout_micros")
        if timeout_supported:
            previous_timeout = parser.timeout_micros
            parser.timeout_micros = timeout_micros
        try:
            return parser.parse(text)
        finally:
            if timeout_supported:
                parser.timeout_micros = previous_timeout

def tree_sitter_available() -> bool:
    return find_spec("tree_sitter") is not None and any(
        _language_available(name)
        for name in ("python", "rust", "javascript", "typescript", "go", "java", "c", "cpp", "csharp")
    )

def available_frontends() -> list[FrontendCapability]:
    languages = tuple(dict.fromkeys(_SUFFIX_LANGUAGE.values()))
    ready = tuple(name for name in languages if _language_available(name))
    unavailable = tuple(name for name in languages if name not in ready)
    return [
        FrontendCapability(
            name="regex",
            available=True,
            confidence=0.75,
            description="Dependency-free baseline extractor for imports, definitions, calls, and weak references.",
        ),
        FrontendCapability(
            name="tree_sitter",
            available=tree_sitter_available(),
            confidence=0.95,
            description="Optional per-language CST frontend; normalizes into graphgraph IR when installed.",
            ready_languages=ready,
            unavailable_languages=unavailable,
        ),
        FrontendCapability(
            name="cpg",
            available=tree_sitter_available(),
            confidence=0.95,
            description="Multi-language control, data, field, and type evidence normalized into GraphGraph IR.",
            ready_languages=ready,
            unavailable_languages=unavailable,
        ),
    ]

_SUFFIX_LANGUAGE = {
    ".py": "python",
    ".rs": "rust",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".go": "go",
    ".java": "java",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".cxx": "cpp",
    ".cc": "cpp",
    ".hpp": "cpp",
    ".cs": "csharp",
    ".rb": "ruby",
    ".php": "php",
    ".kt": "kotlin",
    ".scala": "scala",
    ".swift": "swift",
}

_LANGUAGE_MODULES = {
    "python": ("tree_sitter_python",),
    "rust": ("tree_sitter_rust",),
    "javascript": ("tree_sitter_javascript",),
    "typescript": ("tree_sitter_typescript",),
    "tsx": ("tree_sitter_typescript",),
    "go": ("tree_sitter_go",),
    "java": ("tree_sitter_java",),
    "c": ("tree_sitter_c",),
    "cpp": ("tree_sitter_cpp",),
    "csharp": ("tree_sitter_c_sharp",),
    "ruby": ("tree_sitter_ruby",),
    "php": ("tree_sitter_php",),
    "kotlin": ("tree_sitter_kotlin",),
    "scala": ("tree_sitter_scala",),
    "swift": ("tree_sitter_swift",),
}

def _language_available(name: str) -> bool:
    return _parser_for_language(name) is not None

def _language_for_name(name: str) -> Any | None:
    if name in _LANGUAGE_CACHE:
        return _LANGUAGE_CACHE[name]
    if find_spec("tree_sitter") is None:
        _LANGUAGE_LOAD_ERRORS[name] = "tree_sitter is not installed"
        return None
    try:
        from tree_sitter import Language
    except Exception as exc:
        _LANGUAGE_LOAD_ERRORS[name] = f"{type(exc).__name__}: {exc}"
        return None

    errors: list[str] = []
    if find_spec("tree_sitter_language_pack") is not None:
        try:
            pack = import_module("tree_sitter_language_pack")
            get_language = getattr(pack, "get_language")
            language = get_language("typescript" if name == "tsx" else name)
            _LANGUAGE_CACHE[name] = language
            _LANGUAGE_LOAD_ERRORS.pop(name, None)
            return language
        except Exception as exc:
            errors.append(f"tree_sitter_language_pack: {type(exc).__name__}: {exc}")

    for module_name in _LANGUAGE_MODULES.get(name, ()):
        if find_spec(module_name) is None:
            continue
        try:
            module = import_module(module_name)
            language_obj = module.language()
            try:
                language = Language(language_obj)
            except TypeError:
                language = language_obj
            _LANGUAGE_CACHE[name] = language
            _LANGUAGE_LOAD_ERRORS.pop(name, None)
            return language
        except Exception as exc:
            errors.append(f"{module_name}: {type(exc).__name__}: {exc}")
    _LANGUAGE_LOAD_ERRORS[name] = " | ".join(errors) or "no installed grammar provider"
    return None

def _parser_for_language(name: str) -> Any | None:
    if name in _PARSER_CACHE:
        return _PARSER_CACHE[name]
    language = _language_for_name(name)
    if language is None:
        return None
    try:
        from tree_sitter import Parser
    except Exception as exc:
        _PARSER_LOAD_ERRORS[name] = f"{type(exc).__name__}: {exc}"
        return None
    try:
        parser = Parser()
        if hasattr(parser, "set_language"):
            parser.set_language(language)
        else:
            parser.language = language
    except Exception as exc:
        _PARSER_LOAD_ERRORS[name] = f"{type(exc).__name__}: {exc}"
        return None
    _PARSER_CACHE[name] = parser
    _PARSER_LOAD_ERRORS.pop(name, None)
    return parser

def _parser_for_suffix(suffix: str) -> Any | None:
    name = _SUFFIX_LANGUAGE.get(suffix)
    if not name:
        return None
    return _parser_for_language(name)

def parser_for_suffix(suffix: str) -> Any | None:
    """Return the cached Tree-sitter parser registered for a file suffix."""
    return _parser_for_suffix(suffix.casefold())

def parser_unavailable_reason(suffix: str) -> str:
    """Return the last concrete grammar/parser failure for a source suffix."""
    suffix = suffix.casefold()
    name = _SUFFIX_LANGUAGE.get(suffix)
    if name is None:
        return f"no Tree-sitter language registered for {suffix or '<no suffix>'}"
    return (
        _PARSER_LOAD_ERRORS.get(name)
        or _LANGUAGE_LOAD_ERRORS.get(name)
        or f"{name} grammar is unavailable"
    )

def parse_with_timeout(parser: Any, text: bytes, timeout_micros: int) -> Any | None:
    """Parse bytes through the scanner's shared timeout compatibility layer."""
    return _parse_with_timeout(parser, text, timeout_micros)
