"""OW-AC-03 increment 3: held-out-style conceptual retrieval on an in-repo fixture.

Queries share no identifier tokens with the expected labels. The fixture is
scanned from scratch so this suite does not depend on a third-party checkout
or a stale project graph.
"""

from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path

import pytest

from graphgraph.analysis.eval import evaluate_graph, load_eval_tasks
from graphgraph.io import save_graph
from graphgraph.scanner import scan_directory

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "corpus" / "conceptual-disjoint"
TASKS = ROOT / "eval" / "conceptual-fixture.json"
GATE = 0.80
# Honest measurement on genuinely lexically-disjoint paraphrases (2026-08-19,
# R-005). Structural-only retrieval scores 0.200 -- and that single point comes
# from FIX-C06, which routes to `subsystem_summary` and returns 8 of the
# fixture's 12 nodes, so it is a dragnet rather than conceptual retrieval. The
# ratchet is set at the measured floor, not below it: an earlier value of 0.0
# could not have caught a real regression.
BASELINE = 0.2


def _scan_fixture():
    return scan_directory(
        FIXTURE,
        depth="symbols",
        frontend="tree_sitter",
        docs=True,
    )


_STOPWORDS = frozenset(
    """a an and any are as at be been being by can code define defined does each for from
    get has have how in into is it its like made make must new not of on one only or other
    others out over so than that the their them then there these they this to two up use
    used uses using was what when where which while who why with without you your""".split()
)


def _stem(word: str) -> str:
    for suffix in ("ations", "ation", "ingly", "ing", "edly", "ed", "ies", "es", "s", "ly"):
        if len(word) - len(suffix) >= 4 and word.endswith(suffix):
            return word[: -len(suffix)]
    return word


def _content_tokens(text: str) -> set[str]:
    """Stemmed, stopword-free content tokens; identifiers are split on case/underscore."""
    words: list[str] = []
    for raw in re.split(r"[^A-Za-z]+", text or ""):
        if not raw:
            continue
        words.extend(_split_ident(raw) or [raw])
    return {_stem(w.lower()) for w in words if len(w) > 2 and w.lower() not in _STOPWORDS}


def test_fixture_queries_are_lexically_disjoint_from_target_text() -> None:
    """A paraphrase query must not reuse the wording of the file that answers it.

    The previous guard compared the query only against the expected *identifier*,
    so a docstring restating the query verbatim passed unnoticed -- which is
    exactly what an independent checker found (R-005): four of five queries were
    near-copies of their own docstrings, making this a substring test rather than
    a conceptual one. The surface checked here is the whole file containing the
    answer: label, summary/docstring, and path. If the query's own words occur
    anywhere in that file, plain lexical search reaches the answer and the task
    cannot demonstrate conceptual retrieval.
    """
    data = json.loads(TASKS.read_text(encoding="utf-8"))
    graph = _scan_fixture()
    nodes = list(graph.nodes.values())
    for task in data["tasks"]:
        if task.get("expected_answerable") is False:
            continue
        query_tokens = _content_tokens(task["query"])
        assert query_tokens, f"{task['id']}: query has no content tokens to compare"
        for label in task.get("expected", []):
            targets = [n for n in nodes if n.label == label]
            assert targets, f"{task['id']}: expected label {label} is not in the fixture graph"
            answer_paths = {n.path for n in targets if n.path}
            surface = " ".join(
                f"{n.label} {n.summary} {n.path}"
                for n in nodes
                if n.label == label or (n.path and n.path in answer_paths)
            )
            overlap = query_tokens & _content_tokens(surface)
            assert not overlap, (
                f"{task['id']}: query shares {sorted(overlap)} with the text of {label} "
                f"({sorted(answer_paths)}). A paraphrase task may not reuse the answering "
                f"file's wording -- rewrite the query or the docstring."
            )


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


def _fixture_recall() -> tuple[float, dict[str, object]]:
    graph = _scan_fixture()
    with tempfile.TemporaryDirectory() as tmp:
        graph_path = Path(tmp) / "graph.json"
        save_graph(graph, graph_path)
        results = evaluate_graph(graph_path, load_eval_tasks(TASKS))
    by_id = {row.task_id: row for row in results}
    positives = [row for row in results if "negative" not in row.strata]
    recalls = [row.node_recall if row.node_recall is not None else 0.0 for row in positives]
    return sum(recalls) / len(recalls), by_id


def test_red_control_abstains_on_the_conceptual_fixture() -> None:
    """The red control must abstain whatever the positive tasks score."""
    _, by_id = _fixture_recall()
    red = by_id["FIX-R01"]
    assert red.answerability_status in {"unanswerable", "incomplete"}
    assert red.returned_nodes == 0 or red.node_recall in {None, 0.0}


def test_conceptual_fixture_recall_does_not_regress_below_baseline() -> None:
    """Ratchet against the committed measurement, so a real gain must be recorded.

    `BASELINE` is the honest measurement on genuinely disjoint paraphrases, not
    an aspiration. It is deliberately separate from `GATE`: OW-AC-03 asks for
    0.80 and the system does not reach it, which the xfail below states openly
    rather than hiding behind a fixture that answered its own questions.
    """
    mean, by_id = _fixture_recall()
    detail = ", ".join(f"{t}={by_id[t].node_recall}" for t in by_id if t != "FIX-R01")
    assert mean >= BASELINE, f"conceptual recall regressed to {mean:.3f} < {BASELINE:.3f}; {detail}"


@pytest.mark.xfail(
    strict=True,
    reason=(
        "OW-AC-03 is unmet on genuine paraphrase queries. The fixture previously "
        "reported 0.80 only because its docstrings restated the queries verbatim "
        "(R-005). Structural retrieval alone cannot bridge a lexical gap; the "
        "candidate fix is RF-04. When this passes, promote BASELINE and delete "
        "this marker -- strict=True makes an unnoticed pass a failure."
    ),
)
def test_conceptual_fixture_meets_ow_ac_03_gate() -> None:
    mean, _ = _fixture_recall()
    assert mean >= GATE


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
