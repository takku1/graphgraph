from __future__ import annotations

import os
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from pathspec import GitIgnoreSpec


@dataclass(frozen=True)
class CollectFilesResult:
    files: list[Path]
    truncated: bool
    total_matched: int
    ignore_files: tuple[str, ...] = ()
    ignored_by_rules: int = 0
    rule_pruned_dirs: tuple[str, ...] = ()
    default_pruned_dirs: tuple[str, ...] = ()


# Single source of truth for the file/symbol collection cap. Previously
# hardcoded independently in cli/parser.py (4x), mcp/server.py (3x), and
# every max_nodes=N default across scanner/core.py and services/native.py --
# they drifted out of sync more than once (found via three separate bugs in
# one session: query --show-stats missing on MCP, validate_packet unable to
# check a graph file, and this literal value inconsistent across surfaces).
# Every caller should reference this constant instead of restating the
# number, so raising/lowering the default is a one-line change.
DEFAULT_SCAN_MAX_NODES = 5000

SKIP_DIRS = frozenset({
    ".git", ".svn", ".hg",
    "__pycache__", ".venv", "venv", "env", ".tox", ".mypy_cache",
    ".pytest_cache", ".eggs", "site-packages",
    "node_modules",
    "dist", "build", "out", "target",
    ".graphgraph", ".cache", "coverage", ".next", ".nuxt",
    "graphify-out", ".code-review-graph",
    # Agent configuration and prompt trees are execution context, not project
    # source. Indexing them makes implementation queries anchor on the tool's
    # own instructions and can expose local MCP configuration.
    ".agents", ".claude", ".codex", ".cursor", ".gemini",
    "archive", "archives", "vendor", "third_party", "third-party", "external",
    "tmp", "temp", "temporary", "scratch",
    # Generated agent/run artifacts should not feed back into future answers.
    "evidence", "artifacts", ".artifacts", "run_outputs", "run-output", "run-outputs",
    # Common names for cloned/vendored external repos that should never pollute the graph
    "repos", "references", "references_temp", "reference", "ref", "deps",
})

