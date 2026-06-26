from __future__ import annotations

import re
from pathlib import Path

from .communities import add_community_nodes
from .core import Edge, Graph, Node
from .doc_scanner import DocumentInput, extract_document_context
from .frontends import SourceFile, select_extractor


# ── language-specific import patterns ──────────────────────────────────────

_PY_FROM = re.compile(r"^from\s+([\w.]+)\s+import", re.MULTILINE)
_PY_BARE = re.compile(r"^import\s+([\w.]+)", re.MULTILINE)

_JS_ES = re.compile(r'(?:import|from)\s+["\'](\.[^"\']+)["\']')
_JS_REQ = re.compile(r'require\s*\(\s*["\'](\.[^"\']+)["\']\s*\)')

_GO_IMPORT = re.compile(r'"(\.[^"]+)"')          # only relative: "./pkg", "../util"

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

# ── file classification ─────────────────────────────────────────────────────

SKIP_DIRS = frozenset({
    # VCS / IDE
    ".git", ".svn", ".hg",
    # Python
    "__pycache__", ".venv", "venv", "env", ".tox", ".mypy_cache",
    ".pytest_cache", ".eggs", "site-packages",
    # JS
    "node_modules",
    # Build output (Rust=target, JS=dist/out, Maven=target)
    "dist", "build", "out", "target",
    # Generated / cache
    ".graphgraph", ".cache", "coverage", ".next", ".nuxt",
    # Archive / legacy (not live source)
    "archive", "archives", "vendor", "third_party", "third-party", "external",
})
SKIP_SUFFIXES = frozenset({
    ".pyc", ".pyo", ".class", ".o", ".so", ".dll", ".exe",
    ".wasm", ".lock",                       # lock files have no useful edges
})

_EXT_KIND: dict[str, str] = {
    ".py": "python", ".ts": "typescript", ".tsx": "tsx",
    ".js": "javascript", ".jsx": "jsx", ".go": "go",
    ".rs": "rust", ".java": "java", ".cs": "csharp",
    ".cpp": "cpp", ".cxx": "cpp", ".cc": "cpp",
    ".c": "c", ".h": "header", ".hpp": "header",
    ".rb": "ruby", ".php": "php", ".swift": "swift",
    ".kt": "kotlin", ".scala": "scala", ".hs": "haskell",
    ".json": "json", ".yaml": "yaml", ".yml": "yaml",
    ".toml": "toml", ".ini": "ini", ".env": "env",
    ".md": "markdown", ".mdx": "markdown", ".rst": "rst",
    ".txt": "text", ".html": "html", ".htm": "html",
    ".xml": "xml", ".csv": "csv", ".sql": "sql",
    ".sh": "shell", ".bash": "shell", ".zsh": "shell",
    ".ps1": "powershell", ".bat": "batch",
    ".tf": "terraform", ".hcl": "hcl",
    ".proto": "protobuf", ".graphql": "graphql",
}

# Suffixes whose files we try to extract explicit edges from
_PARSEABLE = frozenset({
    ".py", ".ts", ".tsx", ".js", ".jsx",
    ".go", ".rs", ".java", ".cs",
    ".cpp", ".cxx", ".cc", ".c", ".h", ".hpp",
    ".rb", ".php",
    ".md", ".mdx", ".rst", ".html", ".htm",
})

_SOURCE_EXTS = frozenset({
    ".py", ".ts", ".tsx", ".js", ".jsx", ".go",
    ".rs", ".java", ".cs", ".cpp", ".cxx", ".cc",
    ".c", ".h", ".hpp", ".rb", ".php", ".swift",
    ".kt", ".scala",
})


# ── helpers ─────────────────────────────────────────────────────────────────

def _node_id(path: Path, root: Path) -> str:
    rel = path.relative_to(root).as_posix()
    return re.sub(r"[^A-Za-z0-9_]", "_", rel)


def _collect_files(root: Path, max_nodes: int, extra_skip: frozenset[str] = frozenset()) -> list[Path]:
    skip = SKIP_DIRS | extra_skip
    source: list[Path] = []
    other: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        # skip any path component that matches a skip dir OR starts with "target" (Rust build variants)
        if any(part in skip or part.startswith("target") or part.endswith(".egg-info")
               for part in path.parts):
            continue
        if path.suffix in SKIP_SUFFIXES:
            continue
        (source if path.suffix.lower() in _SOURCE_EXTS else other).append(path)
    return (source + other)[:max_nodes]


