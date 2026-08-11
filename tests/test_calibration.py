from __future__ import annotations

import json
from argparse import Namespace
from dataclasses import replace
from pathlib import Path

import pytest

from graphgraph.analysis.calibration import (
    apply_isotonic,
    calibration_report,
    pav_isotonic,
    reliability_table,
)
from graphgraph.analysis.eval import (
    EvalResult,
    calibration_pairs,
    results_with_calibration_to_json,
)
from graphgraph.cli.evaluation import cmd_eval
from graphgraph.cli.parser import build_parser
from graphgraph.graph.core import Graph, Node
from graphgraph.io import save_graph


def test_reliability_table_assigns_boundaries_and_drops_empty_bins() -> None:
    table = reliability_table([(0.0, False), (0.5, True), (1.0, True)], bins=2)

    assert [(item.lower, item.upper, item.count) for item in table] == [
        (0.0, 0.5, 1),
        (0.5, 1.0, 2),
    ]
    assert table[0].mean_confidence == 0.0
    assert table[0].accuracy == 0.0
    assert table[1].mean_confidence == 0.75
    assert table[1].accuracy == 1.0


def test_calibration_report_exposes_brier_decomposition_and_errors() -> None:
    report = calibration_report(
        [(0.1, False), (0.4, True), (0.8, False), (0.9, True)],
        bins=2,
    )

    assert report.count == 4
    assert report.base_rate == 0.5
    assert report.brier == pytest.approx(0.255)
    assert report.decomposition_residual == pytest.approx(0.0, abs=1e-12)
    assert report.ece == pytest.approx(0.3)
    assert report.mce == pytest.approx(0.35)


