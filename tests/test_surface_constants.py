from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

from graphgraph import surface

ROOT = Path(__file__).resolve().parents[1]


class SurfaceConstantsTest(unittest.TestCase):
    """`graphgraph.surface` owns cold contracts so the parser can skip subsystems.

    Runtime owners and the parser project from the same atomic records, so a
    transport-visible identity cannot drift behind a detached names tuple.
    """

    def _documented_pretty_range(self, command: str) -> tuple[float, float]:
        """The overhead range this command's --pretty help text advertises."""
        import re

        from graphgraph.cli.parser import build_parser

        parser = build_parser()
        subparsers = next(
            action for action in parser._actions if hasattr(action, "choices") and action.choices
        )
        target = subparsers.choices[command]
        pretty = next(
            action for action in target._actions if "--pretty" in getattr(action, "option_strings", ())
        )
        # argparse help strings escape a literal percent as `%%`.
        match = re.search(r"~(\d+)-(\d+)%%? more tokens", pretty.help or "")
        self.assertIsNotNone(match, f"{command} --pretty help must state a measured range: {pretty.help!r}")
        assert match is not None
        return float(match.group(1)) / 100, float(match.group(2)) / 100

    def _pretty_overhead(self, payload: object) -> float:
        import json

        tiktoken = __import__("tiktoken")
        enc = tiktoken.get_encoding("cl100k_base")
        compact = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        pretty = json.dumps(payload, indent=2, ensure_ascii=False)
        compact_tokens = len(enc.encode(compact))
        return (len(enc.encode(pretty)) - compact_tokens) / compact_tokens

    def test_documented_pretty_overhead_survives_measurement(self) -> None:
        """A self-reported cost must survive a real tokenizer.

        `--pretty` advertised "~26% more tokens" for both `query` and `select`.
        Measured with cl100k_base that understated `query` (26-39%) and was
        roughly half of `select` (43-51%), whose flat record lists are the
        shape indentation taxes hardest. This tool's credibility rests on its
        self-reported numbers, so the documented figure is re-measured here
        rather than trusted.
        """
        try:
            __import__("tiktoken")
        except ModuleNotFoundError:  # pragma: no cover - tiktoken is a dev dep
            self.skipTest("tiktoken is required to measure real token cost")

        # `select`: a flat list of small symbol records.
        select_payload = {
            "symbols": [
                {
                    "id": f"src_graphgraph_module_{index}_py__Handler__method_{index}",
                    "label": f"method_{index}",
                    "kind": "method",
                    "path": f"src/graphgraph/module_{index}.py",
                    "callers": index % 7,
                }
                for index in range(200)
            ]
        }
        # `query`: a nested envelope, where indentation amortizes over longer
        # string values and so costs proportionally less.
        query_payload = {
            "packet": "@nodes\n" + "\n".join(f"n{i}: label_{i}" for i in range(120)),
            "anchors": [{"id": f"anchor_{i}", "score": 12.5 + i, "reasons": ["exact", "typed"]} for i in range(12)],
            "receipt": {"route": {"query_class": "subsystem_summary"}, "metrics": {"nodes": 48, "edges": 96}},
        }

        for command, payload in (("select", select_payload), ("query", query_payload)):
            low, high = self._documented_pretty_range(command)
            measured = self._pretty_overhead(payload)
            self.assertGreaterEqual(
                measured,
                low - 0.10,
                f"{command} --pretty documents {100 * low:.0f}-{100 * high:.0f}% "
                f"but measured {100 * measured:.1f}% -- documentation now overstates cost",
            )
            self.assertLessEqual(
                measured,
                high + 0.10,
                f"{command} --pretty documents {100 * low:.0f}-{100 * high:.0f}% "
                f"but measured {100 * measured:.1f}% -- documentation understates cost",
            )

    def test_query_class_catalog_drives_runtime_and_parser(self) -> None:
        from graphgraph.cli.parser import build_parser
        from graphgraph.planning import QUERY_CLASSES

        contracts = surface.QUERY_CLASS_CONTRACTS
        expected = tuple((contract.name, contract.description, contract.automatic) for contract in contracts)
        runtime = tuple((spec.name, spec.description, spec.automatic) for spec in QUERY_CLASSES)

        parser = build_parser()
        subparsers = next(action for action in parser._actions if hasattr(action, "choices") and action.choices)
        plan = subparsers.choices["plan"]
        query_class = next(action for action in plan._actions if action.dest == "query_class")

        self.assertEqual(runtime, expected)
        self.assertEqual(tuple(query_class.choices or ()), tuple(contract.name for contract in contracts))

    def test_representation_names_match(self) -> None:
        from graphgraph.representation import REPRESENTATION_NAMES

        self.assertIs(surface.REPRESENTATION_NAMES, REPRESENTATION_NAMES)

    def test_compiler_pass_catalog_drives_runtime_and_parser(self) -> None:
        from graphgraph.cli.parser import build_parser
        from graphgraph.platform.compiler import BUILTIN_COMPILER_PASSES

        contracts = surface.COMPILER_PASS_CONTRACTS
        expected_names = tuple(contract.name for contract in contracts)
        runtime_names = tuple(compiler_pass.spec.name for compiler_pass in BUILTIN_COMPILER_PASSES)

        parser = build_parser()
        subparsers = next(action for action in parser._actions if hasattr(action, "choices") and action.choices)
        platform = subparsers.choices["platform"]
        actions = next(action for action in platform._actions if hasattr(action, "choices") and action.choices)
        compile_parser = actions.choices["compile"]
        passes = next(action for action in compile_parser._actions if action.dest == "passes")

        self.assertEqual(runtime_names, expected_names)
        self.assertEqual(tuple(passes.choices or ()), expected_names)

    def test_default_scan_max_nodes_matches(self) -> None:
        from graphgraph.scanner.files import DEFAULT_SCAN_MAX_NODES

        self.assertIs(surface.DEFAULT_SCAN_MAX_NODES, DEFAULT_SCAN_MAX_NODES)


class ParserImportWeightTest(unittest.TestCase):
    """The whole point of `surface` is what building a parser must NOT import."""

    #: Subsystems the parser has no reason to load. `scanner` is listed because
    #: it reaches `pathspec` -> `asyncio`, which is pure cost for `--help`.
    FORBIDDEN = (
        "graphgraph.packets",
        "graphgraph.planning",
        "graphgraph.representation",
        "graphgraph.scanner",
        "graphgraph.retrieval",
        "graphgraph.platform",
        "pathspec",
        "asyncio",
    )

    def test_building_the_parser_loads_no_subsystem(self) -> None:
        probe = (
            "import sys\n"
            "from graphgraph.cli.parser import build_parser\n"
            "build_parser()\n"
            "leaked = [m for m in %r if m in sys.modules]\n"
            "print(','.join(leaked))\n" % (self.FORBIDDEN,)
        )
        result = subprocess.run(
            [sys.executable, "-c", probe],
            capture_output=True,
            text=True,
            cwd=ROOT,
            env={**__import__("os").environ, "PYTHONPATH": str(ROOT / "src")},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        leaked = [name for name in result.stdout.strip().split(",") if name]
        self.assertEqual(leaked, [], f"building the parser imported: {leaked}")


if __name__ == "__main__":
    unittest.main()
