from __future__ import annotations

import re
from pathlib import Path


SKIP_DIRS = frozenset({
    ".git", ".svn", ".hg",
    "__pycache__", ".venv", "venv", "env", ".tox", ".mypy_cache",
    ".pytest_cache", ".eggs", "site-packages",
    "node_modules",
    "dist", "build", "out", "target",
    ".graphgraph", ".cache", "coverage", ".next", ".nuxt",
    "archive", "archives", "vendor", "third_party", "third-party", "external",
})

SKIP_SUFFIXES = frozenset({
    ".pyc", ".pyo", ".class", ".o", ".so", ".dll", ".exe",
    ".wasm", ".lock",
})

EXT_KIND: dict[str, str] = {
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

PARSEABLE_SUFFIXES = frozenset({
    ".py", ".ts", ".tsx", ".js", ".jsx",
    ".go", ".rs", ".java", ".cs",
    ".cpp", ".cxx", ".cc", ".c", ".h", ".hpp",
    ".rb", ".php",
    ".md", ".mdx", ".rst", ".html", ".htm",
})

SOURCE_SUFFIXES = frozenset({
    ".py", ".ts", ".tsx", ".js", ".jsx", ".go",
    ".rs", ".java", ".cs", ".cpp", ".cxx", ".cc",
    ".c", ".h", ".hpp", ".rb", ".php", ".swift",
    ".kt", ".scala",
})

DOC_SUFFIXES = frozenset({".md", ".mdx", ".rst", ".html", ".htm", ".txt"})


def node_id(path: Path, root: Path) -> str:
    rel = path.relative_to(root).as_posix()
    return re.sub(r"[^A-Za-z0-9_]", "_", rel)


def collect_files(root: Path, max_nodes: int, extra_skip: frozenset[str] = frozenset()) -> list[Path]:
    skip = SKIP_DIRS | extra_skip
    source: list[Path] = []
    other: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in skip or part.startswith("target") or part.endswith(".egg-info") for part in path.parts):
            continue
        if path.suffix in SKIP_SUFFIXES:
            continue
        suffix_l = path.suffix.lower()
        if suffix_l in DOC_SUFFIXES or path.name.lower() == "readme.md":
            source.insert(0, path)
        elif suffix_l in SOURCE_SUFFIXES:
            source.append(path)
        else:
            other.append(path)
    return (source + other)[:max_nodes]
