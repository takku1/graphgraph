from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from graphgraph.live_validation import run_tests


class LiveValidationTest(unittest.TestCase):
    def test_successful_cargo_command_selecting_zero_tests_fails_verification(self) -> None:
        output = (
            "running 0 tests\n\n"
            "test result: ok. 0 passed; 0 failed; 0 ignored; 0 measured; 36 filtered out\n"
        )
        with tempfile.TemporaryDirectory() as tmp, patch(
            "graphgraph.live_validation.subprocess.run",
            return_value=subprocess.CompletedProcess(["cargo", "test"], 0, output),
        ):
            receipt = run_tests(
                Path(tmp),
                command_text="cargo test -p locus-frontends source::normalize::tests --lib",
            )

        self.assertFalse(receipt["ok"])
        self.assertEqual(receipt["status"], "failed")
        self.assertEqual(receipt["tests"], 0)
        self.assertEqual(receipt["reason"], "test command selected zero tests")

    def test_cargo_command_selecting_one_test_passes_verification(self) -> None:
        output = (
            "running 1 test\n"
            "test source::normalize::normalize_tests::rust_logical_ops_lower_to_bitwise_at_binary_positions ... ok\n\n"
            "test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 35 filtered out\n"
        )
        with tempfile.TemporaryDirectory() as tmp, patch(
            "graphgraph.live_validation.subprocess.run",
            return_value=subprocess.CompletedProcess(["cargo", "test"], 0, output),
        ):
            receipt = run_tests(
                Path(tmp),
                command_text=(
                    "cargo test -p locus-frontends "
                    "rust_logical_ops_lower_to_bitwise_at_binary_positions --lib"
                ),
            )

        self.assertTrue(receipt["ok"])
        self.assertEqual(receipt["status"], "passed")
        self.assertEqual(receipt["tests"], 1)
