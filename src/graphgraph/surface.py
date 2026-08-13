"""Transport-facing name constants, importable without loading any subsystem.

Building the CLI parser needs these tuples for `choices=`, defaults, and help
text -- nothing more. Reading them from their defining modules meant importing
the packet renderers, the planner, the platform stack, and the scanner just to
print `--help`: the scanner pulled in `pathspec`, which pulls in `asyncio`, for
a command that touches no files. That put roughly 200 ms of subsystem import in
front of every single CLI invocation.

This module imports only the standard-library record type used by its atomic
contracts, so both the parser and runtime owners can read their shared transport
contract without loading any GraphGraph subsystem. Packet targets are
intentionally absent: their complete cold catalog is the single authority in
`graphgraph.packet_targets`.
"""

from __future__ import annotations

from typing import NamedTuple


class QueryClassContract(NamedTuple):
    """Cold query-class identity and transport description."""

    name: str
    description: str
    automatic: bool = True


QUERY_CLASS_CONTRACTS: tuple[QueryClassContract, ...] = (
    QueryClassContract("direct_lookup", "Locate a definition or focused symbol."),
    QueryClassContract("reverse_lookup", "Find callers, references, implementors, or dependents."),
    QueryClassContract("affected_tests", "Find direct, transitive, and behavioral tests affected by a change."),
    QueryClassContract("multi_hop_path", "Trace a dependency, call, control, or data-flow path."),
    QueryClassContract("blast_radius", "Estimate downstream change impact and supporting evidence."),
    QueryClassContract("subsystem_summary", "Summarize a subsystem or architecture slice."),
    QueryClassContract("doc_summary", "Ground an answer in document sections and paragraphs."),
    QueryClassContract("negative_query", "Prove absence, isolation, or lack of references."),
    QueryClassContract("recent_changes", "Retrieve qualifying recent history and fixes evidence."),
    QueryClassContract("spreading_activation", "Use explicit multi-step activation retrieval.", automatic=False),
)
QUERY_CLASS_NAMES: tuple[str, ...] = tuple(contract.name for contract in QUERY_CLASS_CONTRACTS)

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

class CompilerPassContract(NamedTuple):
    """Cold public identity for a built-in compiler pass."""

    name: str


EVIDENCE_COMPILER_PASS = CompilerPassContract("evidence")
INFERENCE_COMPILER_PASS = CompilerPassContract("inference")
HIERARCHY_COMPILER_PASS = CompilerPassContract("hierarchy")
COMPILER_PASS_CONTRACTS: tuple[CompilerPassContract, ...] = (
    EVIDENCE_COMPILER_PASS,
    INFERENCE_COMPILER_PASS,
    HIERARCHY_COMPILER_PASS,
)
COMPILER_PASS_NAMES: tuple[str, ...] = tuple(contract.name for contract in COMPILER_PASS_CONTRACTS)

#: Default file/symbol collection cap shared by scanner and transport callers.
DEFAULT_SCAN_MAX_NODES: int = 5000

__all__ = [
    "COMPILER_PASS_NAMES",
    "COMPILER_PASS_CONTRACTS",
    "CompilerPassContract",
    "REPRESENTATION_DEFAULT",
    "REPRESENTATION_DESCRIPTION",
    "DEFAULT_SCAN_MAX_NODES",
    "QUERY_CLASS_CONTRACTS",
    "QUERY_CLASS_NAMES",
    "QueryClassContract",
    "REPRESENTATION_NAMES",
    "EVIDENCE_COMPILER_PASS",
    "HIERARCHY_COMPILER_PASS",
    "INFERENCE_COMPILER_PASS",
]
