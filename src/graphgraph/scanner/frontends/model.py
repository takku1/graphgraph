"""Data contracts for source extraction: file/result records and the Extractor protocol."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ...graph.core import Edge, Node


@dataclass(frozen=True)
class FrontendCapability:
    name: str
    available: bool
    confidence: float
    description: str
    ready_languages: tuple[str, ...] = ()
    unavailable_languages: tuple[str, ...] = ()

@dataclass(frozen=True)
class SourceFile:
    path: Path
    rel: str
    file_node_id: str
    text: str

@dataclass(frozen=True)
class ExtractionResult:
    nodes: dict[str, Node]
    edges: list[Edge]
    frontend: str
    truncated: bool = False
    fallback_files: tuple[str, ...] = ()
    failed_files: tuple[str, ...] = ()
    unsupported_files: tuple[str, ...] = ()
    grammar_errors: tuple[str, ...] = ()
    timeout_files: tuple[str, ...] = ()
    parse_error_files: tuple[str, ...] = ()
    resolved_member_calls: int = 0
    ambiguous_member_calls: int = 0
    unknown_receiver_member_calls: int = 0
    unresolved_member_calls: int = 0

class Extractor(Protocol):
    name: str
    confidence: float

    def extract_symbols(
        self,
        files: list[SourceFile],
        max_total_symbols: int,
        context_nodes: dict[str, Node] | None = None,
    ) -> ExtractionResult:
        ...

@dataclass(frozen=True)
class _TsDef:
    name: str
    kind: str
    start: int
    end: int
    line: int
    extra: tuple[str, ...] = ()
    owner: str = ""
    facts: tuple[str, ...] = ()

@dataclass(frozen=True)
class _MemberCallStats:
    resolved: int = 0
    ambiguous: int = 0
    unknown_receiver: int = 0
    unresolved: int = 0

    def add(self, outcome: str) -> _MemberCallStats:
        return _MemberCallStats(
            resolved=self.resolved + (outcome == "resolved"),
            ambiguous=self.ambiguous + (outcome == "ambiguous"),
            unknown_receiver=self.unknown_receiver + (outcome == "unknown_receiver"),
            unresolved=self.unresolved + (outcome == "unresolved"),
        )

@dataclass(frozen=True)
class _CallSite:
    name: str
    qualified: bool
    receiver: str = ""
    qualifier: str = ""