# ── per-language resolvers ───────────────────────────────────────────────────

def _resolve_py(module: str, current: Path, root: Path, file_map: dict[str, str]) -> str | None:
    parts = module.split(".")
    candidates = ["/".join(parts) + ".py", "/".join(parts) + "/__init__.py"]
    for c in candidates:
        if c in file_map:
            return file_map[c]
    pkg = list(current.relative_to(root).parent.parts)
    for c in candidates:
        rel = "/".join(pkg + [c]) if pkg else c
        if rel in file_map:
            return file_map[rel]
    return None


def _resolve_relative(import_path: str, current: Path, root: Path, file_map: dict[str, str],
                       extra_exts: tuple[str, ...] = ()) -> str | None:
    if not import_path.startswith("."):
        return None
    try:
        base = (current.parent / import_path).resolve().relative_to(root).as_posix()
    except ValueError:
        return None
    candidates = [base] + [base + ext for ext in extra_exts]
    for c in candidates:
        if c in file_map:
            return file_map[c]
    return None


_JS_EXTS = (".ts", ".tsx", ".js", ".jsx", "/index.ts", "/index.js")


def _resolve_js(path: str, current: Path, root: Path, file_map: dict[str, str]) -> str | None:
    return _resolve_relative(path, current, root, file_map, extra_exts=_JS_EXTS)


def _resolve_rust_mod(mod_name: str, current: Path, root: Path, file_map: dict[str, str]) -> str | None:
    # Rust: `mod foo;` looks for foo.rs or foo/mod.rs sibling
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
    # Java/C#/Kotlin: last segment of the import is the class name → find <ClassName>.java etc.
    filename = class_name.split(".")[-1] + suffix
    for rel, nid in file_map.items():
        if rel.endswith("/" + filename) or rel == filename:
            return nid
    return None


def _resolve_c_include(include: str, current: Path, root: Path, file_map: dict[str, str]) -> str | None:
    # `#include "relative/path.h"` — look relative to current file first, then root
    for base in (current.parent, root):
        try:
            rel = (base / include).resolve().relative_to(root).as_posix()
        except ValueError:
            continue
        if rel in file_map:
            return file_map[rel]
    return None


# ── generic filename-mention fallback ───────────────────────────────────────

def _mentions(text: str, file_map: dict[str, str]) -> list[str]:
    """Return node IDs for any other file whose stem appears verbatim in text."""
    found = []
    for rel, nid in file_map.items():
        stem = Path(rel).stem
        if len(stem) < 3:          # skip tiny names like 'a', 'io'
            continue
        if re.search(r"\b" + re.escape(stem) + r"\b", text):
            found.append(nid)
    return found


# ── main entry point ─────────────────────────────────────────────────────────

