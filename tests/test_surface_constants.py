from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

from graphgraph import surface

ROOT = Path(__file__).resolve().parents[1]


class SurfaceConstantsTest(unittest.TestCase):
    """`graphgraph.surface` duplicates names so the parser can skip subsystems.

    The duplication is deliberate and only safe while it is checked: if a packet
    format, query class, representation policy, or compiler pass is added to its
    defining module and not mirrored here, the CLI would silently stop offering
    it.
    """

    def test_packet_format_names_match(self) -> None:
        from graphgraph.packets import PACKET_FORMAT_NAMES

        self.assertEqual(surface.PACKET_FORMAT_NAMES, PACKET_FORMAT_NAMES)

    def test_query_class_names_match(self) -> None:
        from graphgraph.planning import QUERY_CLASS_NAMES

        self.assertEqual(surface.QUERY_CLASS_NAMES, QUERY_CLASS_NAMES)

    def test_representation_names_match(self) -> None:
        from graphgraph.representation import REPRESENTATION_NAMES

        self.assertEqual(surface.REPRESENTATION_NAMES, REPRESENTATION_NAMES)

    def test_compiler_pass_names_match(self) -> None:
        from graphgraph.platform import COMPILER_PASS_NAMES

        self.assertEqual(surface.COMPILER_PASS_NAMES, COMPILER_PASS_NAMES)

    def test_default_scan_max_nodes_matches(self) -> None:
        from graphgraph.scanner.files import DEFAULT_SCAN_MAX_NODES

        self.assertEqual(surface.DEFAULT_SCAN_MAX_NODES, DEFAULT_SCAN_MAX_NODES)


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
