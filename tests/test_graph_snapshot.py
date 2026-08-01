"""The byte-identical acceptance gate, run as a test.

`scripts/graph_snapshot.py` renders a canonical dump of the polyglot corpus.
This module asserts that dump still matches the committed baseline, which is
what turns "the refactor was a no-op" from a claim into a check.

Two properties are asserted beyond the snapshot match, because a snapshot on
its own cannot distinguish "unchanged" from "uniformly broken":

  * precision -- no call edge crosses a language boundary, and no call edge
    reaches an uncalled same-named decoy;
  * recall -- the corpus still produces call edges at all, so a regression that
    emptied the call graph would fail here rather than sail through as a
    stable, empty snapshot.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from graph_snapshot import (  # noqa: E402
    DEFAULT_BASELINE,
    DEFAULT_CORPUS,
    snapshot,
)

_SUFFIX_LANGUAGE = {
    "py": "python", "rb": "ruby", "php": "php", "js": "javascript",
    "tsx": "tsx", "ts": "typescript", "go": "go", "rs": "rust",
    "java": "java", "cs": "csharp", "cpp": "cpp", "hpp": "cpp",
    "h": "c", "c": "c", "kt": "kotlin", "scala": "scala", "swift": "swift",
}

# Node ids encode the file as `<stem>_<suffix>`; the suffix is the language.
_NODE_LANGUAGE = re.compile(
    r"^[^_]*_(" + "|".join(sorted(_SUFFIX_LANGUAGE, key=len, reverse=True)) + r")(?:__|$)"
)


def _language_of(node_id: str) -> str | None:
    match = _NODE_LANGUAGE.match(node_id)
    return _SUFFIX_LANGUAGE[match.group(1)] if match else None


def _edges(dump: str) -> list[dict]:
    return [json.loads(line[2:]) for line in dump.splitlines() if line.startswith("E ")]


class GraphSnapshotTest(unittest.TestCase):
    """The Phase-1 no-op gate and the precision invariants behind it."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.dump = snapshot(DEFAULT_CORPUS)

    def test_snapshot_matches_committed_baseline(self) -> None:
        self.assertTrue(
            DEFAULT_BASELINE.exists(),
            "missing baseline; regenerate with `python scripts/graph_snapshot.py write`",
        )
        expected = DEFAULT_BASELINE.read_text(encoding="utf-8")
        if expected == self.dump:
            return
        # Report the first divergence rather than 300 lines of NDJSON.
        expected_lines = expected.splitlines()
        actual_lines = self.dump.splitlines()
        for index, (want, got) in enumerate(zip(expected_lines, actual_lines)):
            if want != got:
                self.fail(
                    f"graph snapshot drifted at line {index + 1}.\n"
                    f"  baseline: {want}\n"
                    f"  current:  {got}\n"
                    "A reorganisation must not change this file. If the change is a "
                    "deliberate capability improvement, regenerate with "
                    "`python scripts/graph_snapshot.py write` and justify the diff "
                    "in the commit message."
                )
        self.fail(
            f"graph snapshot changed length: baseline {len(expected_lines)} lines, "
            f"current {len(actual_lines)}"
        )

    def test_no_call_edge_crosses_a_language_boundary(self) -> None:
        # Every language in the corpus defines Middle/Entry/Assist/Service/
        # Handle/Run in one directory, so repository-wide name lookup is
        # maximally ambiguous here. Any cross-language edge is a resolver that
        # matched on bare name alone.
        offenders = []
        for edge in _edges(self.dump):
            if edge["type"] != "calls":
                continue
            source, target = _language_of(edge["source"]), _language_of(edge["target"])
            if source and target and source != target:
                offenders.append(f"{edge['source']} -({source}->{target})-> {edge['target']}")
        self.assertEqual([], offenders, "call edges crossed a language boundary")

    def test_no_call_edge_reaches_an_uncalled_decoy(self) -> None:
        # Each helper file defines a `Middle` that nothing calls, sharing its
        # name with the live `Middle` in the corresponding core file. An edge
        # into the helper copy means resolution fell back to bare-name lookup.
        offenders = [
            f"{edge['source']} -> {edge['target']}"
            for edge in _edges(self.dump)
            if edge["type"] == "calls"
            and edge["target"].split("__")[-1].casefold() == "middle"
            and "helper" in edge["target"].split("__")[0].casefold()
        ]
        self.assertEqual([], offenders, "call edges reached an uncalled decoy")

    def test_corpus_still_produces_call_edges(self) -> None:
        # Guards the snapshot itself: an empty call graph is perfectly stable,
        # so without this a regression that resolved nothing would still match
        # a regenerated baseline.
        calls = [edge for edge in _edges(self.dump) if edge["type"] == "calls"]
        self.assertGreaterEqual(
            len(calls), 30, f"corpus call graph collapsed to {len(calls)} edges"
        )

    def test_snapshot_is_reproducible_across_runs(self) -> None:
        # A gate that is not deterministic cannot prove a no-op. Caches are
        # warm by this point, which is the condition a second scan actually
        # runs under.
        self.assertEqual(self.dump, snapshot(DEFAULT_CORPUS))


class GraphSnapshotCliTest(unittest.TestCase):
    """The `check` action must exit non-zero on drift, or it gates nothing."""

    def test_check_detects_a_perturbed_corpus(self) -> None:
        script = REPO_ROOT / "scripts" / "graph_snapshot.py"
        extra = DEFAULT_CORPUS / "core.py"
        original = extra.read_text(encoding="utf-8")
        try:
            extra.write_text(
                original + "\n\ndef SnapshotRedTest():\n    return Middle()\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                [sys.executable, str(script), "check"],
                capture_output=True, text=True, check=False, cwd=REPO_ROOT,
            )
            self.assertEqual(
                1, result.returncode,
                "check exited 0 on a perturbed corpus, so it gates nothing",
            )
            self.assertIn("DRIFT", result.stderr)
        finally:
            extra.write_text(original, encoding="utf-8")

        # And returns to passing once the perturbation is reverted.
        result = subprocess.run(
            [sys.executable, str(script), "check"],
            capture_output=True, text=True, check=False, cwd=REPO_ROOT,
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
