"""Canonical versioned source artifact shared by syntax consumers."""

from __future__ import annotations

import hashlib
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from threading import RLock
from typing import Callable

SOURCE_IR_VERSION = "source_ir_v1"
_MAX_SYNTAX_ARTIFACTS = 512


@dataclass(frozen=True)
class SourceIR:
    """Immutable source bytes and identity for one repository file revision."""

    path: Path
    rel: str
    file_node_id: str
    text: str
    revision: str = field(init=False)
    text_bytes: bytes = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        text_bytes = self.text.encode("utf-8", errors="replace")
        digest = hashlib.sha256()
        digest.update(SOURCE_IR_VERSION.encode("ascii"))
        digest.update(b"\0")
        digest.update(self.path.suffix.casefold().encode("utf-8"))
        digest.update(b"\0")
        digest.update(text_bytes)
        object.__setattr__(self, "text_bytes", text_bytes)
        object.__setattr__(self, "revision", digest.hexdigest())


@dataclass(frozen=True)
class SyntaxIR:
    """Parsed syntax artifact for a specific immutable SourceIR revision."""

    source: SourceIR
    tree: object
    cache_hit: bool


_SYNTAX_CACHE: OrderedDict[tuple[str, str, int], object] = OrderedDict()
_SYNTAX_CACHE_LOCK = RLock()


def compile_syntax_ir(
    source: SourceIR,
    parser: object,
    parse: Callable[[bytes], object | None],
) -> SyntaxIR | None:
    """Parse one source revision once per resident parser and reuse its tree."""
    key = (source.path.suffix.casefold(), source.revision, id(parser))
    with _SYNTAX_CACHE_LOCK:
        tree = _SYNTAX_CACHE.get(key)
        if tree is not None:
            _SYNTAX_CACHE.move_to_end(key)
            return SyntaxIR(source, tree, cache_hit=True)

    tree = parse(source.text_bytes)
    if tree is None:
        return None
    with _SYNTAX_CACHE_LOCK:
        _SYNTAX_CACHE[key] = tree
        _SYNTAX_CACHE.move_to_end(key)
        while len(_SYNTAX_CACHE) > _MAX_SYNTAX_ARTIFACTS:
            _SYNTAX_CACHE.popitem(last=False)
    return SyntaxIR(source, tree, cache_hit=False)


def clear_syntax_ir_cache() -> None:
    """Clear resident syntax artifacts for tests and explicit cache resets."""
    with _SYNTAX_CACHE_LOCK:
        _SYNTAX_CACHE.clear()


__all__ = [
    "SOURCE_IR_VERSION",
    "SourceIR",
    "SyntaxIR",
    "clear_syntax_ir_cache",
    "compile_syntax_ir",
]
