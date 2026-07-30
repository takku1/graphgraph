"""Transport-facing name constants, importable without loading any subsystem.

Building the CLI parser needs these tuples for `choices=`, defaults, and help
text -- nothing more. Reading them from their defining modules meant importing
the packet renderers, the planner, the platform stack, and the scanner just to
print `--help`: the scanner pulled in `pathspec`, which pulls in `asyncio`, for
a command that touches no files. That put roughly 200 ms of subsystem import in
front of every single CLI invocation.

This module has no imports at all, so the parser can read every name it needs
for the cost of one `.pyc`. The values here are duplicated from their
authoritative definitions on purpose; `tests/test_surface_constants.py` fails if
any of them drifts, so the copy cannot silently rot.
"""

from __future__ import annotations

#: Mirrors `graphgraph.packets.formats.PACKET_FORMAT_NAMES`.
PACKET_FORMAT_NAMES: tuple[str, ...] = (
    "lowlevel",
    "sql",
    "hybrid",
    "semantic_arrow",
    "gg",
    "gg_hybrid",
    "gg_lex",
    "gg_lex_hybrid",
    "svo",
    "doc_summary",
)

#: Mirrors `graphgraph.planning.routing.QUERY_CLASS_NAMES`.
QUERY_CLASS_NAMES: tuple[str, ...] = (
    "direct_lookup",
    "reverse_lookup",
    "affected_tests",
    "multi_hop_path",
    "blast_radius",
    "subsystem_summary",
    "doc_summary",
    "negative_query",
    "recent_changes",
    "spreading_activation",
)

#: Mirrors `graphgraph.representation.REPRESENTATION_NAMES`.
REPRESENTATION_NAMES: tuple[str, ...] = ("flat", "hybrid")

#: The single source for how the representation policy is described to a
#: caller. `graphgraph.representation.representation_schema` reads these rather
#: than restating them, so the CLI help and any machine tool schema cannot drift
#: apart -- and the parser gets the text without importing the representation
#: package (and through it, the packet renderers).
REPRESENTATION_DEFAULT: str = "flat"
REPRESENTATION_DESCRIPTION: str = (
    "Project representation policy. flat returns the retrieved exact subgraph. "
    "hybrid is an experimental opt-in that reserves exact query entities and "
    "represents the remaining active project through aggregate path cells."
)

#: Mirrors `graphgraph.platform.COMPILER_PASS_NAMES`.
COMPILER_PASS_NAMES: tuple[str, ...] = ("evidence", "inference", "hierarchy")

#: Mirrors `graphgraph.scanner.files.DEFAULT_SCAN_MAX_NODES`.
DEFAULT_SCAN_MAX_NODES: int = 5000

__all__ = [
    "COMPILER_PASS_NAMES",
    "REPRESENTATION_DEFAULT",
    "REPRESENTATION_DESCRIPTION",
    "DEFAULT_SCAN_MAX_NODES",
    "PACKET_FORMAT_NAMES",
    "QUERY_CLASS_NAMES",
    "REPRESENTATION_NAMES",
]
