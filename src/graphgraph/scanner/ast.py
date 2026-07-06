"""Symbol-level extraction for common languages.

Extracts function/class/struct/trait/enum definitions and builds cross-file
call/reference edges. No AST library required — regex-based, good enough for
graph-level analysis (blast radius, subsystem summaries).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from ..core import Edge, Node

MAX_REFERENCE_PATTERN_NAMES = 5000


# ── definition patterns per language ────────────────────────────────────────

# Existing regex patterns retained for non-AST fallback (unused for .py now)
_PY_CLASS = re.compile(r"^class\s+(\w+)", re.MULTILINE)
_PY_DEF = re.compile(r"^(    )?(?:async\s+)?def\s+(\w+)\s*\(", re.MULTILINE)

_RUST_FN = re.compile(
    r"^\s*(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?fn\s+(\w+)\s*[<(]", re.MULTILINE
)
_RUST_STRUCT = re.compile(
    r"^\s*(?:pub(?:\([^)]*\))?\s+)?struct\s+(\w+)", re.MULTILINE
)
_RUST_ENUM = re.compile(
    r"^\s*(?:pub(?:\([^)]*\))?\s+)?enum\s+(\w+)", re.MULTILINE
)
_RUST_TRAIT = re.compile(
    r"^\s*(?:pub(?:\([^)]*\))?\s+)?trait\s+(\w+)", re.MULTILINE
)
_RUST_IMPL_FOR = re.compile(
    r"^\s*impl\s*(?:<[^>]*>\s*)?(?:(\w+)\s+for\s+)?(\w+)", re.MULTILINE
)

_JS_CLASS = re.compile(r"^(?:export\s+)?(?:default\s+)?class\s+(\w+)", re.MULTILINE)
_JS_FUNC = re.compile(
    r"^(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+(\w+)\s*\(", re.MULTILINE
)
_JS_ARROW = re.compile(
    r"^(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?\(?", re.MULTILINE
)

_GO_FUNC = re.compile(
    r"^func\s+(?:\([^)]+\)\s+)?(\w+)\s*\(", re.MULTILINE
)
_GO_TYPE = re.compile(
    r"^type\s+(\w+)\s+(?:struct|interface)\s*\{", re.MULTILINE
)

_JAVA_CLASS = re.compile(
    r"(?:public|private|protected|abstract|final|\s)+class\s+(\w+)", re.MULTILINE
)
_JAVA_METHOD = re.compile(
    r"(?:public|private|protected|static|final|synchronized|native|abstract|\s)+"
    r"(?:[\w<>\[\]]+\s+)(\w+)\s*\([^)]*\)\s*(?:throws[^{]*)?\{",
    re.MULTILINE,
)

_CS_CLASS = re.compile(
    r"(?:public|private|protected|internal|abstract|sealed|\s)+class\s+(\w+)",
    re.MULTILINE,
)
_CS_METHOD = re.compile(
    r"(?:public|private|protected|internal|static|virtual|override|async|\s)+"
    r"(?:[\w<>\[\]?]+\s+)(\w+)\s*\([^)]*\)\s*\{",
    re.MULTILINE,
)

_C_FUNC = re.compile(
    r"^(?:static\s+|extern\s+|inline\s+)?[\w*]+\s+\**(\w+)\s*\([^;{]*\)\s*\{",
    re.MULTILINE,
)

_LEAN_DEF = re.compile(
    r"^\s*(?:@\[[^\]]*\]\s*)*(private|protected|noncomputable|partial|scoped|local)?\s*"
    r"(def|theorem|lemma|inductive|structure|class|abbrev|opaque|axiom)\s+"
    r"([a-zA-Z_0-9.?!'«»]+)",
    re.MULTILINE
)


# ── identifier reference pattern (used for call detection) ───────────────────

def _limited_name_alternation(names: list[str], *, word_boundaries: bool) -> str | None:
    if not names:
        return None
    escaped = sorted(set(names), key=len, reverse=True)
    terms = [re.escape(n) for n in escaped[:MAX_REFERENCE_PATTERN_NAMES]]
    if word_boundaries:
        terms = [r"\b" + term + r"\b" for term in terms]
    return "|".join(terms)


def _call_pattern(names: list[str]) -> re.Pattern[str] | None:
    pat = _limited_name_alternation(names, word_boundaries=True)
    if pat is None:
        return None
    return re.compile(pat)


def _callsite_pattern(names: list[str]) -> re.Pattern[str] | None:
    pat = _limited_name_alternation(names, word_boundaries=False)
    if pat is None:
        return None
    # Match function calls, optionally qualified (e.g., module.func())
    # Use a negative lookbehind to allow a preceding dot for qualified names.
    return re.compile(r"(?<!\.)\b(" + pat + r")\b\s*(?:!|::)?\s*\(")


# ── symbol extraction per language ───────────────────────────────────────────

@dataclass
class SymbolDef:
    name: str
    kind: str
    line: int
    start: int = 0
    modifier: str | None = None


def _defs_py_ast(text: str) -> list[SymbolDef]:
    """Extract Python symbols using the built‑in ``ast`` module.

    Provides accurate line numbers and avoids false positives from regex.
    """
    import ast
    defs: list[SymbolDef] = []
    try:
        tree = ast.parse(text)
    except Exception:
        return []

    # Attach parent references for method detection.
    for n in ast.walk(tree):
        for child in ast.iter_child_nodes(n):
            setattr(child, "parent", n)

    class Visitor(ast.NodeVisitor):
        def generic_visit(self, node):
            super().generic_visit(node)

        def visit_ClassDef(self, node: ast.ClassDef):
            defs.append(SymbolDef(node.name, "class", node.lineno, node.col_offset))
            self.generic_visit(node)

        def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef):
            kind = "method" if isinstance(getattr(node, "parent", None), ast.ClassDef) else "function"
            defs.append(SymbolDef(node.name, kind, node.lineno, node.col_offset))
            self.generic_visit(node)

        def visit_FunctionDef(self, node: ast.FunctionDef):
            self._visit_function(node)

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
            self._visit_function(node)

    Visitor().visit(tree)
    return defs


def _defs_rust(text: str) -> list[SymbolDef]:
    defs: list[SymbolDef] = []
    for m in _RUST_STRUCT.finditer(text):
        defs.append(SymbolDef(m.group(1), "struct", text[:m.start()].count("\n") + 1, m.start()))
    for m in _RUST_ENUM.finditer(text):
        defs.append(SymbolDef(m.group(1), "enum", text[:m.start()].count("\n") + 1, m.start()))
    for m in _RUST_TRAIT.finditer(text):
        defs.append(SymbolDef(m.group(1), "trait", text[:m.start()].count("\n") + 1, m.start()))
    for m in _RUST_FN.finditer(text):
        defs.append(SymbolDef(m.group(1), "function", text[:m.start()].count("\n") + 1, m.start()))
    # impl X for Y → add "implements" relationship; we store as a special pseudo-def
    for m in _RUST_IMPL_FOR.finditer(text):
        trait_name, type_name = m.group(1), m.group(2)
        if trait_name:
            # impl Trait for Struct → record as a marker so we can wire an edge
            defs.append(SymbolDef(f"impl_{trait_name}_for_{type_name}", "impl_block",
                                   text[:m.start()].count("\n") + 1, m.start()))
    return defs


def _defs_js(text: str) -> list[SymbolDef]:
    defs: list[SymbolDef] = []
    for m in _JS_CLASS.finditer(text):
        defs.append(SymbolDef(m.group(1), "class", text[:m.start()].count("\n") + 1, m.start()))
    for m in _JS_FUNC.finditer(text):
        defs.append(SymbolDef(m.group(1), "function", text[:m.start()].count("\n") + 1, m.start()))
    # only capture arrow functions that look like non-trivial declarations
    for m in _JS_ARROW.finditer(text):
        name = m.group(1)
        if not name[0].isupper():  # skip CONSTANT_CASE etc.
            defs.append(SymbolDef(name, "function", text[:m.start()].count("\n") + 1, m.start()))
    return defs


def _defs_by_patterns(text: str, patterns: list[tuple[re.Pattern[str], str]]) -> list[SymbolDef]:
    defs: list[SymbolDef] = []
    for pattern, kind in patterns:
        for m in pattern.finditer(text):
            defs.append(SymbolDef(m.group(1), kind, text[:m.start()].count("\n") + 1, m.start()))
    return defs


def _defs_go(text: str) -> list[SymbolDef]:
    return _defs_by_patterns(text, [(_GO_TYPE, "struct"), (_GO_FUNC, "function")])


def _defs_java(text: str) -> list[SymbolDef]:
    return _defs_by_patterns(text, [(_JAVA_CLASS, "class"), (_JAVA_METHOD, "method")])


def _defs_cs(text: str) -> list[SymbolDef]:
    return _defs_by_patterns(text, [(_CS_CLASS, "class"), (_CS_METHOD, "method")])


def _defs_c(text: str) -> list[SymbolDef]:
    defs: list[SymbolDef] = []
    for m in _C_FUNC.finditer(text):
        name = m.group(1)
        if len(name) > 2 and not name.startswith("if") and not name.startswith("for"):
            defs.append(SymbolDef(name, "function", text[:m.start()].count("\n") + 1, m.start()))
    return defs


def _defs_lean(text: str) -> list[SymbolDef]:
    defs: list[SymbolDef] = []
    for m in _LEAN_DEF.finditer(text):
        modifier = m.group(1)
        keyword = m.group(2)
        name = m.group(3)
        kind = {
            "def": "function",
            "theorem": "theorem",
            "lemma": "theorem",
            "inductive": "inductive",
            "structure": "structure",
            "class": "class",
            "abbrev": "abbrev",
            "opaque": "opaque",
            "axiom": "axiom",
        }.get(keyword, "function")
        defs.append(SymbolDef(name, kind, text[:m.start()].count("\n") + 1, m.start(), modifier=modifier))
    return defs


_EXTRACTORS: dict[str, callable] = {
    ".py": _defs_py_ast,  # Use AST‑based extraction for Python files.
    ".rs": _defs_rust,
    ".ts": _defs_js,
    ".tsx": _defs_js,
    ".js": _defs_js,
    ".jsx": _defs_js,
    ".go": _defs_go,
    ".java": _defs_java,
    ".cs": _defs_cs,
    ".c": _defs_c,
    ".cpp": _defs_c,
    ".cxx": _defs_c,
    ".cc": _defs_c,
    ".h": _defs_c,
    ".hpp": _defs_c,
    ".lean": _defs_lean,
}

_NOISE_NAMES = frozenset({
    "main", "new", "init", "test", "get", "set", "run", "start", "stop",
    "create", "delete", "update", "read", "write", "open", "close",
    "true", "false", "None", "null", "undefined", "self", "cls",
    "fmt", "err", "ok", "it", "id", "db",
})

_CALLABLE_KINDS = frozenset({"function", "method"})


# ── public API ───────────────────────────────────────────────────────────────

def extract_symbols(
    files: list[tuple[Path, str, str, str]],  # (path, rel_posix, file_node_id, text)
    max_total_symbols: int = 5000,
    context_nodes: dict[str, Node] | None = None,
) -> tuple[dict[str, Node], list[Edge]]:
    """Extract symbol nodes and edges from a list of (path, rel, file_node_id, text) tuples.

    Returns (new_nodes, new_edges) to be merged into an existing Graph.
    The caller is responsible for de-duplicating against existing nodes.
    """
    # Pass 1 — collect all symbol defs and build name→file maps
    file_defs: list[tuple[str, str, str, list[SymbolDef]]] = []  # (file_node_id, rel, text, defs)
    impl_defs: list[tuple[str, SymbolDef]] = []
    # name → list of (node_id, file_node_id) — for cross-ref lookup
    name_to_symbols: dict[str, list[str]] = {}
    symbol_to_file: dict[str, str] = {}
    symbol_nodes: dict[str, Node] = {}
    all_symbol_nodes: dict[str, Node] = dict(context_nodes or {})
    symbol_edges: list[Edge] = []
    total = 0

    for node_id, node in (context_nodes or {}).items():
        if not _is_context_symbol(node):
            continue
        symbol_to_file[node_id] = _file_node_id_for_path(node.path)
        if node.label not in _NOISE_NAMES and len(node.label) > 2:
            name_to_symbols.setdefault(node.label, []).append(node_id)

    for path, rel, file_nid, text in files:
        suffix = path.suffix.lower()
        extractor = _EXTRACTORS.get(suffix)
        if not extractor:
            continue
        try:
            defs = extractor(text)
        except Exception:
            continue
        # deduplicate within file
        seen_names: set[str] = set()
        unique_defs = []
        for d in defs:
            if d.kind == "impl_block":
                impl_defs.append((file_nid, d))
                continue
            if d.name not in seen_names:
                seen_names.add(d.name)
                unique_defs.append(d)
        unique_defs.sort(key=lambda d: d.start)
        file_defs.append((file_nid, rel, text, unique_defs))
        for d in unique_defs:
            if total >= max_total_symbols:
                break
            sym_id = f"{file_nid}__{d.name}"
            facts = []
            if d.name.startswith("__") and not d.name.endswith("__"):
                facts.append("modifier:private")
            elif d.name.startswith("_"):
                facts.append("modifier:protected")
            elif getattr(d, "modifier", None):
                facts.append(f"modifier:{d.modifier}")
            symbol_nodes[sym_id] = Node(
                id=sym_id,
                label=d.name,
                kind=d.kind,
                path=rel,
                summary=f"L{d.line}",
                facts=tuple(facts),
            )
            all_symbol_nodes[sym_id] = symbol_nodes[sym_id]
            symbol_edges.append(Edge(source=file_nid, target=sym_id, type="contains", weight=1.0, confidence=0.8, provenance="regex_ast"))
            symbol_to_file[sym_id] = file_nid
            if d.name not in _NOISE_NAMES and len(d.name) > 2:
                name_to_symbols.setdefault(d.name, []).append(sym_id)
            total += 1

    # Rust impl Trait for Type edges.
    for file_nid, d in impl_defs:
        marker = d.name
        if not marker.startswith("impl_") or "_for_" not in marker:
            continue
        trait_name, type_name = marker[len("impl_"):].split("_for_", 1)
        trait_ids = name_to_symbols.get(trait_name, [])
        type_ids = name_to_symbols.get(type_name, [])
        for type_id in type_ids:
            for trait_id in trait_ids:
                if type_id != trait_id:
                    symbol_edges.append(Edge(source=type_id, target=trait_id, type="implements", weight=1.0, confidence=0.8, provenance="regex_ast"))

    # Pass 2 — detect symbol-level calls from approximate function/method bodies.
    callable_names = [
        name
        for name, ids in name_to_symbols.items()
        if len(ids) == 1 and all_symbol_nodes[ids[0]].kind in _CALLABLE_KINDS
    ]
    callsite_pat = _callsite_pattern(callable_names)
    if callsite_pat:
        for file_nid, _rel, text, defs in file_defs:
            callable_defs = [d for d in defs if d.kind in _CALLABLE_KINDS]
            for idx, d in enumerate(callable_defs):
                src_id = f"{file_nid}__{d.name}"
                end = callable_defs[idx + 1].start if idx + 1 < len(callable_defs) else len(text)
                body = text[d.start:end]
                for m in callsite_pat.finditer(body):
                    name = m.group(1)
                    for tgt_id in name_to_symbols.get(name, []):
                        if tgt_id != src_id:
                            symbol_edges.append(Edge(source=src_id, target=tgt_id, type="calls", weight=1.0, confidence=0.75, provenance="regex_ast"))

    # Pass 3 — detect cross-file references (name appears in another file's text)
    # Build a set of external-symbol names per file to check against
    all_names = [n for n in name_to_symbols if len(name_to_symbols[n]) == 1]  # unambiguous
    if all_names:
        call_pat = _call_pattern(all_names)
        if call_pat:
            for path, rel, file_nid, text in files:
                for m in call_pat.finditer(text):
                    name = m.group(0)
                    tgt_ids = name_to_symbols.get(name, [])
                    for tgt_id in tgt_ids:
                        # only add cross-file references
                        if symbol_to_file.get(tgt_id) != file_nid:
                            symbol_edges.append(
                                Edge(source=file_nid, target=tgt_id, type="references", weight=0.5, confidence=0.45, provenance="regex_reference")
                            )

    # Deduplicate edges
    seen_edges: set[tuple[str, str, str]] = set()
    deduped: list[Edge] = []
    for e in symbol_edges:
        key = (e.source, e.target, e.type)
        if key not in seen_edges:
            seen_edges.add(key)
            deduped.append(e)

    return symbol_nodes, deduped


def _is_context_symbol(node: Node) -> bool:
    return node.kind not in {"file", "python", "package", "concept", "section", "unknown"} and bool(node.path)


def _file_node_id_for_path(path: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]", "_", path)
