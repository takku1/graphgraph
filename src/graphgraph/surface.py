"""Transport-facing name constants, importable without loading any subsystem.

Building the CLI parser needs these tuples for `choices=`, defaults, and help
text -- nothing more. Reading them from their defining modules meant importing
the packet renderers, the planner, the platform stack, and the scanner just to
print `--help`: the scanner pulled in `pathspec`, which pulls in `asyncio`, for
a command that touches no files. That put roughly 200 ms of subsystem import in
front of every single CLI invocation.

This module has no imports at all, so both the parser and runtime owners can
read their shared transport contract for the cost of one `.pyc`. Packet targets
are intentionally absent: their complete cold catalog is the single authority
in `graphgraph.packet_targets`.
"""

from __future__ import annotations

#: Query classes exposed by planning and transport interfaces.
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

#: Representation policies exposed by compilers and transport interfaces.
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

#: Compiler passes exposed by the platform and transport interfaces.
COMPILER_PASS_NAMES: tuple[str, ...] = ("evidence", "inference", "hierarchy")

#: Default file/symbol collection cap shared by scanner and transport callers.
DEFAULT_SCAN_MAX_NODES: int = 5000

__all__ = [
    "COMPILER_PASS_NAMES",
    "REPRESENTATION_DEFAULT",
    "REPRESENTATION_DESCRIPTION",
    "DEFAULT_SCAN_MAX_NODES",
    "QUERY_CLASS_NAMES",
    "REPRESENTATION_NAMES",
]
