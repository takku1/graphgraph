from __future__ import annotations

import json
from argparse import Namespace
from dataclasses import replace
from pathlib import Path

import pytest

from graphgraph import Graph, Node
from graphgraph.analysis.eval import EvalResult, load_eval_tasks
from graphgraph.analysis.eval_protocol import (
    EVAL_SCHEMA_VERSION,
    EXPECTED_EVIDENCE_VERSION,
    REFERENCE_TOKENIZERS_VERSION,
    TASK_RESOLVER_VERSION,
    TOKEN_PROXY_VERSION,
    EvalProtocolError,
    agent_cycle_gate_report,
    deterministic_result_signature,
    load_eval_manifest,
    paired_bootstrap_comparison,
    stratified_report,
)
from graphgraph.cli.evaluation import cmd_eval
from graphgraph.cli.parser import build_parser
from graphgraph.io import save_graph


def _result(
    task_id: str,
    *,
    query_class: str = "direct_lookup",
    split: str = "test",
    strata: tuple[str, ...] = ("exact",),
    recall: float = 1.0,
    confidence: float = 0.8,
    expected_answerable: bool | None = True,
    facet_completeness: float | None = None,
    latency_ms: float = 10.0,
    latency_state: str = "warm_runtime",
    ndcg_at_10: float = 1.0,
) -> EvalResult:
    return EvalResult(
        query=f"query for {task_id}",
        query_class=query_class,
        node_recall=recall,
        edge_recall=None,
        returned_nodes=3,
        returned_edges=2,
        token_estimate=100,
        task_id=task_id,
        project="fixture",
        split=split,
        strata=strata,
        facet_completeness=facet_completeness,
        latency_ms=latency_ms,
        latency_state=latency_state,
        mrr=ndcg_at_10,
        ndcg_at_5=ndcg_at_10,
        ndcg_at_10=ndcg_at_10,
        answerability_status="complete" if recall == 1.0 else "incomplete",
        answerability_confidence=confidence,
        expected_answerable=expected_answerable,
    )


