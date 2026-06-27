from __future__ import annotations

import re
from pathlib import Path

from ..core import Edge
from .files import PARSEABLE_SUFFIXES


_PY_FROM = re.compile(r"^from\s+([\w.]+)\s+import", re.MULTILINE)
_PY_BARE = re.compile(r"^import\s+([\w.]+)", re.MULTILINE)
_JS_ES = re.compile(r'(?:import|from)\s+["\'](\.[^"\']+)["\']')
_JS_REQ = re.compile(r'require\s*\(\s*["\'](\.[^"\']+)["\']\s*\)')
_GO_IMPORT = re.compile(r'"(\.[^"]+)"')
_RUST_MOD = re.compile(r"^\s*(?:pub\s+)?mod\s+(\w+)\s*;", re.MULTILINE)
_RUST_USE = re.compile(r"^\s*use\s+(?:crate|self|super)::([\w:]+)", re.MULTILINE)
_JAVA_IMPORT = re.compile(r"^import\s+([\w.]+);", re.MULTILINE)
_CS_USING = re.compile(r"^using\s+([\w.]+);", re.MULTILINE)
_C_INCLUDE_LOCAL = re.compile(r'#include\s+"([^"]+)"')
_RUBY_REQ_REL = re.compile(r"""require_relative\s+['"]([^'"]+)['"]""")
_RUBY_REQ = re.compile(r"""require\s+['"](\.[^'"]+)['"]""")
_MD_LINK = re.compile(r"""\[(?:[^\]]*)\]\((\.[^)#"'\s]+)\)""")
_RST_INCLUDE = re.compile(r"""^\.\.\s+(?:include|literalinclude)::\s+(\S+)""", re.MULTILINE)
_HTML_HREF = re.compile(r"""href=["'](\.[^"'#\s]+)["']""")

_JS_EXTS = (".ts", ".tsx", ".js", ".jsx", "/index.ts", "/index.js")


def add_file_edges(
    *,
    dirty_files: list[tuple[Path, str, str]],
    root: Path,
    file_map: dict[str, str],
    edges: list[Edge],
    seen: set[tuple[str, str]],
    generic_mentions: bool,
) -> None:
    def add_edge(src: str, tgt: str | None, etype: str = "imports") -> None:
        if tgt and tgt != src:
            key = (src, tgt)
            if key not in seen:
                seen.add(key)
                provenance = "regex_reference" if etype in {"references", "links", "includes"} else "regex_import"
                confidence = 0.45 if etype == "references" else 0.85
                edges.append(Edge(source=src, target=tgt, type=etype, weight=1.0, confidence=confidence, provenance=provenance))

    for path, rel, _file_hash in dirty_files:
        suffix = path.suffix.lower()
        src_id = file_map[rel]

        if suffix not in PARSEABLE_SUFFIXES:
            if generic_mentions:
                try:
                    text = path.read_text(encoding="utf-8", errors="replace")
                    for tgt in _mentions(text, file_map):
                        add_edge(src_id, tgt, "references")
                except Exception:
                    pass
            continue

        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue

        if suffix == ".py":
            for match in _PY_FROM.finditer(text):
                add_edge(src_id, _resolve_py(match.group(1), path, root, file_map))
            for match in _PY_BARE.finditer(text):
                add_edge(src_id, _resolve_py(match.group(1), path, root, file_map))
        elif suffix in {".ts", ".tsx", ".js", ".jsx"}:
            for match in _JS_ES.finditer(text):
                add_edge(src_id, _resolve_js(match.group(1), path, root, file_map))
            for match in _JS_REQ.finditer(text):
                add_edge(src_id, _resolve_js(match.group(1), path, root, file_map))
        elif suffix == ".go":
            for match in _GO_IMPORT.finditer(text):
                add_edge(src_id, _resolve_relative(match.group(1), path, root, file_map, extra_exts=(".go",)))
        elif suffix == ".rs":
            for match in _RUST_MOD.finditer(text):
                add_edge(src_id, _resolve_rust_mod(match.group(1), path, root, file_map))
            for match in _RUST_USE.finditer(text):
                parts = match.group(1).replace("::", "/")
                add_edge(src_id, _resolve_relative("./" + parts, path, root, file_map, extra_exts=(".rs", "/mod.rs")))
        elif suffix == ".java":
            for match in _JAVA_IMPORT.finditer(text):
                add_edge(src_id, _resolve_by_class_name(match.group(1), ".java", file_map), "imports")
        elif suffix == ".cs":
            for match in _CS_USING.finditer(text):
                add_edge(src_id, _resolve_by_class_name(match.group(1), ".cs", file_map), "imports")
        elif suffix in {".c", ".cpp", ".cxx", ".cc", ".h", ".hpp"}:
            for match in _C_INCLUDE_LOCAL.finditer(text):
                add_edge(src_id, _resolve_c_include(match.group(1), path, root, file_map))
        elif suffix == ".rb":
            for match in _RUBY_REQ_REL.finditer(text):
                add_edge(src_id, _resolve_relative("./" + match.group(1), path, root, file_map, extra_exts=(".rb",)))
            for match in _RUBY_REQ.finditer(text):
                add_edge(src_id, _resolve_relative(match.group(1), path, root, file_map, extra_exts=(".rb",)))
        elif suffix in {".md", ".mdx"}:
            for match in _MD_LINK.finditer(text):
                add_edge(src_id, _resolve_relative(match.group(1), path, root, file_map), "links")
        elif suffix == ".rst":
            for match in _RST_INCLUDE.finditer(text):
                add_edge(src_id, _resolve_relative("./" + match.group(1), path, root, file_map), "includes")
        elif suffix in {".html", ".htm"}:
            for match in _HTML_HREF.finditer(text):
                add_edge(src_id, _resolve_relative(match.group(1), path, root, file_map), "links")


