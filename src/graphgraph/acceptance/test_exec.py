"""Language-agnostic test-command execution and classification (D8).

GraphGraph recommends focused test commands; the D8 gate is that every such
command selects at least one test — a zero-exit run that selects zero tests is a
*failed* recommendation. Test runners disagree wildly on output format, so this
module normalizes each ecosystem's output into one :class:`TestOutcome` with the
counts and classification D8 requires. New ecosystems plug in by adding a
:class:`Runner` to ``RUNNERS``; nothing else changes.

The classifier is pure and unit-tested against captured sample output, so the
layer is trustworthy for every ecosystem even when its toolchain is not installed
on the current machine. ``run_command`` executes a command (no shell, bounded by
a timeout) only when a caller explicitly asks.
"""

from __future__ import annotations

import re
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

# Classifications, most-actionable first.
PASSED = "passed"
TEST_FAILURE = "test_failure"
ZERO_SELECTED = "zero_selected"  # the D8 trap: exit 0 but no test selected
COMPILE_FAILURE = "compile_failure"
COMMAND_INVALID = "command_invalid"
TIMEOUT = "timeout"
INFRA_FAILURE = "infra_failure"
UNPARSED = "unparsed"

# Classifications that prove the command actually selected >= 1 test.
_SELECTING = frozenset({PASSED, TEST_FAILURE})


@dataclass(frozen=True)
class Extraction:
    selected: Optional[int] = None
    passed: Optional[int] = None
    failed: Optional[int] = None
    skipped: Optional[int] = None
    compile_failure: bool = False
    invalid: bool = False


@dataclass(frozen=True)
class TestOutcome:
    runner: str
    command: str
    exit_code: Optional[int]
    selected: Optional[int]
    passed: Optional[int]
    failed: Optional[int]
    skipped: Optional[int]
    classification: str
    tail: str = ""

    @property
    def selects_test(self) -> bool:
        return self.classification in _SELECTING and (self.selected or 0) >= 1


def _ints(pattern: str, text: str) -> list[int]:
    return [int(m) for m in re.findall(pattern, text)]


def _first(pattern: str, text: str) -> Optional[int]:
    m = re.search(pattern, text)
    return int(m.group(1)) if m else None


def _extract_cargo(out: str) -> Extraction:
    passed = failed = ignored = 0
    saw_result = False
    for m in re.finditer(r"test result:\s*\w+\.\s*(\d+) passed;\s*(\d+) failed;\s*(\d+) ignored", out):
        saw_result = True
        passed += int(m.group(1))
        failed += int(m.group(2))
        ignored += int(m.group(3))
    running = sum(_ints(r"running (\d+) tests?", out))
    selected: Optional[int]
    if saw_result:
        selected = passed + failed + ignored
    elif re.search(r"running \d+ tests?", out):
        selected = running
    else:
        selected = None
    return Extraction(
        selected=selected,
        passed=passed if saw_result else None,
        failed=failed if saw_result else None,
        skipped=ignored if saw_result else None,
        compile_failure=bool(re.search(r"error\[E\d+\]|could not compile|error: could not", out)),
        invalid=bool(re.search(r"error: (Found argument|Unrecognized|unexpected argument|no such)", out)),
    )


def _extract_pytest(out: str) -> Extraction:
    collected = _first(r"collected (\d+) items?", out)
    selected_explicit = _first(r"(\d+) selected", out)
    deselected = _first(r"(\d+) deselected", out)
    passed = _first(r"(\d+) passed", out)
    failed = _first(r"(\d+) failed", out)
    skipped = _first(r"(\d+) skipped", out)
    errors = _first(r"(\d+) errors?", out)
    invalid = bool(re.search(r"ERROR: (file or directory not found|not found)", out))
    no_tests = "no tests ran" in out
    if selected_explicit is not None:
        selected = selected_explicit
    elif collected is not None:
        selected = max(0, collected - (deselected or 0))
    elif any(v is not None for v in (passed, failed, skipped)):
        selected = (passed or 0) + (failed or 0) + (skipped or 0)
    elif deselected is not None or no_tests:
        # -q mode prints only "N deselected"; everything was filtered out.
        selected = 0
    else:
        selected = None
    compile_failure = bool(errors) and (passed is None) and "during collection" in out
    return Extraction(selected, passed, failed, skipped, compile_failure, invalid)


def _extract_go(out: str) -> Extraction:
    runs = len(re.findall(r"(?m)^=== RUN\s", out))
    passes = len(re.findall(r"--- PASS", out))
    fails = len(re.findall(r"--- FAIL", out))
    no_files = "[no test files]" in out
    if runs:
        selected: Optional[int] = runs
    elif passes or fails:
        selected = passes + fails
    elif no_files:
        selected = 0
    else:
        selected = None
    return Extraction(
        selected=selected,
        passed=passes or None,
        failed=fails or None,
        compile_failure=bool(re.search(r"build failed|cannot find package|undefined:|syntax error", out)),
    )


def _extract_node(out: str) -> Extraction:
    passed = _first(r"(\d+) passed", out)
    failed = _first(r"(\d+) failed", out)
    total = _first(r"(\d+) total", out)
    no_tests = bool(re.search(r"[Nn]o tests? found", out))
    if total is not None:
        selected = total
    elif passed is not None or failed is not None:
        selected = (passed or 0) + (failed or 0)
    elif no_tests:
        selected = 0
    else:
        selected = None
    return Extraction(selected, passed, failed, compile_failure=bool(re.search(r"SyntaxError|Cannot find module", out)))