def test_extended_task_fields_and_facets_are_loaded(tmp_path: Path) -> None:
    path = tmp_path / "tasks.json"
    path.write_text(
        json.dumps(
            {
                "tasks": [
                    {
                        "id": "T-001",
                        "query": "how does the flow work",
                        "query_class": "subsystem_summary",
                        "project": "fixture",
                        "split": "test",
                        "strata": ["compound", "conceptual"],
                        "expected_facets": {
                            "entry": ["start"],
                            "exit": ["finish"],
                        },
                        "oracle_refs": ["src/app.py:10-20"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    task = load_eval_tasks(path)[0]

    assert task.task_id == "T-001"
    assert task.project == "fixture"
    assert task.split == "test"
    assert task.strata == ("compound", "conceptual")
    assert task.expected_nodes == ("start", "finish")
    assert task.expected_facets == (("entry", ("start",)), ("exit", ("finish",)))
    assert task.oracle_refs == ("src/app.py:10-20",)


def test_committed_manifest_is_versioned_repository_held_out_and_independently_oracled() -> None:
    suite = load_eval_manifest(Path("eval/retrieval-v1/manifest.json"))

    assert suite.schema_version == EVAL_SCHEMA_VERSION
    assert suite.versions == {
        "task_resolver": TASK_RESOLVER_VERSION,
        "reference_tokenizers": REFERENCE_TOKENIZERS_VERSION,
        "token_proxy": TOKEN_PROXY_VERSION,
        "expected_evidence": EXPECTED_EVIDENCE_VERSION,
    }
    assert {project.split for project in suite.projects} == {"train", "calibration", "test"}

    repositories_by_split: dict[str, set[str]] = {}
    all_tasks = []
    for project in suite.projects:
        repositories_by_split.setdefault(project.split, set()).add(project.repository)
        all_tasks.extend(project.tasks)
        assert project.oracle_method != "graphgraph"
        assert project.oracle_refs

    split_sets = list(repositories_by_split.values())
    assert all(left.isdisjoint(right) for index, left in enumerate(split_sets) for right in split_sets[index + 1 :])
    assert any("lexical_disjoint" in task.strata for task in all_tasks)
    assert any("compound" in task.strata for task in all_tasks)
    assert any("ambiguous_name" in task.strata for task in all_tasks)
    assert any(task.expected_answerable is False for task in all_tasks)
    assert {project.language for project in suite.projects if any("receiver_oracle" in t.strata for t in project.tasks)} >= {
        "python",
        "javascript",
        "rust",
    }


def test_manifest_rejects_lexical_overlap_for_disjoint_tasks(tmp_path: Path) -> None:
    versions = {
        "task_resolver": TASK_RESOLVER_VERSION,
        "reference_tokenizers": REFERENCE_TOKENIZERS_VERSION,
        "token_proxy": TOKEN_PROXY_VERSION,
        "expected_evidence": EXPECTED_EVIDENCE_VERSION,
    }
    tasks_path = tmp_path / "tasks.json"
    tasks_path.write_text(
        json.dumps(
            {
                "schema_version": EVAL_SCHEMA_VERSION,
                "versions": versions,
                "project": {
                    "id": "fixture",
                    "repository": "owner/fixture",
                    "commit": "abc123",
                    "language": "python",
                    "split": "test",
                },
                "oracle": {"method": "source_inspection", "refs": ["src/app.py:1"]},
                "tasks": [
                    {
                        "id": "BAD-001",
                        "query": "where is parse request",
                        "query_class": "direct_lookup",
                        "strata": ["lexical_disjoint"],
                        "expected": ["parse_request"],
                        "oracle_refs": ["src/app.py:1"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": EVAL_SCHEMA_VERSION,
                "suite_id": "bad-suite",
                "versions": versions,
                "projects": [{"tasks": "tasks.json"}],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(EvalProtocolError, match="lexical_disjoint"):
        load_eval_manifest(manifest)


def test_stratified_report_keeps_failing_strata_visible() -> None:
    results = [
        _result("A", strata=("exact",), latency_state="cold_runtime", latency_ms=20.0),
        _result(
            "B",
            query_class="subsystem_summary",
            strata=("conceptual", "compound"),
            recall=0.0,
            confidence=0.7,
            facet_completeness=0.5,
            ndcg_at_10=0.0,
        ),
        _result(
            "C",
            query_class="negative_query",
            strata=("negative",),
            confidence=0.1,
            expected_answerable=False,
        ),
    ]

    report = stratified_report(results, calibration_bins=2, abstain_threshold=0.5)

    assert report["overall"]["count"] == 3
    assert report["by_query_class"]["subsystem_summary"]["node_recall_mean"] == 0.0
    assert report["by_stratum"]["conceptual"]["failing_tasks"] == ["B"]
    assert report["by_stratum"]["compound"]["facet_completeness_mean"] == 0.5
    assert report["overall"]["latency_ms"]["cold_runtime"]["samples"] == [20.0]
    assert report["overall"]["latency_ms"]["warm_runtime"]["samples"] == [10.0, 10.0]
    assert report["overall"]["calibration"]["count"] == 3
    assert report["overall"]["abstention"]["utility_mean"] == pytest.approx(1 / 3)


def test_agent_cycle_gate_report_enforces_external_accuracy_contract() -> None:
    results = []
    for project in ("flask", "express", "ripgrep"):
        results.append(
            _result(
                f"{project}-concept",
                query_class="subsystem_summary",
                split="calibration" if project == "flask" else "test",
                strata=("conceptual", "lexical_disjoint"),
                recall=1.0,
            )
        )
        results[-1] = replace(results[-1], project=project)
        results.append(
            replace(
                _result(
                    f"{project}-negative",
                    query_class="negative_query",
                    split="calibration" if project == "flask" else "test",
                    strata=("negative", "red_control"),
                    recall=0.0,
                    confidence=0.1,
                    expected_answerable=False,
                ),
                project=project,
                node_recall=None,
                answerability_status="unanswerable",
                returned_nodes=0,
                returned_edges=0,
                token_estimate=0,
            )
        )
    for index in range(12):
        results.append(
            replace(
                _result(
                    f"named-{index:02d}",
                    split="calibration" if index < 4 else "test",
                    strata=("exact",),
                    recall=1.0,
                ),
                project="flask" if index < 4 else "held-out",
            )
        )

    passing = agent_cycle_gate_report(results)

    assert passing["passed"] is True
    assert passing["checks"]["named_task_count"] is True
    assert passing["checks"]["conceptual_task_count"] is True
    assert passing["checks"]["negative_fail_closed"] is True
    assert passing["conceptual"]["full_recall_rate"] == 1.0

    mean_only_results = [
        replace(result, node_recall=0.8)
        if {"conceptual", "lexical_disjoint"} <= set(result.strata)
        else result
        for result in results
    ]
    mean_only = agent_cycle_gate_report(mean_only_results)
    assert mean_only["conceptual"]["recall_mean"] == 0.8
    assert mean_only["conceptual"]["full_recall_rate"] == 0.0
    assert mean_only["checks"]["conceptual_recall"] is False

    failing_results = list(results)
    failing_results[0] = replace(failing_results[0], node_recall=0.0)
    failing_results[3] = replace(
        failing_results[3],
        answerability_status="incomplete",
        answerability_confidence=0.7,
        returned_nodes=7,
        token_estimate=228,
    )

    failing = agent_cycle_gate_report(failing_results)

    assert failing["passed"] is False
    assert failing["conceptual"]["recall_mean"] == pytest.approx(2 / 3)
    assert failing["conceptual"]["full_recall_rate"] == pytest.approx(2 / 3)
    assert failing["negative"]["failing_tasks"] == ["express-negative"]


def test_paired_bootstrap_requires_a_practical_effect_and_is_deterministic() -> None:
    incumbent = [_result(f"T{i}", ndcg_at_10=0.4) for i in range(8)]
    candidate = [_result(f"T{i}", ndcg_at_10=0.5) for i in range(8)]

    first = paired_bootstrap_comparison(
        incumbent,
        candidate,
        metric="ndcg_at_10",
        minimum_effect=0.05,
        samples=500,
        seed=17,
    )
    again = paired_bootstrap_comparison(
        incumbent,
        candidate,
        metric="ndcg_at_10",
        minimum_effect=0.05,
        samples=500,
        seed=17,
    )

    assert first == again
    assert first["matched_tasks"] == 8
    assert first["mean_delta"] == pytest.approx(0.1)
    assert first["confidence_interval"] == pytest.approx([0.1, 0.1])
    assert first["verdict"] == "promote"

    too_small = paired_bootstrap_comparison(
        incumbent,
        [_result(f"T{i}", ndcg_at_10=0.41) for i in range(8)],
        metric="ndcg_at_10",
        minimum_effect=0.05,
        samples=100,
        seed=17,
    )
    assert too_small["verdict"] == "inconclusive"


def test_eval_parser_exposes_stratified_and_paired_protocol_options() -> None:
    args = build_parser().parse_args(
        [
            "eval",
            "--graph",
            "graph.gg",
            "--tasks",
            "tasks.json",
            "--report",
            "--baseline-results",
            "incumbent.json",
            "--compare-metric",
            "facet_completeness",
            "--minimum-effect",
            "0.05",
            "--bootstrap-samples",
            "2000",
            "--bootstrap-seed",
            "23",
        ]
    )

    assert args.report is True
    assert args.baseline_results == "incumbent.json"
    assert args.compare_metric == "facet_completeness"
    assert args.minimum_effect == 0.05
    assert args.bootstrap_samples == 2000
    assert args.bootstrap_seed == 23


def test_repeatability_signature_excludes_latency_but_not_quality() -> None:
    first = [_result("T", latency_ms=10.0, ndcg_at_10=0.5)]
    slower = [_result("T", latency_ms=40.0, ndcg_at_10=0.5)]
    changed = [_result("T", latency_ms=10.0, ndcg_at_10=0.4)]

    assert deterministic_result_signature(first) == deterministic_result_signature(slower)
    assert deterministic_result_signature(first) != deterministic_result_signature(changed)


def test_eval_command_emits_stratified_report(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    graph_path = tmp_path / "graph.json"
    tasks_path = tmp_path / "tasks.json"
    save_graph(Graph(nodes={"target": Node("target", "target", "function", "src/target.py")}), graph_path)
    tasks_path.write_text(
        json.dumps(
            [
                {
                    "id": "T-REPORT",
                    "query": "target",
                    "query_class": "direct_lookup",
                    "strata": ["exact"],
                    "expected": ["target"],
                }
            ]
        ),
        encoding="utf-8",
    )

    cmd_eval(
        Namespace(
            graph=str(graph_path),
            tasks=str(tasks_path),
            max_nodes=None,
            source_mode="off",
            report=True,
            baseline_results=None,
            calibration=False,
            calibration_bins=2,
            abstain_threshold=0.5,
        )
    )
    payload = json.loads(capsys.readouterr().out)

    assert payload["results"][0]["task_id"] == "T-REPORT"
    assert payload["results"][0]["latency_ms"] >= 0.0
    assert payload["report"]["by_stratum"]["exact"]["node_recall_mean"] == 1.0