@pytest.mark.parametrize(
    ("pairs", "bins", "message"),
    [
        ([], 10, "zero predictions"),
        ([(1.1, True)], 10, "confidence must be in"),
        ([(0.5, True)], 0, "bins must be"),
    ],
)
def test_calibration_inputs_are_validated(
    pairs: list[tuple[float, bool]], bins: int, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        calibration_report(pairs, bins=bins)


def test_pav_groups_tied_confidences_independently_of_input_order() -> None:
    forward = [(0.5, False), (0.5, True)]
    reverse = list(reversed(forward))

    assert pav_isotonic(forward) == ((0.5, 0.5),)
    assert pav_isotonic(reverse) == ((0.5, 0.5),)


def test_pav_returns_step_thresholds_and_apply_uses_the_fitted_step() -> None:
    breakpoints = pav_isotonic(
        [(0.1, False), (0.4, True), (0.8, False), (0.9, True)]
    )

    assert breakpoints == ((0.1, 0.0), (0.8, 0.5), (0.9, 1.0))
    assert apply_isotonic(breakpoints, 0.0) == 0.0
    assert apply_isotonic(breakpoints, 0.1) == 0.0
    assert apply_isotonic(breakpoints, 0.4) == 0.5
    assert apply_isotonic(breakpoints, 0.8) == 0.5
    assert apply_isotonic(breakpoints, 0.85) == 1.0
    assert apply_isotonic(breakpoints, 1.0) == 1.0


def test_apply_isotonic_without_a_fit_is_identity() -> None:
    assert apply_isotonic((), 0.37) == 0.37


def _eval_result(
    *, confidence: float | None, node_recall: float | None, edge_recall: float | None
) -> EvalResult:
    return EvalResult(
        query="q",
        query_class="blast_radius",
        node_recall=node_recall,
        edge_recall=edge_recall,
        returned_nodes=1,
        returned_edges=1,
        token_estimate=10,
        answerability_status="answerable",
        answerability_confidence=confidence,
    )


def test_eval_calibration_pairs_use_labeled_recall_not_runtime_absence() -> None:
    results = [
        _eval_result(confidence=0.9, node_recall=1.0, edge_recall=None),
        _eval_result(confidence=0.8, node_recall=1.0, edge_recall=0.5),
        _eval_result(confidence=None, node_recall=1.0, edge_recall=1.0),
        _eval_result(confidence=0.4, node_recall=None, edge_recall=None),
    ]

    assert calibration_pairs(results, complete_recall=1.0) == [
        (0.9, True),
        (0.8, False),
    ]
    assert calibration_pairs(results, complete_recall=0.5) == [
        (0.9, True),
        (0.8, True),
    ]


def test_eval_calibration_excludes_unresolved_ground_truth() -> None:
    invalid = replace(
        _eval_result(confidence=0.1, node_recall=0.0, edge_recall=None),
        expected_unresolved_count=1,
        expected_unresolved=("missing/path",),
    )
    valid = _eval_result(confidence=0.9, node_recall=1.0, edge_recall=None)

    assert calibration_pairs([invalid, valid]) == [(0.9, True)]

    payload = json.loads(results_with_calibration_to_json([invalid, valid], bins=2))
    assert payload["calibration"]["count"] == 1
    assert payload["calibration"]["excluded_unresolved_expectation_tasks"] == 1


def test_eval_calibration_uses_explicit_impossible_query_label() -> None:
    negative = replace(
        _eval_result(confidence=0.1, node_recall=None, edge_recall=None),
        expected_answerable=False,
    )

    assert calibration_pairs([negative]) == [(0.1, False)]


def test_eval_calibration_envelope_keeps_results_and_reports_label_policy() -> None:
    results = [
        _eval_result(confidence=0.9, node_recall=1.0, edge_recall=None),
        _eval_result(confidence=0.8, node_recall=0.0, edge_recall=None),
    ]

    payload = json.loads(
        results_with_calibration_to_json(results, bins=2, complete_recall=1.0)
    )

    assert len(payload["results"]) == 2
    assert payload["calibration"]["count"] == 2
    assert payload["calibration"]["label_policy"] == {
        "source": "declared eval expectations plus explicit impossible-query labels",
        "complete_recall": 1.0,
        "rule": (
            "expected_answerable=false is negative; otherwise all scored "
            "node/edge recall values must meet the threshold"
        ),
    }


@pytest.mark.parametrize("threshold", [-0.1, 1.1])
def test_eval_calibration_rejects_invalid_recall_threshold(threshold: float) -> None:
    with pytest.raises(ValueError, match="complete_recall"):
        calibration_pairs([], complete_recall=threshold)


def test_eval_parser_exposes_opt_in_calibration_receipt() -> None:
    args = build_parser().parse_args(
        [
            "eval",
            "--graph",
            "graph.json",
            "--tasks",
            "tasks.json",
            "--calibration",
            "--calibration-bins",
            "4",
            "--complete-recall",
            "0.8",
        ]
    )

    assert args.calibration is True
    assert args.calibration_bins == 4
    assert args.complete_recall == 0.8


def test_eval_parser_exposes_source_mode() -> None:
    args = build_parser().parse_args(
        [
            "eval",
            "--graph",
            "graph.gg",
            "--tasks",
            "tasks.json",
            "--source-mode",
            "off",
        ]
    )

    assert args.source_mode == "off"


def test_eval_command_emits_calibration_envelope(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    graph_path = tmp_path / "graph.json"
    tasks_path = tmp_path / "tasks.json"
    save_graph(
        Graph(
            nodes={
                "target": Node(
                    "target", "target", "function", "src/target.py", "L1"
                )
            }
        ),
        graph_path,
    )
    tasks_path.write_text(
        json.dumps([{"query": "target", "expected": ["target"]}]),
        encoding="utf-8",
    )

    cmd_eval(
        Namespace(
            graph=str(graph_path),
            tasks=str(tasks_path),
            max_nodes=None,
            calibration=True,
            calibration_bins=2,
            complete_recall=1.0,
        )
    )
    payload = json.loads(capsys.readouterr().out)

    assert payload["calibration"]["count"] == 1
    assert payload["results"][0]["answerability_confidence"] is not None


def test_answer_confidence_is_calibrated_on_the_labeled_set() -> None:
    # path-to-10 #3 gate: the shipped answer confidence must be calibrated
    # (ECE < 0.10) against the hand-labeled pass/fail set. This needs a scanned
    # self-graph (the artifact the self-eval also uses) and is skipped when it is
    # absent. The confidence formula's exact-anchor backbone is calibrated to
    # exactly this set; a regression that decalibrates it trips here.
    from graphgraph.analysis.calibration import calibration_report
    from graphgraph.analysis.eval import evaluate_graph, load_eval_tasks

    graph_path = Path(".graphgraph/graph.gg")
    tasks_path = Path("eval/graphgraph-calibration.json")
    if not graph_path.exists():
        pytest.skip("self-graph not scanned; run `graphgraph scan --docs` first")

    results = evaluate_graph(graph_path, load_eval_tasks(tasks_path))
    report = calibration_report(calibration_pairs(results, complete_recall=1.0), bins=10)
    assert report.ece < 0.10, f"answer-confidence ECE {report.ece:.4f} exceeds the 0.10 gate"
