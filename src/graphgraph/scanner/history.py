from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from ..graph.core import Edge, Node

# Bug-fix signal: fix/bug/error/crash/regression/fail/broken, word-bounded, case-insensitive.
BUGFIX_COMMIT_RE = re.compile(
    r"\b(fix(?:e[sd])?|bug|error|crash(?:e[sd])?|regression|fail(?:s|ed|ure)?|broken)\b",
    re.IGNORECASE,
)

# Maintenance/exclusion signal: purely mechanical commits that should never count
# as a "bug fix" even if they happen to contain a bugfix keyword too
# (e.g. "style: fix ruff lint errors" -- excluded because it's a lint/style pass, not a bug fix).
MAINTENANCE_COMMIT_RE = re.compile(
    r"\b(lint(?:ing)?|format(?:ting)?|typo|dependabot|chore|style)\b",
    re.IGNORECASE,
)

_UNIT_SEP = "\x1f"
_COMMIT_PREFIX = "COMMIT "

# git numstat's abbreviated rename syntax, e.g. "src/{old_name.py => new_name.py}"
# or "common/{old => new}/tail.py". Captures the new-name half so the target path
# can be reconstructed with the shared prefix/suffix kept intact.
_RENAME_BRACE_RE = re.compile(r"\{[^{}]*\s=>\s([^{}]*)\}")


@dataclass(frozen=True)
class CommitRecord:
    sha: str
    subject: str
    files: tuple[str, ...]


def _is_bugfix_commit(subject: str) -> bool:
    return bool(BUGFIX_COMMIT_RE.search(subject)) and not MAINTENANCE_COMMIT_RE.search(subject)


def _parse_commit_log_output(raw: str) -> list[CommitRecord]:
    """Pure parser for `git log --numstat --pretty=format:"COMMIT %H\\x1f%s"` output.

    No subprocess calls -- unit-testable directly with canned text.
    """
    records: list[CommitRecord] = []
    sha = ""
    subject = ""
    files: list[str] = []
    started = False

    def _flush() -> None:
        if started:
            records.append(CommitRecord(sha=sha, subject=subject, files=tuple(files)))

    for line in raw.splitlines():
        if line.startswith(_COMMIT_PREFIX):
            _flush()
            header = line[len(_COMMIT_PREFIX):]
            sha, _, subject = header.partition(_UNIT_SEP)
            files = []
            started = True
            continue
        stripped = line.strip("\r\n")
        if not stripped.strip():
            continue
        # numstat lines are tab-separated (added\tremoved\tpath) specifically so
        # they stay machine-parseable even when the path itself contains spaces
        # (e.g. "docs/getting started.md"). Splitting on generic whitespace
        # (str.split()) breaks such paths into multiple tokens and also mangles
        # git's rename syntax ("old => new", or abbreviated
        # "common/{old => new}/tail") the same way, silently dropping the
        # fixes-edge for renamed/space-containing files.
        parts = stripped.split("\t", 2)
        if len(parts) >= 3:
            file_path = _numstat_target_path(parts[2]).replace("\\", "/")
            if file_path:
                files.append(file_path)

    _flush()
    return records


def _numstat_target_path(field: str) -> str:
    """Resolve a numstat path field to the file's current (post-rename) path."""
    field = _RENAME_BRACE_RE.sub(r"\1", field)
    if " => " in field:
        field = field.rsplit(" => ", 1)[1]
    return field.strip()


def extract_commit_history(
    root: Path,
    file_map: dict[str, str],
    max_commits: int = 300,
    max_files_per_commit: int = 20,
) -> tuple[dict[str, Node], list[Edge]]:
    """Link qualifying bug-fix commits (git log, regex-classified) to the files they touched.

    Deterministic: no LLM calls, no embeddings. A commit qualifies only if its subject
    matches BUGFIX_COMMIT_RE and not MAINTENANCE_COMMIT_RE. File linkage comes from
    `git log --numstat`, which is exact ground truth for "this commit touched this file".

    Commits touching more than `max_files_per_commit` files are skipped entirely: a
    targeted bug fix is, in practice, localized to a handful of files, while a commit
    spanning dozens of files is a repo-wide operation (a large refactor, a rename sweep,
    a formatting pass) that happens to mention a bugfix keyword in passing -- keeping it
    would create an artificially high-degree "commit" hub node that dilutes the "fixes"
    relation's precision for downstream ranking. Verified against this repo's own history:
    genuine fix commits cluster at 1-8 touched files; the one outlier at 84 files was a
    "Refactor codebase structure, fix python parenthesized multiline imports..." commit.
    """
    nodes: dict[str, Node] = {}
    edges: list[Edge] = []

    if not (root / ".git").exists():
        return nodes, edges

    try:
        res = subprocess.run(
            [
                "git", "log", "--no-merges", "-n", str(max_commits),
                "--numstat", f"--pretty=format:{_COMMIT_PREFIX}%H{_UNIT_SEP}%s",
            ],
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=5.0,
        )
        if res.returncode != 0:
            return nodes, edges
        records = _parse_commit_log_output(res.stdout)
    except Exception:
        return nodes, edges

    for record in records:
        if not record.sha or not _is_bugfix_commit(record.subject):
            continue
        if len(record.files) > max_files_per_commit:
            continue

        commit_id = f"commit_{record.sha[:8]}"
        nodes[commit_id] = Node(
            id=commit_id,
            label=record.subject[:72],
            kind="commit",
            path="",
            summary=record.subject,
            facts=(f"sha:{record.sha}",),
            source="git_history",
            confidence=1.0,
        )

        seen_targets: set[str] = set()
        for rel in record.files:
            target = file_map.get(rel)
            if target is None or target in seen_targets:
                continue
            seen_targets.add(target)
            edges.append(Edge(
                source=commit_id,
                target=target,
                type="fixes",
                weight=1.0,
                confidence=1.0,
                provenance="git_history",
                source_location=rel,
            ))

    return nodes, edges
