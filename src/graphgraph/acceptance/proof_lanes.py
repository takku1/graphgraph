"""Bounded proof lanes: what GraphGraph can and cannot claim today."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..analysis.eval import evaluate_graph, load_eval_tasks
from ..io import find_graph_path, load_any
from ..retrieval.relations import query_relations

SELF_SUITE = Path("eval/graphgraph-self.json")
LOCAL_CONCEPTUAL = Path("eval/graphgraph-local-conceptual.json")


def lexical_mention_files(root: Path, term: str) -> list[str]:
    hits: list[str] = []
    for path in root.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if term in text:
            hits.append(path.as_posix())
    return sorted(hits)


def caller_rows(graph_path: Path, target: str, *, include_tests: bool = False) -> list[dict[str, Any]]:
    graph = load_any(graph_path)
    result = query_relations(
        graph,
        target,
        direction="callers",
        limit=50,
        include_tests=include_tests,
    )
    if result.get("status") != "ok":
        return []
    return list(result.get("neighbors") or [])


def caller_labels(graph_path: Path, target: str, *, include_tests: bool = False) -> list[str]:
    return [str(row.get("label") or "") for row in caller_rows(graph_path, target, include_tests=include_tests)]


def self_eval_receipt(graph_path: Path) -> dict[str, Any]:
    results = evaluate_graph(graph_path, load_eval_tasks(SELF_SUITE))
    green = [row for row in results if "RED TEST" not in row.query]
    red = [row for row in results if "RED TEST" in row.query]
    return {
        "suite": str(SELF_SUITE),
        "green_recalls": [row.node_recall for row in green],
        "green_min": min((row.node_recall or 0.0) for row in green) if green else None,
        "red_recall": red[0].node_recall if red else None,
        "red_tokens": red[0].token_estimate if red else None,
    }


def local_conceptual_receipt(graph_path: Path) -> dict[str, Any]:
    results = evaluate_graph(graph_path, load_eval_tasks(LOCAL_CONCEPTUAL))
    recalls = [row.node_recall if row.node_recall is not None else 0.0 for row in results]
    mean = sum(recalls) / len(recalls) if recalls else 0.0
    return {
        "suite": str(LOCAL_CONCEPTUAL),
        "recalls": recalls,
        "mean": round(mean, 4),
        "ow_ac_03_gate": 0.80,
        "meets_gate": mean >= 0.80,
        "claim_boundary": (
            "This is this-repository conceptual recall, not the held-out "
            "OW-AC-03 panel. Corpora for that panel were not present."
        ),
    }


def proof_receipt(*, repo: Path = Path(".")) -> dict[str, Any]:
    graph_path = find_graph_path(repo)
    mentions = lexical_mention_files(repo / "src", "select_symbols")
    callers = caller_rows(graph_path, "select_symbols", include_tests=False)
    caller_paths = {str(row.get("path") or "") for row in callers}
    return {
        "exact_self_eval": self_eval_receipt(graph_path),
        "local_conceptual": local_conceptual_receipt(graph_path),
        "vs_lexical_search": {
            "target": "select_symbols",
            "graph_callers": [row.get("label") for row in callers],
            "lexical_mention_files": len(mentions),
            "definition_file_is_mention_not_caller": any(
                path.endswith("retrieval/predicates.py") for path in mentions
            )
            and not any(path.endswith("retrieval/predicates.py") for path in caller_paths),
            "expected_callers_present": {"cmd_select", "handle_select_symbols"}
            <= {str(row.get("label") or "") for row in callers},
            "claim_boundary": (
                "Lexical search finds mentions. Graph callers exclude the "
                "definition and keep typed production callers. This licenses "
                "'better than rg for caller questions', not 'better than every "
                "graph tool'."
            ),
        },
    }