def _extract_junit(out: str) -> Extraction:
    m = re.search(r"Tests run:\s*(\d+),\s*Failures:\s*(\d+),\s*Errors:\s*(\d+),\s*Skipped:\s*(\d+)", out)
    if not m:
        return Extraction(compile_failure=bool(re.search(r"COMPILATION ERROR|cannot find symbol", out)))
    selected = int(m.group(1))
    failed = int(m.group(2)) + int(m.group(3))
    skipped = int(m.group(4))
    return Extraction(
        selected=selected,
        passed=selected - failed - skipped,
        failed=failed,
        skipped=skipped,
        compile_failure=bool(re.search(r"COMPILATION ERROR|cannot find symbol", out)),
    )


def _extract_dotnet(out: str) -> Extraction:
    m = re.search(r"Failed:\s*(\d+),\s*Passed:\s*(\d+),\s*Skipped:\s*(\d+),\s*Total:\s*(\d+)", out)
    if not m:
        invalid = "No test is available" in out
        return Extraction(selected=0 if invalid else None, invalid=invalid)
    failed, passed, skipped, total = (int(m.group(i)) for i in range(1, 5))
    return Extraction(total, passed, failed, skipped)


def _extract_generic(out: str) -> Extraction:
    passed = _first(r"(\d+) passed", out)
    failed = _first(r"(\d+) (?:failed|failures?)", out)
    if passed is None and failed is None:
        return Extraction()
    return Extraction(selected=(passed or 0) + (failed or 0), passed=passed, failed=failed)


@dataclass(frozen=True)
class Runner:
    name: str
    prefixes: tuple[str, ...]
    extract: Callable[[str], Extraction]

    def matches(self, command: str) -> bool:
        tokens = command.split()
        return bool(tokens) and any(p in tokens[: len(p.split()) + 2] for p in self.prefixes)


RUNNERS: tuple[Runner, ...] = (
    Runner("cargo", ("cargo",), _extract_cargo),
    Runner("pytest", ("pytest", "py.test"), _extract_pytest),
    Runner("go", ("go",), _extract_go),
    Runner("node", ("jest", "vitest", "npm", "pnpm", "yarn", "npx"), _extract_node),
    Runner("junit", ("mvn", "gradle", "./gradlew", "gradlew"), _extract_junit),
    Runner("dotnet", ("dotnet",), _extract_dotnet),
)
_GENERIC = Runner("generic", (), _extract_generic)


def select_runner(command: str) -> Runner:
    for runner in RUNNERS:
        if runner.matches(command):
            return runner
    return _GENERIC


def classify(exit_code: Optional[int], ex: Extraction, *, timed_out: bool = False) -> str:
    if timed_out:
        return TIMEOUT
    if ex.invalid:
        return COMMAND_INVALID
    if ex.compile_failure:
        return COMPILE_FAILURE
    if ex.selected is None:
        return UNPARSED if exit_code == 0 else INFRA_FAILURE
    if ex.selected == 0:
        return ZERO_SELECTED
    if (ex.failed or 0) > 0 or exit_code not in (0, None):
        return TEST_FAILURE
    return PASSED


def outcome_from_output(command: str, exit_code: Optional[int], stdout: str, stderr: str = "", *, timed_out: bool = False) -> TestOutcome:
    runner = select_runner(command)
    combined = f"{stdout}\n{stderr}"
    ex = runner.extract(combined)
    return TestOutcome(
        runner=runner.name,
        command=command,
        exit_code=exit_code,
        selected=ex.selected,
        passed=ex.passed,
        failed=ex.failed,
        skipped=ex.skipped,
        classification=classify(exit_code, ex, timed_out=timed_out),
        tail="\n".join(combined.strip().splitlines()[-6:]),
    )


def _argv(command: str) -> list[str]:
    """Split a command without mangling Windows backslashes, stripping wrap quotes."""
    try:
        tokens = shlex.split(command, posix=False)
    except ValueError:
        tokens = command.split()
    return [
        t[1:-1] if len(t) >= 2 and t[0] == t[-1] and t[0] in "\"'" else t
        for t in tokens
    ]


def run_command(command: str, cwd: Path, *, timeout: float = 240.0) -> TestOutcome:
    """Execute one test command with no shell, bounded by a timeout."""
    argv = _argv(command)
    try:
        proc = subprocess.run(
            argv, cwd=str(cwd), capture_output=True, text=True, timeout=timeout, shell=False
        )
    except FileNotFoundError:
        return TestOutcome(select_runner(command).name, command, None, None, None, None, None, INFRA_FAILURE, "executable not found")
    except subprocess.TimeoutExpired as exc:
        partial = (exc.stdout or "") + (exc.stderr or "")
        tail = "\n".join(str(partial).strip().splitlines()[-6:])
        return TestOutcome(select_runner(command).name, command, None, None, None, None, None, TIMEOUT, tail)
    return outcome_from_output(command, proc.returncode, proc.stdout, proc.stderr)


def tool_available(command: str) -> bool:
    """Whether the runner executable for *command* is on PATH."""
    import shutil

    tokens = _argv(command)
    return bool(tokens) and shutil.which(tokens[0]) is not None
