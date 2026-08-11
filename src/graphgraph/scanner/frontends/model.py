"""Data contracts for source extraction: file/result records and the Extractor protocol."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Protocol

from ...graph.core import Edge, Node
from ..source_ir import SourceIR


@dataclass(frozen=True)
class FrontendCapability:
    name: str
    available: bool
    confidence: float
    description: str
    ready_languages: tuple[str, ...] = ()
    unavailable_languages: tuple[str, ...] = ()
    # Whether `--frontend <name>` / select_extractor(name) actually yields this
    # frontend. A capability can be described (planned work) without being
    # selectable; advertising `available=True` for something that silently
    # falls back to regex is the dishonesty this field exists to prevent.
    selectable: bool = True

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
    external_resolved_member_calls: int = 0
    unmatched_member_calls: int = 0
    bare_unmatched_calls: int = 0
    # Compact stable rows:
    # (language, resolved, ambiguous, unknown_receiver, external_resolved, unmatched)
    member_calls_by_language: tuple[tuple[str, int, int, int, int, int], ...] = ()

    @property
    def unresolved_member_calls(self) -> int:
        """Back-compatible total of the external/unmatched split."""
        return self.external_resolved_member_calls + self.unmatched_member_calls

class Extractor(Protocol):
    name: str
    confidence: float

    def extract_symbols(
        self,
        files: list[SourceIR],
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
    # Suffix that separates this definition's node id from an earlier
    # same-named one in the same file and scope. Empty for the first (and
    # usually only) definition of a name, so ordinary ids are unchanged.
    # Assigned once per file by `_disambiguate_definition_ids`, because
    # `_definition_node_id` is called from a dozen sites and must stay a pure
    # function of the definition it is handed.
    disambiguator: str = ""
    # Declared return annotation, taken from the parser's own `return_type`
    # field rather than re-derived from source text.
    return_type: str = ""
    # The parse node, kept only for the duration of extraction so later
    # stages can reuse the parser's structure instead of re-scanning text.
    # Excluded from comparison: parse nodes are not value-comparable.
    node: object | None = field(default=None, compare=False, repr=False)
    # This definition's source with comments and literals blanked, for the same
    # reason as `node`: resolution needs it and collection has already computed
    # it, and re-deriving it means walking every descendant a second time.
    # Empty when nothing asked for it (Python resolves from a real AST instead).
    literal_free_text: str = field(default="", compare=False, repr=False)

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
    # `external_resolved` and `unmatched` are the two halves of what used to be
    # a single `unresolved` bucket. They record opposite outcomes -- correctly
    # declining to link a call the graph does not own, versus failing to link
    # one it does -- so a combined count cannot tell success from failure.
    # `unresolved` is retained below as their sum for telemetry continuity.
    external_resolved: int = 0
    unmatched: int = 0
    # Bare (unqualified) call sites discarded because the name could not be
    # bound to a single definition, even though the graph *does* define that
    # name somewhere. These never become edges, so a caller count computed
    # after them is a lower bound. Tracked separately from the member-call
    # buckets because a repository of plain functions has no member calls at
    # all, and its evidence was therefore reported as complete.
    bare_unmatched: int = 0
    unknown_receiver_classes: tuple[tuple[str, int], ...] = ()
    by_language: tuple[tuple[str, int, int, int, int, int], ...] = ()

    @property
    def unresolved(self) -> int:
        """Back-compatible total. Prefer the two components for diagnosis."""
        return self.external_resolved + self.unmatched

    def add_bare_unmatched(self) -> _MemberCallStats:
        return replace(self, bare_unmatched=self.bare_unmatched + 1)

    def add(
        self,
        outcome: str,
        receiver: str = "",
        language: str = "",
    ) -> _MemberCallStats:
        classes = dict(self.unknown_receiver_classes)
        if outcome == "unknown_receiver":
            bucket = classify_unknown_receiver(receiver)
            classes[bucket] = classes.get(bucket, 0) + 1
        by_language = {
            name: [resolved, ambiguous, unknown_receiver, external_resolved, unmatched]
            for (
                name,
                resolved,
                ambiguous,
                unknown_receiver,
                external_resolved,
                unmatched,
            ) in self.by_language
        }
        if language:
            counts = by_language.setdefault(language, [0, 0, 0, 0, 0])
            outcome_index = {
                "resolved": 0,
                "ambiguous": 1,
                "unknown_receiver": 2,
                "external_resolved": 3,
                "unmatched": 4,
            }.get(outcome)
            if outcome_index is not None:
                counts[outcome_index] += 1
        return _MemberCallStats(
            resolved=self.resolved + (outcome == "resolved"),
            ambiguous=self.ambiguous + (outcome == "ambiguous"),
            unknown_receiver=self.unknown_receiver + (outcome == "unknown_receiver"),
            external_resolved=self.external_resolved + (outcome == "external_resolved"),
            unmatched=self.unmatched + (outcome == "unmatched"),
            bare_unmatched=self.bare_unmatched,
            unknown_receiver_classes=tuple(sorted(classes.items())),
            by_language=tuple(
                (name, *counts)
                for name, counts in sorted(by_language.items())
            ),
        )

@dataclass(frozen=True)
class _CallSite:
    name: str
    qualified: bool
    receiver: str = ""
    qualifier: str = ""
