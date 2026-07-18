from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from ..graph.core import Graph
from ..retrieval import search_nodes


@dataclass(frozen=True)
class EvaluationCase:
    project: str
    query: str
    expected: tuple[str, ...]
    category: str = "retrieval"


def load_cases(path: Path) -> list[EvaluationCase]:
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = data.get("cases", data) if isinstance(data, dict) else data
    return [EvaluationCase(
        project=str(row.get("project", "default")),
        query=str(row["query"]),
        expected=tuple(str(value) for value in row.get("expected", [])),
        category=str(row.get("category", "retrieval")),
    ) for row in rows]


def evaluate_cases(graphs: dict[str, Graph], cases: list[EvaluationCase], *, limit: int = 20) -> dict[str, object]:
    results = []
    for case in cases:
        graph = graphs.get(case.project)
        if graph is None:
            results.append({**asdict(case), "passed": False, "error": "project graph missing", "found": []})
            continue
        matches = search_nodes(graph, case.query, limit=limit)
        found = [match.node.id for match in matches]
        expected = set(case.expected)
        found_handles = set(found)
        for node_id in found:
            node = graph.nodes[node_id]
            found_handles.update((node.label, node.path))
        hits = expected & found_handles
        reciprocal_rank = 0.0
        for index, node_id in enumerate(found):
            node = graph.nodes[node_id]
            if expected & {node_id, node.label, node.path}:
                reciprocal_rank = 1.0 / (index + 1)
                break
        results.append({
            **asdict(case),
            "passed": expected <= found_handles,
            "recall": len(hits) / max(1, len(expected)),
            "reciprocal_rank": reciprocal_rank,
            "found": found,
        })
    passed = sum(bool(result["passed"]) for result in results)
    return {
        "ok": passed == len(results),
        "cases": len(results),
        "passed": passed,
        "pass_rate": passed / max(1, len(results)),
        "mean_recall": sum(float(result.get("recall", 0.0)) for result in results) / max(1, len(results)),
        "results": results,
    }
