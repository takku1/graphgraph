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
    unknown_receiver_classes: tuple[tuple[str, int], ...] = ()
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

# Syntactic classes of receiver expression, for the unknown_receiver
# histogram. A single opaque total says a resolver pass is needed but not
# which one; the breakdown is what lets the next pass target the largest
# bucket instead of guessing at it from source patterns.
UNKNOWN_RECEIVER_CLASSES = (
    "complex_expression",  # receiver text discarded: indexing, deep chains, macros
    "method_chain",        # a.b() -- needs the return type of b on a's type
    "call_result",         # f() -- needs f's return type
    "field_chain",         # a.b -- needs the type of field b on a's type
    "short_local",         # 1-2 char binding, typically a closure or loop variable
    "named_local",         # longer local whose binding could not be typed
)


def classify_unknown_receiver(receiver: str) -> str:
    """Bucket one unresolved receiver expression by syntactic shape."""
    if not receiver:
        return "complex_expression"
    if "(" in receiver:
        return "method_chain" if "." in receiver.split("(", 1)[0] else "call_result"
    if "." in receiver:
        return "field_chain"
    return "short_local" if len(receiver) <= 2 else "named_local"


@dataclass(frozen=True)
class _MemberCallStats:
    resolved: int = 0
    ambiguous: int = 0
    unknown_receiver: int = 0
    unresolved: int = 0
    unknown_receiver_classes: tuple[tuple[str, int], ...] = ()

    def add(self, outcome: str, receiver: str = "") -> _MemberCallStats:
        classes = dict(self.unknown_receiver_classes)
        if outcome == "unknown_receiver":
            bucket = classify_unknown_receiver(receiver)
            classes[bucket] = classes.get(bucket, 0) + 1
        return _MemberCallStats(
            resolved=self.resolved + (outcome == "resolved"),
            ambiguous=self.ambiguous + (outcome == "ambiguous"),
            unknown_receiver=self.unknown_receiver + (outcome == "unknown_receiver"),
            unresolved=self.unresolved + (outcome == "unresolved"),
            unknown_receiver_classes=tuple(sorted(classes.items())),
        )

@dataclass(frozen=True)
class _CallSite:
    name: str
    qualified: bool
    receiver: str = ""
    qualifier: str = ""