SKIP_FILE_NAMES = frozenset({
    ".gitignore", ".ignore",
    ".mcp.json", "mcp.json",
    "agents.md", "claude.md", "gemini.md",
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
    exclude_paths: frozenset[str] = frozenset(),
) -> CollectFilesResult:
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

    # Each ignore file is evaluated relative to its own directory. Applying
    # ancestor specs in order preserves gitignore's last-match-wins behavior,
    # including nested negations, without trying to rewrite patterns.
    ignore_specs: dict[Path, tuple[GitIgnoreSpec, ...]] = {}
    loaded_ignore_files: list[str] = []
    ignored_by_rules = 0
    rule_pruned_dirs: set[str] = set()
    default_pruned_dirs: set[str] = set()

    for dirpath, dirnames, filenames in os.walk(root):
        directory = Path(dirpath)

        specs: list[GitIgnoreSpec] = []
        for ignore_name in (".gitignore", ".ignore"):
            ignore_path = directory / ignore_name
            if not ignore_path.is_file():
                continue
            try:
                specs.append(GitIgnoreSpec.from_lines(ignore_path.read_text(encoding="utf-8", errors="replace").splitlines()))
                loaded_ignore_files.append(ignore_path.relative_to(root).as_posix())
            except OSError:
                continue
        if specs:
            ignore_specs[directory] = tuple(specs)

        kept_dirs: list[str] = []
        for dirname in sorted(dirnames):
            path = directory / dirname
            rel = path.relative_to(root).as_posix()
            if dirname in skip or dirname.startswith("target") or dirname.endswith(".egg-info"):
                default_pruned_dirs.add(rel)
            elif _ignored_by_specs(path, root, ignore_specs, is_dir=True):
                # A directory excluded as a directory cannot have a child
                # re-included by Git ignore semantics unless the directory
                # itself is first unignored. Pruning here preserves negation
                # behavior while avoiding a file-by-file walk of huge corpora.
                rule_pruned_dirs.add(rel)
            else:
                kept_dirs.append(dirname)
        dirnames[:] = kept_dirs
        filenames.sort()

        for filename in filenames:
            path = directory / filename
            if _default_file_skip(filename) or path.suffix.lower() in SKIP_SUFFIXES:
                continue
            if _ignored_by_specs(path, root, ignore_specs):
                ignored_by_rules += 1
                continue
            suffix_l = path.suffix.lower()
            rel = path.relative_to(root).as_posix()
            if rel in exclude_paths:
                continue
            if rel in staged_posix:
                priority_files.append(path)
            elif suffix_l in SOURCE_SUFFIXES:
                code_files.append(path)
            elif suffix_l in DOC_SUFFIXES or path.name.lower() == "readme.md":
                doc_files.append(path)
            else:
                other_files.append(path)

    ordered = priority_files + code_files + doc_files + other_files
    return CollectFilesResult(
        files=ordered[:max_nodes],
        truncated=len(ordered) > max_nodes,
        total_matched=len(ordered),
        ignore_files=tuple(loaded_ignore_files),
        ignored_by_rules=ignored_by_rules,
        rule_pruned_dirs=tuple(sorted(rule_pruned_dirs)),
        default_pruned_dirs=tuple(sorted(default_pruned_dirs)),
    )


def _default_file_skip(filename: str) -> bool:
    lower = filename.lower()
    # Environment files are secret-bearing machine configuration. Examples
    # are excluded too: they add little implementation topology and keeping a
    # single rule avoids accidentally indexing a newly named environment file.
    return lower in SKIP_FILE_NAMES or lower == ".env" or lower.startswith(".env.")


@lru_cache(maxsize=1024)
def _compiled_ignore_spec(ignore_path: str, _mtime_ns: int, _size: int) -> GitIgnoreSpec | None:
    """Compile one ignore file, memoized on its identity and mtime/size.

    Compiling a `.gitignore` allocates one pattern object per line, and
    ``path_ignored_by_rules`` is called once per candidate path -- so a
    freshness sweep over a few dozen paths recompiled the same ancestor
    files hundreds of times (measured: 6,474 pattern objects, ~204ms, the
    single largest cost in a CLI query). Keying on mtime and size means an
    edited ignore file still produces a fresh compile.
    """
    try:
        text = Path(ignore_path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    return GitIgnoreSpec.from_lines(text.splitlines())


def _ignore_specs_for(directory: Path) -> tuple[GitIgnoreSpec, ...]:
    loaded: list[GitIgnoreSpec] = []
    for ignore_name in (".gitignore", ".ignore"):
        ignore_path = directory / ignore_name
        try:
            stat = ignore_path.stat()
        except OSError:
            continue
        spec = _compiled_ignore_spec(str(ignore_path), stat.st_mtime_ns, stat.st_size)
        if spec is not None:
            loaded.append(spec)
    return tuple(loaded)


def path_ignored_by_rules(root: Path, rel_path: str) -> bool:
    """Check one path against ancestor `.gitignore` and `.ignore` files."""
    path = root / rel_path
    specs: dict[Path, tuple[GitIgnoreSpec, ...]] = {}
    directories = [root]
    if path.parent != root:
        parts = path.parent.relative_to(root).parts
        directories.extend(root.joinpath(*parts[:i]) for i in range(1, len(parts) + 1))
    for directory in directories:
        loaded = _ignore_specs_for(directory)
        if loaded:
            specs[directory] = loaded
    return _ignored_by_specs(path, root, specs)


def _ignored_by_specs(
    path: Path,
    root: Path,
    specs: dict[Path, tuple[GitIgnoreSpec, ...]],
    *,
    is_dir: bool = False,
) -> bool:
    ignored = False
    # Path.parents is nearest-first; evaluate root-to-leaf so nested ignore
    # files override parent rules exactly as git does.
    ordered = [root]
    if path.parent != root:
        parts = path.parent.relative_to(root).parts
        ordered.extend(root.joinpath(*parts[:i]) for i in range(1, len(parts) + 1))
    for directory in ordered:
        try:
            relative = path.relative_to(directory).as_posix()
        except ValueError:
            continue
        if is_dir:
            relative = relative.rstrip("/") + "/"
        for spec in specs.get(directory, ()):
            result = spec.check_file(relative)
            if result.include is not None:
                ignored = bool(result.include)
    return ignored