def scan_directory(
    root: Path,
    max_nodes: int = 500,
    generic_mentions: bool = False,
    skip_dirs: list[str] | None = None,
    depth: str = "files",
    frontend: str = "auto",
    docs: bool = False,
    communities: bool = False,
    previous_graph_path: Path | None = None,
    manifest_path: Path | None = None,
) -> Graph:
    """Scan *root* and build a Graph of file-level (and optionally symbol-level) nodes.

    Handles: Python, JS/TS, Go, Rust, Java, C#, C/C++, Ruby,
             Markdown links, RST includes, HTML hrefs.

    Args:
        root: Directory to scan.
        max_nodes: Maximum number of file nodes to collect.
        generic_mentions: If True, also add weak "references" edges from any
            non-parseable text file that mentions another file's stem name.
        skip_dirs: Additional directory names to skip (beyond built-in SKIP_DIRS).
        depth: "files" (default) → one node per file;
               "symbols" → file nodes + function/class/struct nodes with call edges.
        frontend: "auto" prefers Tree-sitter when available and falls back to
            regex; "tree_sitter" requires Tree-sitter; "regex" forces baseline.
        docs: Extract document sections/concepts from Markdown/RST/HTML/text.
        communities: Add deterministic path/scope community summary nodes.
        previous_graph_path: Path to the existing graph JSON/GG file.
        manifest_path: Path to the manifest JSON file.
    """
    root = root.resolve()
    extra_skip = frozenset(skip_dirs) if skip_dirs else frozenset()
    files = _collect_files(root, max_nodes, extra_skip)

    file_map: dict[str, str] = {}   # rel_posix -> node_id
    for f in files:
        rel = f.relative_to(root).as_posix()
        nid = _node_id(f, root)
        file_map[rel] = nid

    nodes: dict[str, Node] = {}
    edges: list[Edge] = []
    seen: set[tuple[str, str]] = set()

    # Load manifest and previous graph if available and paths are provided
    from .manifest import Manifest, compute_file_hash
    from .io import load_any

    manifest = None
    previous_graph = None
    if manifest_path and previous_graph_path:
        manifest = Manifest.load(manifest_path)
        if previous_graph_path.exists():
            try:
                previous_graph = load_any(previous_graph_path)
            except Exception:
                previous_graph = None

    skipped_files: list[tuple[Path, str, str]] = []
    dirty_files: list[tuple[Path, str, str]] = []

    if manifest and previous_graph:
        for f in files:
            rel = f.relative_to(root).as_posix()
            info = manifest.get_file_info(rel)
            current_hash = compute_file_hash(f)
            if (info and info.get("hash") == current_hash and
                info.get("depth") == depth and
                info.get("frontend") == frontend and
                info.get("docs") == docs and
                info.get("communities") == communities):
                skipped_files.append((f, rel, current_hash))
            else:
                dirty_files.append((f, rel, current_hash))
    else:
        for f in files:
            rel = f.relative_to(root).as_posix()
            current_hash = compute_file_hash(f)
            dirty_files.append((f, rel, current_hash))

    active_rels = {f.relative_to(root).as_posix() for f in files}

    # Helper to determine owning file path of any node ID (for edge mapping)
    def find_file_for_node(node_id: str) -> str | None:
        if node_id in nodes:
            return nodes[node_id].path
        # fallback: check file_map
        for rel, nid in file_map.items():
            if nid == node_id:
                return rel
        return None

    # Load skipped nodes and edges
    for f, rel, fhash in skipped_files:
        info = manifest.get_file_info(rel)
        for nid in info.get("nodes", []):
            if nid in previous_graph.nodes:
                nodes[nid] = previous_graph.nodes[nid]
        for src, tgt, etype in info.get("edges", []):
            matching_edge = None
            for pe in previous_graph.edges:
                if pe.source == src and pe.target == tgt and pe.type == etype:
                    matching_edge = pe
                    break
            if matching_edge:
                edges.append(matching_edge)
                seen.add((src, tgt))
            else:
                edges.append(Edge(source=src, target=tgt, type=etype))
                seen.add((src, tgt))

    # Create file nodes for dirty files
    for f, rel, fhash in dirty_files:
        nid = file_map[rel]
        nodes[nid] = Node(
            id=nid,
            label=f.name,
            kind=_EXT_KIND.get(f.suffix.lower(), "file"),
            path=rel,
        )

    # Scans dirty files for imports
    def add_edge(src: str, tgt: str | None, etype: str = "imports") -> None:
        if tgt and tgt != src:
            key = (src, tgt)
            if key not in seen:
                seen.add(key)
                provenance = "regex_reference" if etype in {"references", "links", "includes"} else "regex_import"
                confidence = 0.45 if etype == "references" else 0.85
                edges.append(Edge(source=src, target=tgt, type=etype, weight=1.0, confidence=confidence, provenance=provenance))

    for f, rel, fhash in dirty_files:
        suffix = f.suffix.lower()
        src_id = file_map[rel]

        if suffix not in _PARSEABLE:
            if generic_mentions:
                try:
                    text = f.read_text(encoding="utf-8", errors="replace")
                    for tgt in _mentions(text, file_map):
                        add_edge(src_id, tgt, "references")
                except Exception:
                    pass
            continue

        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue

        if suffix == ".py":
            for m in _PY_FROM.finditer(text):
                add_edge(src_id, _resolve_py(m.group(1), f, root, file_map))
            for m in _PY_BARE.finditer(text):
                add_edge(src_id, _resolve_py(m.group(1), f, root, file_map))

        elif suffix in {".ts", ".tsx", ".js", ".jsx"}:
            for m in _JS_ES.finditer(text):
                add_edge(src_id, _resolve_js(m.group(1), f, root, file_map))
            for m in _JS_REQ.finditer(text):
                add_edge(src_id, _resolve_js(m.group(1), f, root, file_map))

        elif suffix == ".go":
            for m in _GO_IMPORT.finditer(text):
                add_edge(src_id, _resolve_relative(m.group(1), f, root, file_map, extra_exts=(".go",)))

        elif suffix == ".rs":
            for m in _RUST_MOD.finditer(text):
                add_edge(src_id, _resolve_rust_mod(m.group(1), f, root, file_map))
            for m in _RUST_USE.finditer(text):
                parts = m.group(1).replace("::", "/")
                add_edge(src_id, _resolve_relative("./" + parts, f, root, file_map, extra_exts=(".rs", "/mod.rs")))

        elif suffix == ".java":
            for m in _JAVA_IMPORT.finditer(text):
                add_edge(src_id, _resolve_by_class_name(m.group(1), ".java", file_map), "imports")

        elif suffix == ".cs":
            for m in _CS_USING.finditer(text):
                add_edge(src_id, _resolve_by_class_name(m.group(1), ".cs", file_map), "imports")

        elif suffix in {".c", ".cpp", ".cxx", ".cc", ".h", ".hpp"}:
            for m in _C_INCLUDE_LOCAL.finditer(text):
                add_edge(src_id, _resolve_c_include(m.group(1), f, root, file_map))

        elif suffix == ".rb":
            for m in _RUBY_REQ_REL.finditer(text):
                add_edge(src_id, _resolve_relative("./" + m.group(1), f, root, file_map, extra_exts=(".rb",)))
            for m in _RUBY_REQ.finditer(text):
                add_edge(src_id, _resolve_relative(m.group(1), f, root, file_map, extra_exts=(".rb",)))

        elif suffix in {".md", ".mdx"}:
            for m in _MD_LINK.finditer(text):
                add_edge(src_id, _resolve_relative(m.group(1), f, root, file_map), "links")

        elif suffix == ".rst":
            for m in _RST_INCLUDE.finditer(text):
                add_edge(src_id, _resolve_relative("./" + m.group(1), f, root, file_map), "includes")

        elif suffix in {".html", ".htm"}:
            for m in _HTML_HREF.finditer(text):
                add_edge(src_id, _resolve_relative(m.group(1), f, root, file_map), "links")

    metadata = {
        "scan_depth": depth,
        "frontend": "files",
        "docs": str(bool(docs)).lower(),
        "communities": str(bool(communities)).lower(),
    }

    if depth == "symbols" and dirty_files:
        source_files: list[SourceFile] = []
        for f, rel, fhash in dirty_files:
            suffix = f.suffix.lower()
            if suffix not in _PARSEABLE:
                continue
            file_nid = file_map[rel]
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            source_files.append(SourceFile(f, rel, file_nid, text))

        if source_files:
            max_syms = max(500, max_nodes * 5)
            extraction = select_extractor(frontend).extract_symbols(source_files, max_total_symbols=max_syms)
            metadata["frontend"] = extraction.frontend
            nodes.update(extraction.nodes)
            existing = {(e.source, e.target, e.type) for e in edges}
            for e in extraction.edges:
                key = (e.source, e.target, e.type)
                if key not in existing:
                    existing.add(key)
                    edges.append(e)

    if docs and dirty_files:
        doc_inputs: list[DocumentInput] = []
        for f, rel, fhash in dirty_files:
            if f.suffix.lower() not in {".md", ".mdx", ".rst", ".html", ".htm", ".txt"}:
                continue
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            doc_inputs.append(DocumentInput(f, rel, file_map[rel], text))
        if doc_inputs:
            doc_nodes, doc_edges = extract_document_context(doc_inputs, file_map)
            nodes.update(doc_nodes)
            existing = {(e.source, e.target, e.type) for e in edges}
            for e in doc_edges:
                key = (e.source, e.target, e.type)
                if key not in existing:
                    existing.add(key)
                    edges.append(e)

    # Update manifest for the scanned (dirty) files
    if manifest:
        # Clean up deleted files from manifest
        keys_to_delete = [k for k in manifest.files if k not in active_rels]
        for k in keys_to_delete:
            del manifest.files[k]

        for f, rel, fhash in dirty_files:
            file_nodes = [nid for nid, node in nodes.items() if find_file_for_node(nid) == rel]
            file_edges = [(e.source, e.target, e.type) for e in edges if find_file_for_node(e.source) == rel]
            manifest.update_file(
                rel_path=rel,
                file_hash=fhash,
                depth=depth,
                frontend=frontend,
                docs=docs,
                communities=communities,
                nodes=file_nodes,
                edges=file_edges,
            )
        manifest.save(manifest_path)

    graph = Graph(nodes=nodes, edges=edges, metadata=metadata)
    if communities:
        graph = add_community_nodes(graph)
        graph.metadata["communities"] = "path"
    return graph
