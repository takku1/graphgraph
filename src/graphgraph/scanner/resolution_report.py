"""Per-language receiver-resolution volume and held-out precision (OW-AC-05)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..graph.core import Graph
from .core import scan_directory

HELDOUT_ROOT = Path(__file__).resolve().parents[3] / "tests" / "corpus" / "heldout-receivers"
POLYGLOT_ROOT = Path(__file__).resolve().parents[3] / "tests" / "corpus" / "polyglot"

HELDOUT_EXPECTED: dict[str, set[tuple[str, str, str]]] = {
    "ts": {("persist", "save", "Store")},
    "cs": {("Persist", "Save", "Store")},
    "py": {("persist", "save", "Store")},
    "go": {("Persist", "Save", "Store")},
}


def _owner_label(graph: Graph, node_id: str) -> str:
    node = graph.nodes[node_id]
    if node.parent and node.parent in graph.nodes:
        return graph.nodes[node.parent].label
    return ""


def _type_resolved_calls(graph: Graph) -> set[tuple[str, str, str]]:
    observed: set[tuple[str, str, str]] = set()
    for edge in graph.edges:
        if edge.type != "calls" or "tree_sitter_type_resolved" not in (edge.provenance or ""):
            continue
        source = graph.nodes.get(edge.source)
        target = graph.nodes.get(edge.target)
        if source is None or target is None or target.kind != "method":
            continue
        observed.add((source.label, target.label, _owner_label(graph, edge.target)))
    return observed


def language_volume(graph: Graph) -> dict[str, dict[str, int]]:
    """Counts from scan telemetry when present; otherwise zeroed."""

    raw = graph.metadata.get("member_calls_by_language", "")
    if not raw:
        return {}
    try:
        import json

        payload = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    if not isinstance(payload, dict):
        return {}
    return {
        str(language): {
            "resolved": int(stats.get("resolved", 0)),
            "ambiguous": int(stats.get("ambiguous", 0)),
            "unknown_receiver": int(stats.get("unknown_receiver", 0)),
            "unmatched": int(stats.get("unmatched", 0)),
        }
        for language, stats in payload.items()
        if isinstance(stats, dict)
    }


def heldout_precision_table(root: Path | None = None) -> dict[str, Any]:
    """Independently labeled multi-file oracles, not the 7-language same-file fixture."""

    base = root or HELDOUT_ROOT
    by_language: dict[str, Any] = {}
    hits = 0
    expected_total = 0
    extras = 0
    for language, expected in HELDOUT_EXPECTED.items():
        graph = scan_directory(base / language, depth="symbols", frontend="tree_sitter")
        observed = _type_resolved_calls(graph)
        found = expected & observed
        extra = {
            item
            for item in observed
            if item[2] and item[2] != next(iter(expected))[2]
        }
        hits += len(found)
        expected_total += len(expected)
        extras += len(extra)
        denom = len(found) + len(extra)
        by_language[language] = {
            "expected": len(expected),
            "found": len(found),
            "false_owners": len(extra),
            "precision": 1.0 if denom == 0 else round(len(found) / denom, 4),
            "recall": round(len(found) / len(expected), 4) if expected else 0.0,
            "volume": language_volume(graph),
        }
    if POLYGLOT_ROOT.is_dir():
        polyglot = scan_directory(POLYGLOT_ROOT, depth="symbols", frontend="tree_sitter")
        by_language["polyglot_fixture"] = {"volume": language_volume(polyglot)}
    precision = 1.0 if extras == 0 and hits else (hits / (hits + extras) if (hits + extras) else 0.0)
    recall = hits / expected_total if expected_total else 0.0
    return {
        "metric": "receiver_resolution_precision",
        "value": round(precision, 4),
        "recall": round(recall, 4),
        "direction": "higher",
        "target": 0.98,
        "by_language": by_language,
        "hits": hits,
        "expected": expected_total,
        "false_owners": extras,
    }
