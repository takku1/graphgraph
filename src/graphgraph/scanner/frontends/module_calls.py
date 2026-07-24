"""Import-aware resolution of module-qualified calls (``module.func()``).

The member-call resolver types a *variable* receiver (``obj.method()``) and
leaves ``module.func()`` unresolved, because a module is not a typed value. But
the graph already carries the two facts needed to resolve it: an import binds a
local alias to a module, and that module's file already contains the target
symbol. Joining them is a dictionary lookup, and it is the single biggest
caller-recall gap on real Python repos (graybox 2026-07-22, F3).

The join is deliberately conservative. A candidate is accepted only when a
*top-level* symbol of the resolved module file matches the called name, and only
when the module path picks exactly one file. That makes the pass self-correcting:
a call like ``instance.method()`` (where ``instance`` is a class value, not a
module) finds no top-level module symbol and falls through to the receiver-type
resolver untouched, and an ambiguous module name emits nothing rather than a
guess -- the same error direction the whole call-resolution surface protects.
"""
from __future__ import annotations

import re

from .syntax import _identifier, _lang_family

_RESOLVABLE_KINDS = {"function", "method", "class"}
# Bare identifier or a dotted module path (``model_io`` or ``pkg.model_io``).
_MODULE_TOKEN = re.compile(r"[A-Za-z_][\w.]*$")
_PY_IMPORT = re.compile(r"^[ \t]*import[ \t]+([^\n#]+)", re.MULTILINE)
_PY_FROM = re.compile(
    r"^[ \t]*from[ \t]+(\.*[\w.]+)[ \t]+import[ \t]+(?:\(([^)]+)\)|([^\n#]+))",
    re.MULTILINE,
)

_JS_SUFFIXES = frozenset({".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx"})
_JS_SOURCE_SUFFIXES = (".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx")
_ID = r"[A-Za-z_$][\w$]*"
# `const store = require('./store')` -- a CommonJS module binding.
_JS_REQUIRE = re.compile(
    rf"\b(?:const|let|var)\s+({_ID})\s*=\s*require\(\s*['\"]([^'\"]+)['\"]\s*\)"
)
# `import * as util from './util'` -- an ESM namespace binding.
_JS_IMPORT_NS = re.compile(
    rf"\bimport\s+\*\s+as\s+({_ID})\s+from\s+['\"]([^'\"]+)['\"]"
)
# `import cfg from './config'` -- an ESM default binding (whole-module value).
_JS_IMPORT_DEFAULT = re.compile(
    rf"\bimport\s+({_ID})\s+from\s+['\"]([^'\"]+)['\"]"
)


def _js_module_path(spec: str) -> str:
    """A JS import specifier reduced to a dotted, path-suffix-matchable module.

    ``./store`` -> ``store``; ``../lib/format.js`` -> ``lib.format``;
    ``./config/index`` -> ``config``. Relative markers and the file extension
    are dropped so the shared suffix-overlap join can match the target file.
    """
    spec = spec.strip()
    for suffix in _JS_SOURCE_SUFFIXES:
        if spec.endswith(suffix):
            spec = spec[: -len(suffix)]
            break
    parts = [
        segment
        for segment in spec.replace("\\", "/").split("/")
        if segment and segment not in (".", "..")
    ]
    if parts and parts[-1] == "index":
        parts.pop()  # `./store/index` is addressed as `store`
    return ".".join(parts)


def _js_module_alias_targets(text: str) -> dict[str, str]:
    targets: dict[str, str] = {}
    for pattern in (_JS_REQUIRE, _JS_IMPORT_NS, _JS_IMPORT_DEFAULT):
        for alias, spec in pattern.findall(text):
            module = _js_module_path(spec)
            if module and _identifier(alias):
                targets.setdefault(alias, module)
    return targets


def module_alias_targets(suffix: str, text: str) -> dict[str, str]:
    """Map each import-bound local alias to the dotted module path it names.

    ``import model_io`` -> ``{model_io: model_io}``;
    ``import pkg.model_io as mio`` -> ``{mio: pkg.model_io}``;
    ``from pkg import model_io`` -> ``{model_io: pkg.model_io}``.
    """
    if suffix in _JS_SUFFIXES:
        return _js_module_alias_targets(text)
    if suffix != ".py":
        # Other languages can be added here with their own binding rules.
        return {}
    targets: dict[str, str] = {}
    for match in _PY_IMPORT.finditer(text):
        for part in match.group(1).split(","):
            part = part.strip()
            if not part:
                continue
            if " as " in part:
                module, alias = (piece.strip() for piece in part.split(" as ", 1))
                if _MODULE_TOKEN.match(module) and _identifier(alias):
                    targets.setdefault(alias, module)
            elif _MODULE_TOKEN.match(part):
                # `import a.b.c` binds `a`, but the usable call receiver is the
                # full dotted path `a.b.c`; key on the receiver text.
                targets.setdefault(part, part)
    for match in _PY_FROM.finditer(text):
        package = match.group(1).strip(".")  # drop leading dots on relative imports
        body = match.group(2) or match.group(3) or ""
        for part in body.split(","):
            part = part.strip()
            if not part or part == "*":
                continue
            if " as " in part:
                name, alias = (piece.strip() for piece in part.split(" as ", 1))
            else:
                name = alias = part
            if _identifier(name) and _identifier(alias):
                targets.setdefault(alias, f"{package}.{name}" if package else name)
    return targets


def _module_parts(path: str | None) -> list[str]:
    """Dotted module components of a file path: ``pkg/model_io.py`` -> [pkg, model_io]."""
    if not path:
        return []
    normalized = path.replace("\\", "/").rsplit(".", 1)[0]
    parts = [segment for segment in normalized.split("/") if segment]
    if parts and parts[-1] == "__init__":
        parts.pop()  # a package's __init__.py is addressed by the package name
    return parts


def _suffix_overlap(path_parts: list[str], module_parts: list[str]) -> int:
    """Count trailing components shared by a file path and a module path."""
    overlap = 0
    for left, right in zip(reversed(path_parts), reversed(module_parts)):
        if left != right:
            break
        overlap += 1
    return overlap


def resolve_module_qualified_call(
    receiver: str,
    name: str,
    alias_targets: dict[str, str],
    name_to_symbols: dict[str, list[str]],
    nodes,
    source_id: str,
    src_lang: str | None,
) -> str | None:
    """Resolve ``receiver.name()`` to a symbol id, or None to leave it unresolved."""
    module_path = alias_targets.get(receiver)
    if module_path is None:
        return None
    module_parts = [segment for segment in module_path.split(".") if segment]
    if not module_parts:
        return None
    best: str | None = None
    best_score = (-1, 1)
    ambiguous = False
    for symbol_id in name_to_symbols.get(name, ()):
        node = nodes.get(symbol_id)
        if node is None or symbol_id == source_id or node.kind not in _RESOLVABLE_KINDS:
            continue
        if src_lang is not None and _lang_family(node.path) not in (None, src_lang):
            continue
        path_parts = _module_parts(node.path)
        overlap = _suffix_overlap(path_parts, module_parts)
        if overlap == 0:
            continue
        # Rank by how much of the module path matched (an exact `library.model_io`
        # beats a leaf-only `model_io`), then prefer the file whose path IS the
        # module (fewest unmatched leading components), so `import model_io`
        # prefers root `model_io.py` over `deep/pkg/model_io.py`.
        score = (overlap, -(len(path_parts) - overlap))
        if score > best_score:
            best, best_score, ambiguous = symbol_id, score, False
        elif score == best_score:
            ambiguous = True
    if best is None or ambiguous:
        return None
    return best
