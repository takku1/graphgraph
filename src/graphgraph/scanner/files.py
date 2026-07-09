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
    "graphify-out", ".code-review-graph",
    "archive", "archives", "vendor", "third_party", "third-party", "external",
    "tmp", "temp", "temporary", "scratch",
    # Generated agent/run artifacts should not feed back into future answers.
    "evidence", "artifacts", ".artifacts", "run_outputs", "run-output", "run-outputs",
    # Common names for cloned/vendored external repos that should never pollute the graph
    "repos", "references", "references_temp", "reference", "ref", "deps",
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
    ".lean": "lean",
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
    ".rb", ".php", ".kt", ".scala", ".swift", ".lean",
    ".md", ".mdx", ".rst", ".html", ".htm",
})

SOURCE_SUFFIXES = frozenset({
    ".py", ".ts", ".tsx", ".js", ".jsx", ".go",
    ".rs", ".java", ".cs", ".cpp", ".cxx", ".cc",
    ".c", ".h", ".hpp", ".rb", ".php", ".swift",
    ".kt", ".scala", ".lean",
})

DOC_SUFFIXES = frozenset({".md", ".mdx", ".rst", ".html", ".htm", ".txt"})


def node_id(path: Path, root: Path) -> str:
    rel = path.relative_to(root).as_posix()
    return re.sub(r"[^A-Za-z0-9_]", "_", rel)


def find_pruned_dirs(root: Path, skip: frozenset[str]) -> set[str]:
    """Return names of *skip*-listed directories under *root* that hold entries.

    Used to warn that real content was excluded by a default skip rule (e.g. a
    project directory literally named ``build``) instead of dropping it silently.
    """
    import os

    pruned: set[str] = set()
    for dirpath, dirnames, _filenames in os.walk(root):
        kept = []
        for d in dirnames:
            if d in skip or d.startswith("target") or d.endswith(".egg-info"):
                try:
                    if any(Path(dirpath, d).iterdir()):
                        pruned.add(d)
                except OSError:
                    pass
            else:
                kept.append(d)
        dirnames[:] = kept  # do not descend into skipped directories
    return pruned


def collect_files(
    root: Path,
    max_nodes: int,
    extra_skip: frozenset[str] = frozenset(),
    git_staged: set[str] | None = None,
    include: frozenset[str] = frozenset(),
) -> list[Path]:
    """Collect files from *root*, honouring skip rules.

    Priority order (highest first):
      1. Git-staged / modified source files (they are the active work)
      2. All other source files (code then docs then other)

    Files inside directories listed in *extra_skip* or the built-in SKIP_DIRS
    are ignored.  A directory is also skipped when any path component matches
    the pattern ``target*`` or ends with ``.egg-info``.
    """
    skip = (SKIP_DIRS | extra_skip) - include
    priority_files: list[Path] = []   # staged / git-modified
    code_files: list[Path] = []
    doc_files: list[Path] = []
    other_files: list[Path] = []

    staged_posix: set[str] = git_staged or set()

    for path in sorted(root.rglob("*"), key=lambda p: p.as_posix()):
        if not path.is_file():
            continue
        # Only components *within* the scanned tree count against skip rules.
        # Checking the absolute path's parts would skip everything whenever
        # any ancestor directory (e.g. a checkout under ~/repos/myproject or
        # /tmp/anything) happens to share a name with a skip-listed dir.
        parts = path.relative_to(root).parts
        if any(
            part in skip
            or part.startswith("target")
            or part.endswith(".egg-info")
            for part in parts
        ):
            continue
        if path.suffix in SKIP_SUFFIXES:
            continue
        suffix_l = path.suffix.lower()
        rel = path.relative_to(root).as_posix()
        if rel in staged_posix:
            priority_files.append(path)
        elif suffix_l in SOURCE_SUFFIXES:
            code_files.append(path)
        elif suffix_l in DOC_SUFFIXES or path.name.lower() == "readme.md":
            doc_files.append(path)
        else:
            other_files.append(path)

    ordered = priority_files + code_files + doc_files + other_files
    return ordered[:max_nodes]
