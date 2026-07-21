from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from graphgraph import (
    scan_directory,
)


class HistoryScannerTest(unittest.TestCase):
    """scanner/history.py: commit history extraction."""

    def test_scan_directory_filters_ignored_git_paths_from_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".ignore").write_text("packet.json\n", encoding="utf-8")
            (root / "app.py").write_text("x = 1\n", encoding="utf-8")
            (root / "packet.json").write_text("{}\n", encoding="utf-8")
            with patch(
                "graphgraph.scanner.core._get_git_metadata",
                return_value=({"app.py", "packet.json"}, {"app.py": 2, "packet.json": 9}),
            ):
                graph = scan_directory(root)
        self.assertEqual(graph.metadata["git_dirty"], "app.py")
        self.assertNotIn("packet.json", json.dumps(graph.metadata))

    def test_history_bugfix_and_maintenance_classification(self) -> None:
        from graphgraph.scanner.history import _is_bugfix_commit

        # Clear bug fix -> included.
        self.assertTrue(_is_bugfix_commit("fix: cast scanner facts list to tuple to match Node dataclass typing"))
        # Maintenance-only -> excluded (no bugfix keyword at all).
        self.assertFalse(_is_bugfix_commit("chore: remove temporary web search lookup capabilities"))
        # Contains a bugfix keyword AND a maintenance keyword -> excluded by the AND-NOT rule.
        self.assertFalse(_is_bugfix_commit("style: fix ruff lint errors in scanner module"))
        # Neutral feature commit -> excluded (no bugfix keyword).
        self.assertFalse(_is_bugfix_commit("feat: add packet renderer for hybrid format"))

    def test_history_parse_commit_log_output(self) -> None:
        from graphgraph.scanner.history import _parse_commit_log_output

        raw = (
            "COMMIT abc1234567890\x1ffix: handle empty file list\n"
            "2\t1\tsrc/graphgraph/scanner/core.py\n"
            "0\t3\tsrc/graphgraph/scanner/files.py\n"
            "\n"
            "COMMIT def4567890abc\x1fchore: bump dependency versions\n"
            "1\t1\tpyproject.toml\n"
        )
        records = _parse_commit_log_output(raw)
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0].sha, "abc1234567890")
        self.assertEqual(records[0].subject, "fix: handle empty file list")
        self.assertEqual(
            records[0].files,
            ("src/graphgraph/scanner/core.py", "src/graphgraph/scanner/files.py"),
        )
        self.assertEqual(records[1].files, ("pyproject.toml",))

    def test_history_parse_commit_log_output_handles_renames_and_spaces(self) -> None:
        # Regression: numstat lines are tab-separated (added\tremoved\tpath), but
        # the parser used str.split() (whitespace-generic), which silently
        # mis-parses two common real cases:
        #  1. A path containing a space (e.g. "docs/getting started.md") gets
        #     split into multiple tokens, so parts[2] is just "docs/getting"
        #     -- never matches any real file.
        #  2. Git's rename numstat syntax -- "old => new" or an abbreviated
        #     "common/{old => new}/tail" -- also splits on the whitespace
        #     around "=>", so parts[2] becomes a garbled fragment like
        #     "src/{old_name.py" instead of the file's current path, silently
        #     dropping the fixes-edge for every renamed file.
        from graphgraph.scanner.history import _parse_commit_log_output

        raw = (
            "COMMIT abc1234567890\x1ffix: rename and reword docs\n"
            "1\t0\tsrc/{old_name.py => new_name.py}\n"
            "2\t2\tsrc/old_dir/thing.py => other_dir/thing.py\n"
            "1\t1\tdocs/getting started.md\n"
        )
        records = _parse_commit_log_output(raw)
        self.assertEqual(len(records), 1)
        self.assertEqual(
            records[0].files,
            (
                "src/new_name.py",
                "other_dir/thing.py",
                "docs/getting started.md",
            ),
        )

    def test_history_skips_wide_commits_above_file_cap(self) -> None:
        # Found via real-data validation against this repo's own history: a large
        # refactor commit that happened to mention "fix" touched 84 files and would
        # otherwise become an artificially high-degree hub node.
        from graphgraph.scanner.history import extract_commit_history

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".git").mkdir()

            def fake_run(*args, **kwargs):
                class _Result:
                    returncode = 0
                    stdout = (
                        "COMMIT wide0000001\x1frefactor codebase, fix imports along the way\n"
                        + "".join(f"1\t0\tfile{i}.py\n" for i in range(25))
                        + "\nCOMMIT narrow000001\x1ffix: off-by-one in loop\n"
                        "1\t0\tfile0.py\n"
                    )

                return _Result()

            file_map = {f"file{i}.py": f"file_{i}" for i in range(25)}
            with patch("graphgraph.scanner.history.subprocess.run", side_effect=fake_run):
                nodes, edges = extract_commit_history(root, file_map, max_files_per_commit=20)

            self.assertNotIn("commit_wide0000", nodes)
            self.assertIn("commit_narrow00", nodes)
            self.assertEqual(len(edges), 1)

    @unittest.skipUnless(shutil.which("git"), "git binary not available on PATH")
    def test_get_git_metadata_handles_quoted_paths(self) -> None:
        # Regression: _get_git_metadata parsed `git status --porcelain` output
        # assuming paths are never quoted, but git's core.quotepath default
        # wraps a path in double quotes with C-style/octal escapes whenever it
        # contains a space or non-ASCII byte (e.g. "caf\303\251.py" for
        # "café.py"). The naive line[3:].strip() parse kept the literal quote
        # characters and escape sequences in the path, so such files never
        # matched the real on-disk relative path and were silently dropped
        # from git-priority scanning. Fixed by using `-z` (NUL-separated,
        # never-quoted output) instead of parsing quoted text.
        from graphgraph.scanner.core import _get_git_metadata

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            def run_git(*args: str) -> None:
                subprocess.run(["git", *args], cwd=root, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

            run_git("init", "-q")
            run_git("config", "user.email", "test@example.com")
            run_git("config", "user.name", "Test User")
            (root / "app.py").write_text("x = 1\n", encoding="utf-8")
            run_git("add", ".")
            run_git("commit", "-q", "-m", "initial")

            # Untracked file with a space in the name -- git quotes this
            # unless the name is already "safe", and even a space alone
            # doesn't always trigger quoting, so combine it with a non-ASCII
            # character to force core.quotepath's default quoting path.
            (root / "notes café.md").write_text("hi\n", encoding="utf-8")

            dirty_files, _churn = _get_git_metadata(root)
            self.assertIn("notes café.md", dirty_files, dirty_files)

    def test_get_git_metadata_handles_staged_rename(self) -> None:
        # Regression guard for the -z parsing rewrite: a staged rename/copy
        # entry is followed by an *extra* NUL-terminated token (the original
        # path) that must be consumed and skipped, not treated as its own
        # dirty-file entry -- otherwise the old path would leak into
        # dirty_files as a bogus, nonexistent file.
        from graphgraph.scanner.core import _get_git_metadata

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            def run_git(*args: str) -> None:
                subprocess.run(["git", *args], cwd=root, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

            run_git("init", "-q")
            run_git("config", "user.email", "test@example.com")
            run_git("config", "user.name", "Test User")
            (root / "old_name.py").write_text("x = 1\n" * 5, encoding="utf-8")
            run_git("add", ".")
            run_git("commit", "-q", "-m", "initial")
            run_git("mv", "old_name.py", "new_name.py")

            dirty_files, _churn = _get_git_metadata(root)
            self.assertIn("new_name.py", dirty_files, dirty_files)
            self.assertNotIn("old_name.py", dirty_files, dirty_files)

    def test_history_real_git_repo_end_to_end(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            def run_git(*args: str) -> None:
                subprocess.run(["git", *args], cwd=root, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

            run_git("init", "-q")
            run_git("config", "user.email", "test@example.com")
            run_git("config", "user.name", "Test User")

            (root / "app.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
            (root / "README.md").write_text("# demo\n", encoding="utf-8")
            run_git("add", ".")
            run_git("commit", "-q", "-m", "feat: initial commit")

            (root / "app.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
            run_git("add", ".")
            run_git("commit", "-q", "-m", "fix: correct add() returning subtraction result")

            (root / "app.py").write_text(
                "def add(a, b):\n    return a - b\n\n\ndef sub(a, b):\n    return a - b\n",
                encoding="utf-8",
            )
            run_git("add", ".")
            run_git("commit", "-q", "-m", "style: reformat with black")

            (root / "README.md").write_text("# demo\n\nUsage docs.\n", encoding="utf-8")
            run_git("add", ".")
            run_git("commit", "-q", "-m", "docs: add usage section")

            graph = scan_directory(root, depth="files", history=True)

            commit_nodes = {n.id: n for n in graph.nodes.values() if n.kind == "commit"}
            self.assertEqual(len(commit_nodes), 1, commit_nodes)
            commit_node = next(iter(commit_nodes.values()))
            self.assertIn("correct add()", commit_node.summary)

            fixes_edges = [e for e in graph.edges if e.type == "fixes"]
            self.assertEqual(len(fixes_edges), 1)
            app_file_node = next(n for n in graph.nodes.values() if n.path == "app.py")
            self.assertEqual(fixes_edges[0].source, commit_node.id)
            self.assertEqual(fixes_edges[0].target, app_file_node.id)
