from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from graphgraph import (
    Edge,
    Graph,
    Node,
)
from graphgraph.retrieval import (
    retrieve_context,
)


class DevelopmentFieldLogRetrievalTest(unittest.TestCase):
    def test_scope_mode_strict_blocks_and_expand_allows_structural_boundary(self) -> None:
        graph = Graph(
            nodes={
                "A": Node("A", "run_formula_yield_benchmark", "function", "crates/locus-pipeline/src/yield.rs"),
                "B": Node("B", "external_consumer", "function", "crates/locus-engine/src/lib.rs"),
            },
            edges=[Edge("A", "B", "calls")],
        )
        strict = retrieve_context(
            graph, "run_formula_yield_benchmark", "direct_lookup", hops=1,
            scopes=("crates/locus-pipeline",), scope_mode="strict",
        )
        expanded = retrieve_context(
            graph, "run_formula_yield_benchmark", "direct_lookup", hops=1,
            scopes=("crates/locus-pipeline",), scope_mode="expand",
        )
        self.assertEqual(strict.nodes, {"A"})
        self.assertIn("B", expanded.nodes)
        self.assertEqual(expanded.metadata["quality"]["cross_scope_nodes"], 1)

    def test_affected_tests_reports_direct_evidence_and_runnable_command(self) -> None:
        graph = Graph(
            nodes={
                "RUN": Node("RUN", "run_formula_yield_benchmark", "function", "crates/locus-pipeline/src/yield.rs"),
                "VAL": Node("VAL", "validate_candidates_detailed", "method", "crates/locus-pipeline/src/lib.rs"),
                "TEST": Node("TEST", "pinned_formula_corpus", "function", "crates/locus-pipeline/tests/yield_benchmark.rs"),
                "NOISE": Node("NOISE", "identity_validation", "function", "crates/locus-core/src/numerical.rs"),
            },
            edges=[
                Edge("RUN", "VAL", "calls"),
                Edge("TEST", "RUN", "calls"),
                Edge("NOISE", "VAL", "references"),
            ],
        )
        result = retrieve_context(
            graph,
            "which tests cover run_formula_yield_benchmark and validate_candidates_detailed",
            "affected_tests",
            hops=2,
        )
        affected = result.metadata["affected_tests"]
        self.assertEqual([item["id"] for item in affected["direct"]], ["TEST"])
        self.assertEqual(affected["commands"], ["cargo test -p locus-pipeline --test yield_benchmark"])
        self.assertEqual(affected["direct"][0]["root_paths"][0]["root"]["id"], "RUN")
        self.assertEqual(
            affected["command_provenance"][0]["tests"][0]["id"],
            "TEST",
        )
        self.assertEqual(
            affected["direct"][0]["covers"],
            [
                {"id": "RUN", "label": "run_formula_yield_benchmark"},
                {"id": "VAL", "label": "validate_candidates_detailed"},
            ],
        )
        self.assertEqual(result.metadata["inferred_scope"], "crates/locus-pipeline")
        self.assertNotIn("NOISE", result.starts)

    def test_affected_tests_reserves_multi_field_assertion_ahead_of_generic_tests(self) -> None:
        graph = Graph(
            nodes={
                "CANDIDATE": Node(
                    "CANDIDATE",
                    "candidate_generation",
                    "field",
                    "crates/locus-pipeline/src/yield_benchmark.rs",
                ),
                "EXTRACTION": Node(
                    "EXTRACTION",
                    "extraction_only",
                    "field",
                    "crates/locus-pipeline/src/yield_benchmark.rs",
                ),
                "Z_PINNED": Node(
                    "Z_PINNED",
                    "pinned_formula_corpus_produces_machine_readable_yield_report",
                    "function",
                    "crates/locus-pipeline/tests/yield_benchmark.rs",
                ),
                **{
                    f"A_NOISE_{index}": Node(
                        f"A_NOISE_{index}",
                        f"generic_pipeline_test_{index}",
                        "function",
                        f"crates/locus-pipeline/tests/pipeline_{index}.rs",
                    )
                    for index in range(8)
                },
            },
            edges=[
                Edge(
                    "Z_PINNED",
                    "CANDIDATE",
                    "references",
                    confidence=0.94,
                    provenance="tree_sitter_type_resolved_field_assertion",
                ),
                Edge(
                    "Z_PINNED",
                    "EXTRACTION",
                    "references",
                    confidence=0.94,
                    provenance="tree_sitter_type_resolved_field_assertion",
                ),
                *[
                    Edge(f"A_NOISE_{index}", "CANDIDATE", "references", confidence=0.6)
                    for index in range(8)
                ],
            ],
        )

        result = retrieve_context(
            graph,
            "Which tests directly validate candidate_generation and extraction_only?",
            "affected_tests",
            hops=2,
            max_nodes=4,
        )

        affected = result.metadata["affected_tests"]
        self.assertEqual(affected["direct"][0]["id"], "Z_PINNED")
        self.assertTrue(affected["direct"][0]["in_packet"])
        self.assertIn("Z_PINNED", result.nodes)
        self.assertEqual(result.metadata["facet_coverage"]["coverage_ratio"], 1.0)
        self.assertEqual(result.metadata["answerability"]["status"], "answerable")

    def test_affected_tests_drops_intent_word_homonym_roots(self) -> None:
        graph = Graph(
            nodes={
                "BASE": Node("BASE", "SourceCaseBaseline", "struct", "crates/locus-pipeline/src/yield.rs"),
                "EVAL": Node("EVAL", "evaluate", "method", "crates/locus-pipeline/src/yield.rs", parent="BASE"),
                "HOMONYM": Node(
                    "HOMONYM",
                    "affected_packages",
                    "method",
                    "crates/locus-frontends/src/planner.rs",
                ),
                "DIRECT": Node(
                    "DIRECT",
                    "representative_disk_corpus_meets_all_case_expectations",
                    "function",
                    "crates/locus-pipeline/tests/yield_benchmark.rs",
                ),
                "UNRELATED": Node(
                    "UNRELATED",
                    "planner_test",
                    "function",
                    "crates/locus-frontends/tests/suite/planner_test.rs",
                ),
            },
            edges=[
                Edge("BASE", "EVAL", "defines"),
                Edge("DIRECT", "EVAL", "calls", confidence=0.95, provenance="tree_sitter_type_resolved"),
                Edge("UNRELATED", "HOMONYM", "calls", confidence=0.95, provenance="tree_sitter_type_resolved"),
            ],
        )

        result = retrieve_context(
            graph,
            "If SourceCaseBaseline evaluate changes, which tests are affected?",
            "affected_tests",
            hops=2,
        )

        affected = result.metadata["affected_tests"]
        recommended = {item["id"] for item in [*affected["direct"], *affected["transitive"]]}
        self.assertIn("DIRECT", recommended)
        self.assertNotIn("UNRELATED", recommended)
        self.assertNotIn("HOMONYM", result.starts)

    def test_domain_facets_credit_promotable_yield_and_parent_traversal_rejection(self) -> None:
        from graphgraph.retrieval.context import facet_coverage

        graph = Graph(
            nodes={
                "YIELD": Node("YIELD", "min_promotable_candidates", "field", "src/yield.rs"),
                "UNSAFE": Node(
                    "UNSAFE",
                    "disk_backed_source_corpus_rejects_parent_traversal",
                    "function",
                    "tests/yield_benchmark.rs",
                ),
            }
        )

        coverage = facet_coverage(
            graph,
            {"YIELD", "UNSAFE"},
            (
                ("yield loss", ("yield", "loss")),
                ("unsafe path rejection", ("unsafe", "path", "rejection")),
            ),
        )

        self.assertEqual(coverage["unfulfilled"], [])

    def test_code_convention_query_requires_code_not_document_mentions(self) -> None:
        query = (
            "Where do tests load fixture files using CARGO_MANIFEST_DIR, "
            "include_str, read_to_string, or tests/fixtures?"
        )
        graph = Graph(
            nodes={
                "DOC": Node(
                    "DOC",
                    "Fixture loading notes",
                    "paragraph",
                    "docs/testing.md",
                    summary="Use CARGO_MANIFEST_DIR include_str and read_to_string for tests fixtures.",
                )
            }
        )

        result = retrieve_context(graph, query, "direct_lookup", hops=1)

        self.assertEqual(result.metadata["answerability"]["status"], "incomplete")
        self.assertTrue(result.metadata["structural_facet_coverage"]["unfulfilled"])

    def test_consumer_reverse_lookup_promotes_contract_members_and_direct_test(self) -> None:
        graph = Graph(
            nodes={
                "BASE": Node("BASE", "SourceCaseBaseline", "struct", "src/yield.rs"),
                "EVAL": Node("EVAL", "evaluate", "method", "src/yield.rs", parent="BASE"),
                "MIN": Node("MIN", "min_promotable_candidates", "field", "src/yield.rs", parent="BASE"),
                "TEST": Node(
                    "TEST",
                    "representative_disk_corpus_meets_all_case_expectations",
                    "function",
                    "tests/yield_benchmark.rs",
                ),
            },
            edges=[
                Edge("BASE", "EVAL", "contains"),
                Edge("BASE", "MIN", "contains"),
                Edge("TEST", "EVAL", "calls", confidence=0.95, provenance="tree_sitter_type_resolved"),
            ],
        )
        query = "Where is SourceCaseBaseline, what metrics does it enforce, and which test consumes it?"

        result = retrieve_context(graph, query, "reverse_lookup", hops=1)

        self.assertTrue({"BASE", "EVAL", "MIN", "TEST"} <= result.nodes)
        self.assertEqual(result.metadata["answerability"]["status"], "answerable")

    def test_reverse_lookup_fulfills_registration_and_exercise_from_topology(self) -> None:
        graph = Graph(
            nodes={
                "ADVISOR": Node(
                    "ADVISOR",
                    "StochasticProcessesAdvisor",
                    "struct",
                    "src/stochastic_processes.rs",
                ),
                "EXAMINE": Node(
                    "EXAMINE",
                    "examine",
                    "method",
                    "src/stochastic_processes.rs",
                    parent="ADVISOR",
                ),
                "REGISTRY": Node(
                    "REGISTRY",
                    "default_advisors",
                    "function",
                    "src/lib.rs",
                ),
                "TEST": Node(
                    "TEST",
                    "markov_gemv_emits_refutable_transition_hypothesis",
                    "function",
                    "tests/suite/stochastic_processes_test.rs",
                ),
                "TRAIT": Node(
                    "TRAIT",
                    "Advisor",
                    "trait",
                    "src/advisor.rs",
                ),
                "OTHER": Node(
                    "OTHER",
                    "ControlTheoryAdvisor",
                    "struct",
                    "src/control_theory.rs",
                ),
            },
            edges=[
                Edge("ADVISOR", "EXAMINE", "contains"),
                Edge("ADVISOR", "TRAIT", "implements"),
                Edge("OTHER", "TRAIT", "implements"),
                Edge("REGISTRY", "ADVISOR", "references"),
                Edge(
                    "TEST",
                    "EXAMINE",
                    "calls",
                    provenance="tree_sitter_type_resolved",
                ),
            ],
        )

        result = retrieve_context(
            graph,
            (
                "Where is StochasticProcessesAdvisor registered and which tests "
                "exercise it?"
            ),
            "reverse_lookup",
            hops=1,
            anchor_limit=1,
            max_nodes=12,
        )

        self.assertIn("TEST", result.nodes)
        self.assertNotIn("OTHER", result.nodes)
        self.assertEqual(result.metadata["facet_coverage"]["unfulfilled"], [])
        self.assertEqual(result.metadata["answerability"]["status"], "answerable")
        fulfilled = {
            item["facet"]: set(item["evidence"])
            for item in result.metadata["facet_coverage"]["fulfilled"]
        }
        self.assertEqual(fulfilled["registered"], {"REGISTRY"})
        self.assertEqual(fulfilled["exercise"], {"TEST"})

    def test_affected_tests_uses_aggregated_cargo_harness_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            crate = Path(tmp) / "locus-frontends"
            module = crate / "tests" / "suite" / "fpcore_test.rs"
            module.parent.mkdir(parents=True)
            (crate / "Cargo.toml").write_text(
                '[package]\nname = "locus-frontends"\nversion = "0.1.0"\n',
                encoding="utf-8",
            )
            (module.parent / "main.rs").write_text("mod fpcore_test;\n", encoding="utf-8")
            module.write_text("#[test]\nfn parses_fpcore() {}\n", encoding="utf-8")
            graph = Graph(
                nodes={
                    "RUN": Node("RUN", "parse_fpcore", "function", "crates/locus-frontends/src/fpcore.rs"),
                    "TEST": Node(
                        "TEST",
                        "parses_fpcore",
                        "function",
                        "crates/locus-frontends/tests/suite/fpcore_test.rs",
                        source=str(module),
                    ),
                },
                edges=[Edge("TEST", "RUN", "calls")],
            )
            result = retrieve_context(graph, "which tests cover parse_fpcore", "affected_tests", hops=2)

        affected = result.metadata["affected_tests"]
        self.assertEqual(affected["commands"], ["cargo test -p locus-frontends --test suite fpcore_test"])
        self.assertEqual(affected["direct"][0]["covers"], [{"id": "RUN", "label": "parse_fpcore"}])

    def test_affected_tests_include_tests_that_call_an_owned_method(self) -> None:
        graph = Graph(
            nodes={
                "ADVISOR": Node(
                    "ADVISOR",
                    "StochasticProcessesAdvisor",
                    "struct",
                    "src/stochastic_processes.rs",
                ),
                "EXAMINE": Node(
                    "EXAMINE",
                    "examine",
                    "method",
                    "src/stochastic_processes.rs",
                    parent="ADVISOR",
                ),
                "POSITIVE": Node(
                    "POSITIVE",
                    "markov_gemv_emits_refutable_transition_hypothesis",
                    "function",
                    "tests/suite/stochastic_processes_test.rs",
                ),
            },
            edges=[
                Edge("ADVISOR", "EXAMINE", "contains"),
                Edge(
                    "POSITIVE",
                    "EXAMINE",
                    "calls",
                    provenance="tree_sitter_type_resolved",
                ),
            ],
        )

        result = retrieve_context(
            graph,
            "Which tests cover StochasticProcessesAdvisor?",
            "affected_tests",
            hops=2,
        )

        affected = result.metadata["affected_tests"]
        self.assertEqual([item["id"] for item in affected["direct"]], ["POSITIVE"])
        self.assertEqual(
            affected["direct"][0]["covers"],
            [{"id": "ADVISOR", "label": "StochasticProcessesAdvisor"}],
        )

    def test_affected_tests_treats_inline_rust_test_facts_as_direct_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            crate = Path(tmp) / "locus-engine"
            source = crate / "src" / "scheduling.rs"
            source.parent.mkdir(parents=True)
            (crate / "Cargo.toml").write_text(
                '[package]\nname = "locus-engine"\nversion = "0.1.0"\n',
                encoding="utf-8",
            )
            (crate / "src" / "lib.rs").write_text("mod scheduling;\n", encoding="utf-8")
            source.write_text(
                "fn schedule_candidates_for_expr() {}\n"
                "#[cfg(test)] mod tests {\n"
                "    #[test] fn reports_template() { schedule_candidates_for_expr(); }\n"
                "}\n",
                encoding="utf-8",
            )
            graph = Graph(
                nodes={
                    "RUN": Node(
                        "RUN",
                        "schedule_candidates_for_expr",
                        "function",
                        "crates/locus-engine/src/scheduling.rs",
                    ),
                    "TEST": Node(
                        "TEST",
                        "reports_template",
                        "function",
                        "crates/locus-engine/src/scheduling.rs",
                        facts=("role:test", "rust_attribute:test"),
                        source=str(source),
                    ),
                },
                edges=[Edge("TEST", "RUN", "calls", provenance="tree_sitter")],
            )
            result = retrieve_context(
                graph,
                "which tests cover schedule_candidates_for_expr",
                "affected_tests",
                hops=2,
            )

        affected = result.metadata["affected_tests"]
        self.assertEqual([item["id"] for item in affected["direct"]], ["TEST"])
        self.assertEqual(
            affected["commands"],
            ["cargo test -p locus-engine reports_template --lib"],
        )

    def test_affected_tests_recovers_inline_rust_tests_from_legacy_graph_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            crate = Path(tmp) / "locus-frontends"
            source = crate / "src" / "planner.rs"
            source.parent.mkdir(parents=True)
            (crate / "Cargo.toml").write_text(
                '[package]\nname = "locus-frontends"\nversion = "0.1.0"\n',
                encoding="utf-8",
            )
            (crate / "src" / "lib.rs").write_text("mod planner;\n", encoding="utf-8")
            source.write_text(
                "fn plan_writes() {}\n"
                "#[cfg(test)] mod tests {\n"
                "    #[test]\n"
                "    fn plan_writes_reports_each_target_once() { plan_writes(); }\n"
                "}\n",
                encoding="utf-8",
            )
            graph = Graph(
                nodes={
                    "PLAN": Node(
                        "PLAN",
                        "plan_writes",
                        "function",
                        "crates/locus-frontends/src/planner.rs",
                    ),
                    "TEST": Node(
                        "TEST",
                        "plan_writes_reports_each_target_once",
                        "function",
                        "crates/locus-frontends/src/planner.rs",
                        summary="L4",
                        source=str(source),
                    ),
                },
                edges=[Edge("TEST", "PLAN", "calls", provenance="tree_sitter")],
            )
            result = retrieve_context(
                graph,
                "which direct tests cover plan_writes",
                "affected_tests",
                hops=2,
                anchor_paths=("crates/locus-frontends/src/planner.rs",),
            )

        affected = result.metadata["affected_tests"]
        self.assertEqual([item["id"] for item in affected["direct"]], ["TEST"])
        self.assertIn(
            "cargo test -p locus-frontends plan_writes_reports_each_target_once --lib",
            affected["commands"],
        )

    def test_changed_integration_test_path_emits_command_on_uncertain_route(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            crate = Path(tmp) / "locus-engine"
            source = crate / "tests" / "suite" / "groebner_test.rs"
            source.parent.mkdir(parents=True)
            (crate / "Cargo.toml").write_text(
                '[package]\nname = "locus-engine"\nversion = "0.1.0"\n',
                encoding="utf-8",
            )
            (source.parent / "main.rs").write_text("mod groebner_test;\n", encoding="utf-8")
            source.write_text("#[test]\nfn reports_fragment_boundary() {}\n", encoding="utf-8")
            graph = Graph(
                nodes={
                    "TEST": Node(
                        "TEST",
                        "reports_fragment_boundary",
                        "function",
                        "crates/locus-engine/tests/suite/groebner_test.rs",
                        source=str(source),
                    ),
                }
            )
            result = retrieve_context(
                graph,
                "finite field fragment provenance",
                "subsystem_summary",
                hops=1,
                anchor_paths=("crates/locus-engine/tests/suite/groebner_test.rs",),
            )

        self.assertEqual(
            result.metadata["affected_tests"]["commands"],
            ["cargo test -p locus-engine --test suite groebner_test"],
        )
        self.assertEqual(
            result.metadata["affected_tests"]["commands_by_role"]["changed_path_regression"],
            ["cargo test -p locus-engine --test suite groebner_test"],
        )

    def test_changed_cargo_directory_main_uses_directory_integration_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            crate = Path(tmp) / "locus-advisors"
            source = crate / "tests" / "suite" / "main.rs"
            source.parent.mkdir(parents=True)
            (crate / "Cargo.toml").write_text(
                '[package]\nname = "locus-advisors"\nversion = "0.1.0"\n',
                encoding="utf-8",
            )
            source.write_text("fn main() {}\n", encoding="utf-8")
            graph = Graph(
                nodes={
                    "MAIN": Node(
                        "MAIN",
                        "suite",
                        "function",
                        "crates/locus-advisors/tests/suite/main.rs",
                        source=str(source),
                    ),
                }
            )

            result = retrieve_context(
                graph,
                "stochastic advisor suite",
                "subsystem_summary",
                hops=1,
                anchor_paths=("crates/locus-advisors/tests/suite/main.rs",),
            )

        self.assertEqual(
            result.metadata["affected_tests"]["commands"],
            ["cargo test -p locus-advisors --test suite"],
        )

    def test_test_path_does_not_turn_file_fields_or_locals_into_test_cases(self) -> None:
        from graphgraph.retrieval.context import _is_test_node

        path = "crates/locus-engine/tests/suite/groebner_test.rs"
        self.assertFalse(_is_test_node(Node("FILE", "groebner_test.rs", "rust", path)))
        self.assertFalse(_is_test_node(Node("FIELD", "value", "field", path)))
        self.assertTrue(_is_test_node(Node("TEST", "reports_boundary", "function", path)))

    def test_exact_changed_paths_compile_to_primary_per_file_anchors(self) -> None:
        graph = Graph(
            nodes={
                "CORE": Node(
                    "CORE",
                    "evidence_is_consistent",
                    "method",
                    "crates/locus-core/src/finding.rs",
                    facts=("domain:obligation",),
                ),
                "ENGINE": Node(
                    "ENGINE",
                    "ScheduleArtifactStatus",
                    "enum",
                    "crates/locus-engine/src/scheduling.rs",
                ),
                "FRONTEND": Node(
                    "FRONTEND",
                    "resolve_project_effects",
                    "function",
                    "crates/locus-frontends/src/source/effects.rs",
                    facts=("semantic_scope:interprocedural", "policy:conservative"),
                ),
                "NOISE": Node(
                    "NOISE",
                    "obligation_consistency_schedule_effects",
                    "function",
                    "src/unrelated_scope_consistency.rs",
                    summary="obligation consistency schedule artifact effects",
                ),
            },
        )
        result = retrieve_context(
            graph,
            (
                "Validate obligation consistency, schedule artifact readiness, "
                "and conservative interprocedural effects; identify affected tests."
            ),
            "affected_tests",
            hops=1,
            anchor_paths=(
                "crates/locus-core/src/finding.rs",
                "crates/locus-engine/src/scheduling.rs",
                "crates/locus-frontends/src/source/effects.rs",
            ),
        )

        self.assertTrue({"CORE", "ENGINE", "FRONTEND"} <= set(result.starts))
        self.assertNotIn("NOISE", result.starts)
        self.assertTrue(all(item["anchors"] for item in result.metadata["anchor_paths"]))

    def test_exact_changed_path_reserves_multiple_query_facets_in_one_file(self) -> None:
        path = "src/graphgraph/retrieval/context.py"
        graph = Graph(
            nodes={
                "ANCHOR": Node("ANCHOR", "preferred_path_anchor_matches", "function", path),
                "RECEIPT": Node(
                    "RECEIPT",
                    "reconcile_semantic_retrieval_receipt",
                    "function",
                    path,
                ),
                "NOISE": Node("NOISE", "unrelated_helper", "function", path),
            }
        )

        result = retrieve_context(
            graph,
            "Validate exact path anchoring and semantic receipt consistency.",
            "multi_hop_path",
            hops=1,
            anchor_paths=(path,),
        )

        self.assertTrue({"ANCHOR", "RECEIPT"} <= set(result.starts))
        self.assertNotIn("NOISE", result.starts)

    def test_exact_changed_path_uses_file_node_for_unmatched_fallback(self) -> None:
        path = "src/planner.rs"
        graph = Graph(
            nodes={
                "FILE": Node("FILE", "planner.rs", "rust", path),
                "UNRELATED": Node("UNRELATED", "minimal_reduced", "function", path),
            },
            edges=[Edge("FILE", "UNRELATED", "contains")],
        )

        result = retrieve_context(
            graph,
            "finite field fragment boundary",
            "affected_tests",
            hops=1,
            anchor_paths=(path,),
        )

        self.assertEqual(result.starts, ("FILE",))
        self.assertEqual(result.metadata["anchor_paths"][0]["role"], "file_fallback")

    def test_preferred_path_anchors_do_not_repeat_global_search_per_facet(self) -> None:
        from graphgraph.retrieval.context import preferred_path_anchor_matches

        path = "src/planner.rs"
        graph = Graph(
            nodes={
                "FILE": Node("FILE", "planner.rs", "rust", path),
                "PLAN": Node("PLAN", "plan_writes", "method", path),
            },
            edges=[Edge("FILE", "PLAN", "contains")],
        )

        with patch(
            "graphgraph.retrieval.context.search_nodes",
            side_effect=AssertionError("exact-path anchoring must stay path-local"),
        ):
            matches = preferred_path_anchor_matches(
                graph,
                "planner write deduplication",
                "affected_tests",
                (path,),
                (("planner write deduplication", ("planner", "write", "deduplication")),),
            )

        self.assertEqual(matches[0].node.id, "PLAN")
        with patch(
            "graphgraph.retrieval.context.search_nodes",
            side_effect=AssertionError("exact-path retrieval must not run global search"),
        ):
            result = retrieve_context(
                graph,
                "planner write deduplication",
                "affected_tests",
                hops=1,
                anchor_paths=(path,),
            )
        self.assertEqual(result.starts, ("PLAN",))

    def test_exact_path_keeps_one_symbol_winner_per_facet_not_every_owner_member(self) -> None:
        path = "src/planner.rs"
        graph = Graph(
            nodes={
                "OWNER": Node("OWNER", "TransformPlanner", "struct", path),
                "PLAN": Node(
                    "PLAN",
                    "plan_writes",
                    "method",
                    path,
                    summary="impl TransformPlanner; reports each target once",
                ),
                "NOISE": Node(
                    "NOISE",
                    "affected_packages",
                    "method",
                    path,
                    summary="impl TransformPlanner",
                ),
            },
        )

        result = retrieve_context(
            graph,
            "TransformPlanner plan deduplication",
            "affected_tests",
            hops=1,
            anchor_paths=(path,),
        )

        self.assertEqual(set(result.starts), {"OWNER", "PLAN"})
        self.assertNotIn("NOISE", result.starts)

    def test_facet_parser_drops_output_instructions_and_connective_phrases(self) -> None:
        from graphgraph.retrieval.context import query_facets

        facets = query_facets(
            "After adding TransformPlanner plan deduplication, return minimal runnable Cargo commands "
            "for direct behavioral tests, then focus on its own step."
        )

        self.assertEqual(
            facets,
            (
                ("TransformPlanner", ("transform", "planner")),
                ("plan deduplication", ("plan", "deduplication")),
            ),
        )
        self.assertNotIn(
            "paths",
            {
                label
                for label, _terms in query_facets(
                    "For the exact changed paths, identify TransformPlanner plan deduplication."
                )
            },
        )

    def test_facet_coverage_translates_behavior_words_to_code_level_forms(self) -> None:
        from graphgraph.retrieval.context import facet_coverage

        graph = Graph(
            nodes={
                "PLAN_TEST": Node(
                    "PLAN_TEST",
                    "plan_writes_reports_each_target_once",
                    "function",
                    "src/planner.rs",
                ),
                "PINNED": Node(
                    "PINNED",
                    "evaluate_pinned_corpus",
                    "method",
                    "src/yield.rs",
                    facts=("requires exact case and file counts",),
                ),
            },
        )

        coverage = facet_coverage(
            graph,
            set(graph.nodes),
            (
                ("plan deduplication", ("plan", "deduplication")),
                ("pinned corpus equality", ("pinned", "corpus", "equality")),
            ),
        )

        self.assertEqual(coverage["unfulfilled"], [])

    def test_semantic_reconciliation_fulfills_direct_and_command_output_facets(self) -> None:
        from graphgraph.planning import QueryRoute
        from graphgraph.retrieval import reconcile_retrieval_receipt

        graph = Graph(
            nodes={
                "TARGET": Node("TARGET", "evaluate_pinned_corpus", "method", "src/yield.rs"),
                "TEST": Node("TEST", "representative_corpus", "function", "tests/yield.rs"),
            },
            edges=[Edge("TEST", "TARGET", "calls", provenance="tree_sitter_type_resolved")],
        )
        result = retrieve_context(
            graph,
            "which direct tests cover evaluate_pinned_corpus and what cargo runs",
            "affected_tests",
            hops=2,
        )
        result.metadata["facet_coverage"] = {
            "fulfilled": [],
            "unfulfilled": ["direct", "cargo runs"],
            "coverage_ratio": 0.0,
            "warning": "unfulfilled query facets",
        }
        result.metadata["answerability"] = {
            "status": "incomplete",
            "abstained": False,
            "reason": "unfulfilled query facets",
        }
        result.metadata["affected_tests"]["commands"] = ["cargo test -p locus-pipeline --test yield_benchmark"]
        result.metadata["affected_tests"]["command_provenance"] = [{
            "command": "cargo test -p locus-pipeline --test yield_benchmark",
            "tests": [{"id": "TEST"}],
        }]

        errors = reconcile_retrieval_receipt(
            graph,
            result,
            route=QueryRoute("affected_tests", 1.0, 1.0, ("explicit query class",)),
            automatic_route=False,
        )

        self.assertEqual(errors, ())
        self.assertEqual(result.metadata["facet_coverage"]["unfulfilled"], [])
        self.assertEqual(result.metadata["answerability"]["status"], "answerable")
        self.assertFalse(result.metadata["answerability"]["abstained"])
        self.assertTrue(result.metadata["semantic_validation"]["ok"])

    def test_packet_quality_reports_query_specific_topology_trust(self) -> None:
        graph = Graph(
            nodes={
                "ENTRY": Node("ENTRY", "entry", "function", "src/app.py"),
                "TRUSTED": Node("TRUSTED", "trusted", "function", "src/app.py"),
                "AMBIGUOUS": Node("AMBIGUOUS", "ambiguous", "method", "src/app.py"),
            },
            edges=[
                Edge(
                    "ENTRY",
                    "TRUSTED",
                    "calls",
                    confidence=0.95,
                    provenance="tree_sitter_type_resolved",
                ),
                Edge(
                    "ENTRY",
                    "AMBIGUOUS",
                    "calls",
                    confidence=0.35,
                    provenance="tree_sitter_ambiguous_call",
                ),
            ],
        )

        result = retrieve_context(graph, "how does entry work", "subsystem_summary", hops=1)

        topology = result.metadata["quality"]["topology_trust"]
        self.assertEqual(topology["status"], "mixed")
        self.assertEqual(topology["trusted_call_edges"], 1)
        self.assertEqual(topology["ambiguous_call_edges"], 1)

    def test_call_dependent_queries_include_global_topology_coverage(self) -> None:
        graph = Graph(
            nodes={
                "CALLER": Node("CALLER", "caller", "function", "src/app.py"),
                "TARGET": Node("TARGET", "target", "function", "src/app.py"),
            },
            edges=[
                Edge(
                    "CALLER",
                    "TARGET",
                    "calls",
                    confidence=0.95,
                    provenance="tree_sitter_type_resolved",
                )
            ],
            metadata={
                "member_calls_global_resolved": "10",
                "member_calls_global_ambiguous": "2",
                "member_calls_global_unknown_receiver": "40",
                "member_calls_global_unresolved": "48",
            },
        )

        result = retrieve_context(
            graph,
            "what calls target",
            "reverse_lookup",
            hops=1,
        )

        topology = result.metadata["quality"]["topology_trust"]
        self.assertEqual(topology["local_status"], "high")
        self.assertEqual(topology["global_status"], "low")
        self.assertEqual(topology["status"], "low")
        self.assertEqual(topology["global_call_coverage_ratio"], 0.1)
        self.assertEqual(topology["scope"], "selected_packet+global_extraction")

    def test_qualified_method_query_selects_only_its_own_test(self) -> None:
        path = "crates/locus-pipeline/src/yield_benchmark.rs"
        graph = Graph(
            nodes={
                "OLD_TYPE": Node("OLD_TYPE", "YieldBaseline", "struct", path),
                "NEW_TYPE": Node("NEW_TYPE", "SourceYieldBaseline", "struct", path),
                "OLD_EVAL": Node("OLD_EVAL", "evaluate", "method", path, summary="[YieldBaseline::evaluate]"),
                "NEW_EVAL": Node(
                    "NEW_EVAL", "evaluate", "method", path, summary="[SourceYieldBaseline::evaluate]"
                ),
                "OLD_TEST": Node(
                    "OLD_TEST", "formula_baseline", "function",
                    "crates/locus-pipeline/tests/yield_benchmark.rs",
                ),
                "NEW_TEST": Node(
                    "NEW_TEST", "source_baseline", "function",
                    "crates/locus-pipeline/tests/source_yield.rs",
                ),
            },
            edges=[
                Edge("OLD_TYPE", "OLD_EVAL", "contains"),
                Edge("NEW_TYPE", "NEW_EVAL", "contains"),
                Edge("OLD_TEST", "OLD_EVAL", "calls"),
                Edge("NEW_TEST", "NEW_EVAL", "calls"),
            ],
        )
        result = retrieve_context(
            graph,
            "which tests cover SourceYieldBaseline::evaluate",
            "affected_tests",
            hops=2,
        )
        self.assertEqual(result.starts, ("NEW_EVAL",))
        self.assertNotIn("OLD_EVAL", result.starts)
        self.assertEqual(
            [item["id"] for item in result.metadata["affected_tests"]["direct"]],
            ["NEW_TEST"],
        )

    def test_qualified_method_bypasses_a_crowded_lexical_candidate_list(self) -> None:
        from graphgraph.retrieval.context import select_anchor_matches
        from graphgraph.retrieval.models import Match

        owner = Node("TYPE", "SourceYieldBaseline", "struct", "src/yield.rs")
        method = Node(
            "EVAL", "evaluate", "method", "src/yield.rs",
            summary="[SourceYieldBaseline::evaluate]",
        )
        graph = Graph(nodes={"TYPE": owner, "EVAL": method})

        selected = select_anchor_matches(
            (Match(owner, 30.0, ("label_exact:sourceyieldbaseline",)),),
            4,
            "affected_tests",
            query="which tests cover SourceYieldBaseline::evaluate",
            graph=graph,
        )

        self.assertEqual([match.node.id for match in selected], ["EVAL"])
        self.assertEqual(selected[0].reasons, ("qualified_exact:SourceYieldBaseline::evaluate",))

    def test_exact_subsystem_anchor_beats_unrelated_generic_metric(self) -> None:
        pipeline = "crates/locus-pipeline/src/yield_benchmark.rs"
        graph = Graph(
            nodes={
                "BASE": Node("BASE", "SourceYieldBaseline", "struct", pipeline),
                "EVAL": Node("EVAL", "evaluate", "method", pipeline, summary="SourceYieldBaseline::evaluate"),
                "PARSE_FIELD": Node("PARSE_FIELD", "max_parse_failures", "field", pipeline),
                "HELPER": Node(
                    "HELPER", "parse_failure_findings", "function",
                    "crates/locus-frontends/src/normalizer.rs",
                ),
                "GOOD_TEST": Node(
                    "GOOD_TEST", "source_baseline_positive", "function",
                    "crates/locus-pipeline/tests/yield_benchmark.rs",
                ),
                "NOISE_TEST": Node(
                    "NOISE_TEST", "fpcore_parse_failures", "function",
                    "crates/locus-frontends/tests/suite/fpcore_test.rs",
                ),
            },
            edges=[
                Edge("BASE", "EVAL", "contains"),
                Edge("BASE", "PARSE_FIELD", "contains"),
                Edge("GOOD_TEST", "EVAL", "calls"),
                Edge("NOISE_TEST", "HELPER", "calls"),
            ],
        )
        result = retrieve_context(
            graph,
            "How does SourceYieldBaseline::evaluate gate parse failures, and which positive and negative tests cover it?",
            "affected_tests",
            hops=2,
        )
        self.assertIn("EVAL", result.starts)
        self.assertNotIn("HELPER", result.starts)
        self.assertNotIn("NOISE_TEST", result.nodes)
        self.assertEqual(
            [item["id"] for item in result.metadata["affected_tests"]["direct"]],
            ["GOOD_TEST"],
        )

    def test_facet_normalization_drops_meta_language_and_accepts_verified_preview(self) -> None:
        from graphgraph.retrieval.context import facet_coverage, query_facets

        facets = query_facets("verified source applications, and which tests cover every part")
        self.assertEqual(facets, (("verified source applications", ("verified", "source", "applications")),))
        graph = Graph(
            nodes={
                "PREVIEW": Node(
                    "PREVIEW", "preview_fixes", "function", "crates/locus-frontends/src/refactor.rs"
                ),
            }
        )
        coverage = facet_coverage(graph, {"PREVIEW"}, facets)
        self.assertEqual(coverage["unfulfilled"], [])
        self.assertEqual(coverage["coverage_ratio"], 1.0)

    def test_facet_normalization_keeps_single_noise_and_strips_method_verbs(self) -> None:
        from graphgraph.retrieval.context import query_facets

        facets = query_facets(
            "How does SourceYieldBaseline::evaluate assess strategy yield, noise, and parse failures?"
        )

        self.assertEqual(
            facets,
            (
                ("SourceYieldBaseline::evaluate", ("source", "yield", "baseline", "evaluate")),
                ("strategy yield", ("strategy", "yield")),
                ("noise", ("noise",)),
                ("parse failures", ("parse", "failures")),
            ),
        )

    def test_facet_anchor_prefers_owner_coherent_same_file_field(self) -> None:
        path = "crates/locus-pipeline/src/yield_benchmark.rs"
        graph = Graph(
            nodes={
                "SourceYieldBaseline__evaluate": Node(
                    "SourceYieldBaseline__evaluate", "evaluate", "method", path,
                    summary="SourceYieldBaseline::evaluate",
                ),
                "YieldBenchmarkReport__field_successful_verified_applications": Node(
                    "YieldBenchmarkReport__field_successful_verified_applications",
                    "successful_verified_applications", "field", path,
                ),
                "SourceYieldBenchmarkReport__field_successful_verified_applications": Node(
                    "SourceYieldBenchmarkReport__field_successful_verified_applications",
                    "successful_verified_applications", "field", path,
                ),
            },
        )

        result = retrieve_context(
            graph,
            "How does SourceYieldBaseline::evaluate assess verified source applications?",
            "affected_tests",
            hops=2,
        )

        self.assertIn(
            "SourceYieldBenchmarkReport__field_successful_verified_applications",
            result.starts,
        )
        self.assertNotIn(
            "YieldBenchmarkReport__field_successful_verified_applications",
            result.starts,
        )

    def test_affected_tests_preserves_compound_implementation_facets(self) -> None:
        path = "crates/locus-pipeline/src/yield.rs"
        graph = Graph(
            nodes={
                "RUN": Node("RUN", "run_initial_strategy_yield_benchmark", "function", path),
                "OLD": Node("OLD", "run_strategy_yield_benchmark", "function", path),
                "IDENTITY": Node(
                    "IDENTITY", "IdentityDiscoveryAdvisor", "struct",
                    "crates/locus-advisors/src/identity_discovery.rs",
                ),
                "SIMPLE": Node(
                    "SIMPLE", "SimplerFormDiscovery", "function",
                    "crates/locus-advisors/src/simpler_form.rs",
                ),
                "FINITE": Node(
                    "FINITE", "finite_field_equivalence", "function",
                    "crates/locus-frontends/src/cross_file.rs",
                ),
                "CONJ": Node(
                    "CONJ", "conjugate_rationalization", "function",
                    "crates/locus-advisors/src/numerical_stability.rs",
                ),
                "VERIFIED": Node("VERIFIED", "successful_verified_applications", "function", path),
                "TEST": Node(
                    "TEST",
                    "real_source_yield_benchmark",
                    "function",
                    "crates/locus-pipeline/tests/yield_benchmark.rs",
                ),
            },
            edges=[
                Edge("RUN", target, "calls")
                for target in ("IDENTITY", "SIMPLE", "FINITE", "CONJ", "VERIFIED")
            ] + [Edge("TEST", "RUN", "calls")],
        )
        result = retrieve_context(
            graph,
            (
                "How does run_initial_strategy_yield_benchmark measure identity discovery, "
                "simpler form discovery, finite field equivalence, conjugate rationalization, "
                "and successful verified applications, and which tests cover the chain?"
            ),
            "affected_tests",
            hops=2,
        )
        self.assertNotIn("OLD", result.starts)
        self.assertTrue({"RUN", "IDENTITY", "SIMPLE", "FINITE", "CONJ", "VERIFIED"} <= result.nodes)
        self.assertEqual(result.metadata["facet_coverage"]["unfulfilled"], [])
        self.assertEqual(result.metadata["facet_coverage"]["coverage_ratio"], 1.0)
        self.assertEqual(result.metadata["hybrid_intents"], ["multi_hop_path", "affected_tests"])
        self.assertEqual([item["id"] for item in result.metadata["affected_tests"]["direct"]], ["TEST"])
