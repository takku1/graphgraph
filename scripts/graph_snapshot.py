"""Canonical, timestamp-free graph dump used as a byte-identical acceptance gate.

The scan and retrieval optimisation cycles (see `docs/findings/`) each gated
their changes on an ad-hoc dump of this shape, rebuilt from scratch every time.
This is that dump, committed, so a refactor can be *proved* to be a no-op rather
than argued to be one.

The contract this file exists to enforce:

    A reorganisation must not move a single byte of this dump.
    A capability change must move it, and the diff is the evidence.

Which fields are included is the whole design. Everything semantically
meaningful about a node or edge is in -- confidence, provenance, evidence and
source location included, because a refactor that silently downgraded edge
confidence while keeping the topology would otherwise pass. Everything that
varies between two runs of *unchanged* code is out: timestamps, durations, host
paths, and git state. A gate that is not reproducible is not a gate, so the
excluded set is enumerated explicitly below rather than filtered by guesswork.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from graphgraph.graph.core import Graph  # noqa: E402
from graphgraph.scanner.core import scan_directory  # noqa: E402

DEFAULT_CORPUS = REPO_ROOT / "tests" / "corpus" / "polyglot"
DEFAULT_BASELINE = REPO_ROOT / "tests" / "corpus" / "polyglot.snapshot"

# Node/edge fields excluded from the dump because they vary between two runs of
# unchanged code. Listed rather than inferred: a field added to Node or Edge
# later should land in the dump by default and be excluded only deliberately.
_VOLATILE_NODE_FIELDS = ("created_at", "updated_at")
_VOLATILE_EDGE_FIELDS = ("valid_from", "valid_to")

# Metadata keys that are part of the behavioural contract. Restricted to an
# allow-list because `graph.metadata` also carries scan durations, host paths,
# grammar versions and git SHAs, none of which are reproducible.
_STABLE_METADATA_KEYS = (
    "member_call_resolution_rate",
    "member_calls_internal_total",
    "member_calls_resolved",
    "member_calls_ambiguous",
    "member_calls_unknown_receiver",
    "member_calls_external_resolved",
    "member_calls_unmatched",
    "member_calls_by_language",
    "member_call_telemetry_version",
    "member_call_telemetry_scope",
    "bare_calls_unmatched",
    "unknown_receiver_classes",
    "symbol_frontend",
    "symbols_truncated",
)


def _portable(value: str) -> str:
    """Normalise a path-bearing string so Windows and POSIX agree."""
    return value.replace("\\", "/")


def _relative_to_root(value: str, root: Path | None) -> str:
    """Strip the absolute corpus prefix from a host path.

    `Node.source` holds a fully-qualified path, so a dump containing it is
    reproducible only on the machine that produced it -- which would make this
    gate useless in CI and useless to a second developer. Reduce it to a
    corpus-relative path; anything already relative passes through unchanged.
    """
    portable = _portable(value)
    if not portable or root is None:
        return portable
    prefix = _portable(str(root.resolve())).rstrip("/") + "/"
    if portable.startswith(prefix):
        return portable[len(prefix):]
    return portable


def canonical_dump(graph: Graph, root: Path | None = None) -> str:
    """Render a graph as sorted, timestamp-free, host-independent NDJSON."""
    lines: list[str] = []

    for node in sorted(graph.nodes.values(), key=lambda n: n.id):
        record = {
            "id": _portable(node.id),
            "label": node.label,
            "kind": node.kind,
            "path": _portable(node.path),
            "summary": node.summary,
            # Sorted: facts are a set in spirit, and extraction order is not
            # part of the contract. An unsorted tuple would make this gate fail
            # on reorderings that change nothing.
            "facts": sorted(node.facts),
            "scope": node.scope,
            "parent": _portable(node.parent),
            "source": _relative_to_root(node.source, root),
            "confidence": round(node.confidence, 6),
            "active": node.active,
        }
        lines.append("N " + json.dumps(record, sort_keys=True, separators=(",", ":")))

    for edge in sorted(
        graph.edges,
        key=lambda e: (e.source, e.target, e.type, e.evidence, e.source_location),
    ):
        record = {
            "source": _portable(edge.source),
            "target": _portable(edge.target),
            "type": edge.type,
            "weight": round(edge.weight, 6),
            "confidence": round(edge.confidence, 6),
            "provenance": edge.provenance,
            "evidence": edge.evidence,
            "source_location": _relative_to_root(edge.source_location, root),
            "active": edge.active,
        }
        lines.append("E " + json.dumps(record, sort_keys=True, separators=(",", ":")))

    metadata = getattr(graph, "metadata", {}) or {}
    for key in _STABLE_METADATA_KEYS:
        if key in metadata:
            lines.append(f"M {key}={_portable(str(metadata[key]))}")

    return "\n".join(lines) + "\n"


def snapshot(corpus: Path, frontend: str = "tree_sitter") -> str:
    """Scan *corpus* and render its canonical dump."""
    graph = scan_directory(corpus, depth="symbols", frontend=frontend, docs=False)
    return canonical_dump(graph, root=corpus)


def _diff(expected: str, actual: str, limit: int = 40) -> str:
    import difflib

    delta = list(
        difflib.unified_diff(
            expected.splitlines(),
            actual.splitlines(),
            fromfile="baseline",
            tofile="current",
            lineterm="",
        )
    )
    if len(delta) > limit:
        delta = delta[:limit] + [f"... ({len(delta) - limit} more lines)"]
    return "\n".join(delta)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("action", choices=("write", "check", "print"))
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--frontend", default="tree_sitter")
    args = parser.parse_args(argv)

    current = snapshot(args.corpus, frontend=args.frontend)

    if args.action == "print":
        sys.stdout.write(current)
        return 0

    if args.action == "write":
        args.baseline.parent.mkdir(parents=True, exist_ok=True)
        # newline="\n" so the baseline is identical on Windows and POSIX.
        args.baseline.write_text(current, encoding="utf-8", newline="\n")
        node_count = sum(1 for line in current.splitlines() if line.startswith("N "))
        edge_count = sum(1 for line in current.splitlines() if line.startswith("E "))
        print(f"wrote {args.baseline} ({node_count} nodes, {edge_count} edges)")
        return 0

    if not args.baseline.exists():
        print(f"no baseline at {args.baseline}; run `write` first", file=sys.stderr)
        return 2
    expected = args.baseline.read_text(encoding="utf-8")
    if expected == current:
        print(f"OK: snapshot matches {args.baseline}")
        return 0
    print(f"DRIFT: snapshot differs from {args.baseline}", file=sys.stderr)
    print(_diff(expected, current), file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
