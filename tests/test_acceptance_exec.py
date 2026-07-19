from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from graphgraph.acceptance.test_exec import (
    COMPILE_FAILURE,
    PASSED,
    TEST_FAILURE,
    ZERO_SELECTED,
    outcome_from_output,
    run_command,
    select_runner,
)

# Captured representative output per ecosystem.
_SAMPLES = {
    "cargo_pass": (
        "cargo test -p locus-frontends rust_logical_ops --lib",
        0,
        "running 1 test\ntest normalize::normalize_tests::rust_logical_ops ... ok\n\n"
        "test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 35 filtered out\n",
        1,
        PASSED,
        True,
    ),
    "cargo_zero_trap": (
        "cargo test -p locus-frontends source::normalize::tests --lib",
        0,
        "running 0 tests\n\n"
        "test result: ok. 0 passed; 0 failed; 0 ignored; 0 measured; 36 filtered out\n",
        0,
        ZERO_SELECTED,
        False,
    ),
    "cargo_compile": (
        "cargo test -p locus-frontends",
        101,
        "error[E0433]: failed to resolve\nerror: could not compile `locus-frontends` due to previous error\n",
        None,
        COMPILE_FAILURE,
        False,
    ),
    "pytest_pass": (
        "pytest tests/test_app.py -q",
        0,
        "collected 1 item\n\ntests/test_app.py .   [100%]\n\n===== 1 passed in 0.01s =====\n",
        1,
        PASSED,
        True,
    ),
    "pytest_zero": (
        "pytest tests/test_app.py -k nomatch",
        5,
        "collected 0 items\n\n===== no tests ran in 0.01s =====\n",
        0,
        ZERO_SELECTED,
        False,
    ),
    "go_pass": (
        "go test ./pkg -run TestNormalize",
        0,
        "=== RUN   TestNormalize\n--- PASS: TestNormalize (0.00s)\nPASS\nok  example/pkg 0.002s\n",
        1,
        PASSED,
        True,
    ),
    "go_no_files": (
        "go test ./pkg",
        0,
        "?   example/pkg [no test files]\n",
        0,
        ZERO_SELECTED,
        False,
    ),
    "node_pass": (
        "npx jest normalize",
        0,
        "Tests:       2 passed, 2 total\nSnapshots:   0 total\n",
        2,
        PASSED,
        True,
    ),
    "node_no_tests": (
        "npx jest nomatch",
        1,
        "No tests found, exiting with code 1\n",
        0,
        ZERO_SELECTED,
        False,
    ),
    "junit_failure": (
        "mvn -Dtest=NormalizeTest test",
        1,
        "Tests run: 5, Failures: 1, Errors: 0, Skipped: 1, Time elapsed: 0.5 s\n",
        5,
        TEST_FAILURE,
        True,
    ),
    "dotnet_pass": (
        "dotnet test --filter Normalize",
        0,
        "Passed!  - Failed:     0, Passed:     5, Skipped:     0, Total:     5\n",
        5,
        PASSED,
        True,
    ),
}


class MultiLanguageParserTest(unittest.TestCase):
    def test_every_ecosystem_parses_to_normalized_outcome(self) -> None:
        for name, (command, exit_code, stdout, selected, classification, selects) in _SAMPLES.items():
            with self.subTest(sample=name):
                outcome = outcome_from_output(command, exit_code, stdout)
                self.assertEqual(outcome.selected, selected, f"{name}: selected")
                self.assertEqual(outcome.classification, classification, f"{name}: {outcome.tail}")
                self.assertEqual(outcome.selects_test, selects, f"{name}: selects_test")

    def test_zero_selected_trap_is_a_failed_recommendation(self) -> None:
        # The exact defect from the usage report: exit 0, zero tests selected.
        command, exit_code, stdout, *_ = _SAMPLES["cargo_zero_trap"]
        outcome = outcome_from_output(command, exit_code, stdout)
        self.assertEqual(outcome.exit_code, 0)
        self.assertFalse(outcome.selects_test)
        self.assertEqual(outcome.classification, ZERO_SELECTED)

    def test_runner_selection_by_command(self) -> None:
        self.assertEqual(select_runner("cargo test -p x").name, "cargo")
        self.assertEqual(select_runner("go test ./...").name, "go")
        self.assertEqual(select_runner("mvn test").name, "junit")
        self.assertEqual(select_runner("dotnet test").name, "dotnet")
        self.assertEqual(select_runner("npx vitest run").name, "node")
        self.assertEqual(select_runner("bazel test //x").name, "generic")


class LivePytestExecutionTest(unittest.TestCase):
    """End-to-end: really run a focused command that selects a test, and the trap."""

    def _make_repo(self) -> Path:
        tmp = Path(tempfile.mkdtemp())
        (tmp / "test_sample.py").write_text(
            "def test_alpha():\n    assert True\n\ndef test_beta():\n    assert True\n",
            encoding="utf-8",
        )
        return tmp

    def test_focused_command_selects_a_test(self) -> None:
        repo = self._make_repo()
        cmd = f'"{sys.executable}" -m pytest test_sample.py -k test_alpha -q'
        outcome = run_command(cmd, repo, timeout=120)
        self.assertTrue(outcome.selects_test, outcome.tail)
        self.assertEqual(outcome.classification, PASSED, outcome.tail)
        self.assertGreaterEqual(outcome.selected or 0, 1)

    def test_zero_match_command_is_caught_live(self) -> None:
        repo = self._make_repo()
        cmd = f'"{sys.executable}" -m pytest test_sample.py -k nomatch_xyz -q'
        outcome = run_command(cmd, repo, timeout=120)
        self.assertFalse(outcome.selects_test, outcome.tail)
        self.assertEqual(outcome.classification, ZERO_SELECTED, outcome.tail)


class CoversReceiptTest(unittest.TestCase):
    def test_covers_ok_requires_a_source_to_test_path(self) -> None:
        from graphgraph.acceptance.affected_tests_case import _covers_ok

        ok, _ = _covers_ok(
            [{"command": "cargo test -p x t", "tests": [{"id": "t", "root_paths": [{"root": {}}]}]}]
        )
        self.assertTrue(ok)
        self.assertFalse(_covers_ok([])[0])
        self.assertFalse(_covers_ok([{"command": "c", "tests": []}])[0])
        self.assertFalse(_covers_ok([{"command": "c", "tests": [{"id": "t", "root_paths": []}]}])[0])


if __name__ == "__main__":
    unittest.main()
