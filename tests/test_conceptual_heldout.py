"""OW-AC-03 increment 3: held-out-style conceptual retrieval on an in-repo fixture.

Queries share no identifier tokens with the expected labels. The fixture is
scanned from scratch so this suite does not depend on a third-party checkout
or a stale project graph.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from graphgraph.analysis.eval import evaluate_graph, load_eval_tasks
from graphgraph.io import save_graph
from graphgraph.scanner import scan_directory

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "corpus" / "conceptual-disjoint"
TASKS = ROOT / "eval" / "conceptual-fixture.json"
GATE = 0.80


def _scan_fixture():
    return scan_directory(
        FIXTURE,
        depth="symbols",
        frontend="tree_sitter",
        docs=True,
    )


def test_fixture_queries_are_lexically_disjoint_from_expected_labels() -> None:
    data = json.loads(TASKS.read_text(encoding="utf-8"))
    for task in data["tasks"]:
        if task.get("expected_answerable") is False:
            continue
        query_tokens = {part.lower() for part in task["query"].replace("?", "").split() if part.isalpha()}
        for label in task.get("expected", []):
            pieces = {part.lower() for part in _split_ident(label)}
            overlap = query_tokens & pieces
            assert not overlap, f"{task['id']}: query shares {overlap} with {label}"


def _split_ident(label: str) -> list[str]:
    parts: list[str] = []
    current = []
    for char in label:
        if char.isupper() and current:
            parts.append("".join(current))
            current = [char]
        elif char == "_":
            if current:
                parts.append("".join(current))
            current = []
        else:
            current.append(char)
    if current:
        parts.append("".join(current))
    return [part for part in parts if len(part) > 2]


def test_conceptual_fixture_mean_recall_and_red_control_abstain() -> None:
    graph = _scan_fixture()
    with tempfile.TemporaryDirectory() as tmp:
        graph_path = Path(tmp) / "graph.json"
        save_graph(graph, graph_path)
        results = evaluate_graph(graph_path, load_eval_tasks(TASKS))
    by_id = {row.task_id: row for row in results}
    positives = [row for row in results if "negative" not in row.strata]
    recalls = [row.node_recall if row.node_recall is not None else 0.0 for row in positives]
    mean = sum(recalls) / len(recalls)
    red = by_id["FIX-R01"]
    assert red.answerability_status in {"unanswerable", "incomplete"}
    assert red.returned_nodes == 0 or red.node_recall in {None, 0.0}
    assert mean >= GATE, (
        f"conceptual fixture mean recall {mean:.3f} < {GATE:.2f}; "
        + ", ".join(f"{row.task_id}={row.node_recall}" for row in positives)
    )


def test_generic_missing_words_do_not_prove_a_facet_absent() -> None:
    from graphgraph import Graph, Node
    from graphgraph.retrieval.facets import facet_is_provably_absent

    graph = Graph(
        nodes={
            "LADDER": Node(
                "LADDER",
                "ConfidenceLadder",
                "class",
                "evidence.py",
                summary="How well-supported a conclusion is.",
            )
        }
    )
    assert not facet_is_provably_absent(
        graph, ("tool", "record", "sure", "conclusion", "holds")
    )
    assert facet_is_provably_absent(
        graph, ("graphql", "subscription", "transport")
    )


def test_local_conceptual_suite_stays_at_the_gate_when_a_graph_exists() -> None:
    from graphgraph.acceptance.proof_lanes import local_conceptual_receipt
    from graphgraph.io import find_graph_path

    try:
        graph_path = find_graph_path(ROOT)
    except FileNotFoundError:
        return
    receipt = local_conceptual_receipt(graph_path)
    assert receipt["mean"] >= GATE, receipt
    assert receipt["meets_gate"] is True