def _resolve_py(module: str, current: Path, root: Path, file_map: dict[str, str]) -> str | None:
    parts = module.split(".")
    candidates = ["/".join(parts) + ".py", "/".join(parts) + "/__init__.py"]
    for candidate in candidates:
        if candidate in file_map:
            return file_map[candidate]
    pkg = list(current.relative_to(root).parent.parts)
    for candidate in candidates:
        rel = "/".join(pkg + [candidate]) if pkg else candidate
        if rel in file_map:
            return file_map[rel]
    return None


def _resolve_relative(
    import_path: str,
    current: Path,
    root: Path,
    file_map: dict[str, str],
    extra_exts: tuple[str, ...] = (),
) -> str | None:
    if not import_path.startswith("."):
        return None
    try:
        base = (current.parent / import_path).resolve().relative_to(root).as_posix()
    except ValueError:
        return None
    candidates = [base] + [base + ext for ext in extra_exts]
    for candidate in candidates:
        if candidate in file_map:
            return file_map[candidate]
    return None


def _resolve_js(path: str, current: Path, root: Path, file_map: dict[str, str]) -> str | None:
    return _resolve_relative(path, current, root, file_map, extra_exts=_JS_EXTS)


def _resolve_rust_mod(mod_name: str, current: Path, root: Path, file_map: dict[str, str]) -> str | None:
    sibling = current.parent / (mod_name + ".rs")
    mod_rs = current.parent / mod_name / "mod.rs"
    for candidate in (sibling, mod_rs):
        try:
            rel = candidate.resolve().relative_to(root).as_posix()
        except ValueError:
            continue
        if rel in file_map:
            return file_map[rel]
    return None


def _resolve_by_class_name(class_name: str, suffix: str, file_map: dict[str, str]) -> str | None:
    filename = class_name.split(".")[-1] + suffix
    for rel, nid in file_map.items():
        if rel.endswith("/" + filename) or rel == filename:
            return nid
    return None


def _resolve_c_include(include: str, current: Path, root: Path, file_map: dict[str, str]) -> str | None:
    for base in (current.parent, root):
        try:
            rel = (base / include).resolve().relative_to(root).as_posix()
        except ValueError:
            continue
        if rel in file_map:
            return file_map[rel]
    return None


def _mentions(text: str, file_map: dict[str, str]) -> list[str]:
    found = []
    for rel, nid in file_map.items():
        sidebar_stem = Path(rel).stem
        if len(sidebar_stem) < 3:
            continue
        if re.search(r"\b" + re.escape(sidebar_stem) + r"\b", text):
            found.append(nid)
    return found
