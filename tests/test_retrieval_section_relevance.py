from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from graphgraph import (
    Edge,
    Graph,
    Node,
)
from graphgraph.retrieval import (
    retrieve_context,
)


class QueryConditionedSectionRelevanceTest(unittest.TestCase):
    """P0 #2: document section retrieval must rank sections by query relevance,
    not by graph shape, when a document has more sections than the budget."""

    def _doc_graph(self) -> Graph:
        # One markdown document with six distinctly-themed sections, each
        # attached to the doc by a section_of edge (section -> doc), mirroring
        # the real scanner layout. Bodies carry topic terms so BM25 has signal.
        nodes = {
            "doc": Node("doc", "guide.md", "markdown", "docs/guide.md"),
        }
        sections = {
            "sec_install": ("Installation", "install the package with pip and configure the virtualenv"),
            "sec_auth": ("Authentication", "configure oauth tokens and api keys for login credentials"),
            "sec_deploy": ("Deployment", "deploy to kubernetes with docker containers and helm charts"),
            "sec_metrics": ("Metrics", "prometheus scrapes latency and throughput gauges and counters"),
            "sec_backup": ("Backups", "snapshot the database to s3 and restore from archived dumps"),
            "sec_upgrade": ("Upgrades", "migrate the schema and roll forward version pins during upgrade"),
        }
        edges = []
        for sid, (label, body) in sections.items():
            nodes[sid] = Node(sid, label, "section", "docs/guide.md", facts=(body,))
            edges.append(Edge(sid, "doc", "section_of"))
        return Graph(nodes=nodes, edges=edges)

    def _retained_sections(self, graph: Graph, query: str, budget: int) -> set[str]:
        from dataclasses import replace

        from graphgraph.planning import plan_context
        from graphgraph.planning.budgets import plan_terms
        from graphgraph.retrieval.context import expand_context

        plan = replace(plan_context("doc_summary", query, max_nodes=budget), node_budget=budget)
        nodes, _ = expand_context(graph, ("doc",), plan, query_terms=plan_terms(query))
        return {n for n in nodes if n.startswith("sec_")}

    def test_query_selects_its_own_section_within_a_tight_budget(self) -> None:
        graph = self._doc_graph()
        # Budget holds the doc + 3 of 6 sections. Each query must surface the
        # section that answers it -- proving selection tracks the query, not
        # graph shape (all sections are one hop with identical edge weight).
        deploy = self._retained_sections(graph, "deploy kubernetes docker containers", budget=4)
        self.assertIn("sec_deploy", deploy)

        backup = self._retained_sections(graph, "restore database backup from s3 snapshot", budget=4)
        self.assertIn("sec_backup", backup)

        # Different queries yield different survivors: the feature is doing work.
        self.assertNotEqual(deploy, backup)

    def test_bm25_ranks_heading_and_body_matches_above_unrelated(self) -> None:
        from graphgraph.retrieval.relevance import bm25_scores

        graph = self._doc_graph()
        sections = [graph.nodes[n] for n in graph.nodes if n.startswith("sec_")]
        scores = bm25_scores(sections, ("deploy", "kubernetes", "docker"))
        top = max(scores, key=scores.__getitem__)
        self.assertEqual(top, "sec_deploy")
        # An unrelated section scores zero against these terms.
        self.assertEqual(scores["sec_install"], 0.0)

    def test_empty_query_is_a_no_op_multiplier(self) -> None:
        from graphgraph.retrieval.relevance import relevance_multipliers, section_priority_bias

        graph = self._doc_graph()
        sections = [graph.nodes[n] for n in graph.nodes if n.startswith("sec_")]
        self.assertEqual(relevance_multipliers(sections, ()), {})
        self.assertEqual(section_priority_bias(graph, ("doc",), ()), {})

    def test_negative_query_abstains_when_requested_entity_has_no_graph_evidence(self) -> None:
        graph = Graph(
            nodes={
                "DOC": Node(
                    "DOC",
                    "scheduler implementation notes",
                    "doc_section",
                    "docs/runtime.md",
                    summary="The worker implementation is wired into the runtime.",
                ),
                "WORKER": Node("WORKER", "WorkerPool", "class", "src/runtime.py"),
                "REPORT": Node(
                    "REPORT",
                    "Negative query bug",
                    "section",
                    "docs/bugs/retrieval.md",
                    summary="Where is the nonexistent quantum banana scheduler implemented?",
                ),
            },
            edges=[Edge("DOC", "WORKER", "references"), Edge("REPORT", "DOC", "references")],
        )

        result = retrieve_context(
            graph,
            "Where is the nonexistent quantum banana scheduler implemented?",
            "negative_query",
            hops=1,
        )

        self.assertEqual(result.starts, ())
        self.assertEqual(result.nodes, set())
        self.assertTrue(result.metadata["answerability"]["abstained"])
        self.assertEqual(result.metadata["answerability"]["status"], "unanswerable")
        self.assertIn("quantum banana scheduler", result.metadata["facet_coverage"]["unfulfilled"])
        self.assertEqual(result.metadata["mention_coverage"]["coverage_ratio"], 1.0)

    def test_compiler_abstains_on_low_confidence_automatic_route(self) -> None:
        from graphgraph.platform import GraphProgram, GraphRuntime

        graph = Graph(
            nodes={
                "RECEIPT": Node(
                    "RECEIPT",
                    "receipt consistency",
                    "paragraph",
                    "docs/architecture.md",
                    summary="Facet coverage and answerability telemetry.",
                )
            }
        )

        compiled = GraphRuntime(graph).compile(
            GraphProgram(query="facet coverage answerability reconciliation")
        )

        self.assertLess(compiled.route.confidence, 0.25)
        self.assertEqual(compiled.retrieval.metadata["answerability"]["status"], "incomplete")
        self.assertTrue(compiled.retrieval.metadata["answerability"]["abstained"])
        self.assertEqual(
            compiled.retrieval.metadata["routing_recovery"]["strategy"],
            "calibrated_abstention",
        )
        self.assertEqual(compiled.receipt.semantic_validation, "pass")

    def test_semantic_validation_rejects_packet_tests_omitted_from_receipt(self) -> None:
        from graphgraph.planning import QueryRoute
        from graphgraph.retrieval import reconcile_retrieval_receipt

        graph = Graph(
            nodes={
                "TARGET": Node("TARGET", "compile_formula", "function", "src/compiler.py"),
                "TEST": Node("TEST", "test_compile_formula", "function", "tests/test_compiler.py"),
            },
            edges=[Edge("TEST", "TARGET", "calls", provenance="tree_sitter")],
        )
        result = retrieve_context(
            graph,
            "which tests cover compile_formula",
            "affected_tests",
            hops=2,
        )
        result.metadata["affected_tests"]["direct"] = []
        result.metadata["affected_tests"]["transitive"] = []

        errors = reconcile_retrieval_receipt(
            graph,
            result,
            route=QueryRoute("affected_tests", 1.0, 1.0, ("explicit query class",)),
            automatic_route=False,
        )

        self.assertTrue(errors)
        self.assertFalse(result.metadata["semantic_validation"]["ok"])
        self.assertIn("TEST", " ".join(errors))

    def test_semantic_validation_rejects_candidate_commands_as_test_evidence(self) -> None:
        from graphgraph.planning import QueryRoute
        from graphgraph.retrieval import reconcile_retrieval_receipt

        graph = Graph(
            nodes={
                "TARGET": Node("TARGET", "compile_formula", "function", "src/compiler.py"),
                "CANDIDATE": Node(
                    "CANDIDATE",
                    "test_formula_cli",
                    "function",
                    "tests/test_formula_cli.py",
                ),
            },
        )
        result = retrieve_context(
            graph,
            "which tests cover compile_formula and what command runs them",
            "affected_tests",
            hops=2,
        )
        affected = result.metadata["affected_tests"]
        affected["direct"] = []
        affected["transitive"] = []
        affected["commands"] = ["pytest -q tests/test_formula_cli.py"]
        affected["command_provenance"] = [{
            "command": "pytest -q tests/test_formula_cli.py",
            "tests": [{"id": "CANDIDATE"}],
        }]

        errors = reconcile_retrieval_receipt(
            graph,
            result,
            route=QueryRoute("affected_tests", 1.0, 1.0, ("explicit query class",)),
            automatic_route=False,
        )

        self.assertIn(
            "affected-test commands were emitted without attributed direct or "
            "transitive test evidence",
            errors,
        )
        self.assertEqual(affected["evidence_status"], "candidate_only")
        self.assertEqual(
            result.metadata["semantic_validation"]["evidence_status"],
            "candidate_only",
        )
        self.assertFalse(result.metadata["semantic_validation"]["ok"])
        self.assertEqual(result.metadata["answerability"]["status"], "incomplete")
        self.assertTrue(result.metadata["answerability"]["abstained"])

    def test_doc_summary_reserves_each_requested_heading_facet(self) -> None:
        graph = Graph(
            nodes={
                "DOC": Node("DOC", "audit.md", "markdown", "docs/audit.md"),
                "GAPS": Node(
                    "GAPS",
                    "Major Remaining Gaps",
                    "section",
                    "docs/audit.md",
                    facts=("Affected-test selection is incomplete.",),
                ),
                "ORDER": Node(
                    "ORDER",
                    "Recommended Build Order",
                    "section",
                    "docs/audit.md",
                    facts=("First enforce receipt consistency.",),
                ),
                "HEADER": Node(
                    "HEADER",
                    "GraphGraph audit",
                    "section",
                    "docs/audit.md",
                    facts=("Historical status.",),
                ),
            },
            edges=[
                Edge("GAPS", "DOC", "section_of"),
                Edge("ORDER", "DOC", "section_of"),
                Edge("HEADER", "DOC", "section_of"),
            ],
        )

        result = retrieve_context(
            graph,
            "What are the Major Remaining Gaps and Recommended Build Order in the documentation?",
            "doc_summary",
            hops=1,
            max_nodes=4,
        )

        self.assertTrue({"GAPS", "ORDER"} <= result.nodes)
        self.assertEqual(result.metadata["facet_coverage"]["unfulfilled"], [])
        self.assertEqual(result.metadata["answerability"]["status"], "answerable")

    def test_multihop_query_reserves_and_reports_every_requested_facet(self) -> None:
        graph = Graph(
            nodes={
                "REPORT": Node("REPORT", "CandidateSearchReport", "struct", "src/search.rs"),
                "PIPELINE": Node("PIPELINE", "DiscoveryPipeline", "struct", "src/discovery.rs"),
                "ENGINE": Node("ENGINE", "LocusEngine", "struct", "src/engine.rs"),
                "TIMING": Node(
                    "TIMING",
                    "YieldStageTimingsMs",
                    "struct",
                    "src/metrics.rs",
                    summary="Candidate generation timing fields.",
                ),
                "BENCH": Node(
                    "BENCH",
                    "run_formula_yield_benchmark",
                    "function",
                    "src/yield_benchmark.rs",
                    summary="Runs the deterministic formula yield corpus.",
                ),
                "EXTRACT": Node(
                    "EXTRACT",
                    "EgraphStageTimingsMs",
                    "struct",
                    "benches/extraction.rs",
                    summary="Measures e-graph extraction.",
                ),
            },
            edges=[
                Edge("PIPELINE", "REPORT", "produces"),
                Edge("REPORT", "ENGINE", "consumed_by"),
                Edge("ENGINE", "BENCH", "calls"),
                Edge("BENCH", "TIMING", "returns"),
                Edge("ENGINE", "EXTRACT", "calls"),
            ],
        )
        query = (
            "How does CandidateSearchReport flow from DiscoveryPipeline through LocusEngine "
            "into formula yield timing, and where is e-graph extraction measured?"
        )

        result = retrieve_context(graph, query, "multi_hop_path", hops=2, max_nodes=16)

        coverage = result.metadata["facet_coverage"]
        self.assertEqual(coverage["unfulfilled"], [])
        self.assertEqual(coverage["coverage_ratio"], 1.0)
        self.assertTrue({"REPORT", "PIPELINE", "ENGINE", "TIMING", "BENCH", "EXTRACT"} <= result.nodes)
        self.assertEqual(result.metadata["answerability"]["status"], "answerable")

    def test_multihop_prefers_distributed_code_evidence_over_full_document_match(self) -> None:
        from graphgraph.retrieval.context import Match, reserve_facet_matches

        graph = Graph(
            nodes={
                "DOC": Node(
                    "DOC",
                    "Formula yield timing roadmap",
                    "paragraph",
                    "docs/roadmap.md",
                ),
                "DOC2": Node(
                    "DOC2",
                    "Formula yield timing notes",
                    "paragraph",
                    "docs/notes.md",
                ),
                "BENCH": Node(
                    "BENCH",
                    "run_formula_yield_benchmark",
                    "function",
                    "src/yield_benchmark.rs",
                ),
                "TIMING": Node(
                    "TIMING",
                    "YieldStageTimingsMs",
                    "struct",
                    "src/yield_benchmark.rs",
                ),
            }
        )
        selected = (Match(graph.nodes["DOC"], 80.0, ()),)
        candidates = (
            *selected,
            Match(graph.nodes["DOC2"], 70.0, ()),
            Match(graph.nodes["BENCH"], 60.0, ()),
            Match(graph.nodes["TIMING"], 50.0, ()),
        )

        reserved = reserve_facet_matches(
            selected,
            candidates,
            (("formula yield timing", ("formula", "yield", "timing")),),
            graph=graph,
            prefer_code=True,
        )

        self.assertTrue({"BENCH", "TIMING"} <= {match.node.id for match in reserved})

    def test_multihop_docs_only_mentions_are_reported_as_structurally_incomplete(self) -> None:
        graph = Graph(
            nodes={
                "DOC": Node(
                    "DOC",
                    "CandidateSearchReport flows through DiscoveryPipeline and LocusEngine",
                    "paragraph",
                    "docs/bugs/timing.md",
                    summary="formula yield timing and e-graph extraction are measured",
                )
            }
        )
        query = (
            "How does CandidateSearchReport flow from DiscoveryPipeline through LocusEngine "
            "into formula yield timing, and where is e-graph extraction measured?"
        )

        result = retrieve_context(graph, query, "multi_hop_path", hops=2, max_nodes=16)

        self.assertEqual(result.metadata["facet_coverage"]["coverage_ratio"], 1.0)
        self.assertEqual(result.metadata["structural_facet_coverage"]["coverage_ratio"], 0.0)
        self.assertEqual(result.metadata["answerability"]["status"], "incomplete")
        self.assertIn("no code or structural evidence", result.metadata["answerability"]["reason"])

    def test_affected_tests_reports_direct_graph_evidence_even_if_packet_prunes_test(self) -> None:
        from graphgraph.retrieval.context import affected_test_recommendations

        graph = Graph(
            nodes={
                "TARGET": Node("TARGET", "compile_formula", "function", "src/compiler.py"),
                "TEST": Node("TEST", "test_compile_formula", "function", "tests/test_compiler.py"),
            },
            edges=[
                Edge(
                    "TEST",
                    "TARGET",
                    "calls",
                    confidence=0.97,
                    provenance="tree_sitter_type_resolved",
                )
            ],
        )

        affected = affected_test_recommendations(graph, ("TARGET",), {"TARGET"})

        self.assertEqual([item["id"] for item in affected["direct"]], ["TEST"])
        self.assertFalse(affected["direct"][0]["in_packet"])
        self.assertEqual(affected["direct"][0]["evidence"][0]["provenance"], "tree_sitter_type_resolved")

    def test_reverse_lookup_reports_known_callers_omitted_by_node_budget(self) -> None:
        nodes = {
            "TARGET": Node("TARGET", "normalize_rust", "function", "src/normalize.rs"),
            "FILE": Node("FILE", "normalize.rs", "file", "src/normalize.rs"),
            "SIBLING": Node("SIBLING", "normalize_cast_calls", "function", "src/normalize.rs"),
        }
        edges = [
            Edge("FILE", "TARGET", "contains"),
            Edge("FILE", "SIBLING", "contains"),
        ]
        for index in range(8):
            node_id = f"CALLER_{index}"
            nodes[node_id] = Node(node_id, f"caller_{index}", "function", f"src/caller_{index}.rs")
            edges.append(Edge(node_id, "TARGET", "calls", confidence=0.95, provenance="tree_sitter"))
        graph = Graph(nodes=nodes, edges=edges)

        result = retrieve_context(
            graph,
            "What directly calls normalize_rust?",
            "reverse_lookup",
            hops=1,
            anchor_limit=1,
            max_nodes=8,
        )

        truncation = result.metadata["truncation"]
        self.assertTrue(truncation["truncated"])
        self.assertEqual(truncation["known_direct_neighbors"], 8)
        self.assertEqual(truncation["returned_direct_neighbors"], 7)
        self.assertEqual(truncation["omitted_direct_neighbors"], 1)
        self.assertEqual(result.metadata["answerability"]["status"], "incomplete")
        self.assertTrue(result.metadata["answerability"]["abstained"])
        returned_callers = {
            edge.source
            for edge in result.edges
            if edge.type == "calls" and edge.target == "TARGET"
        }
        self.assertEqual(len(returned_callers), 7)
        self.assertNotIn("SIBLING", result.nodes)

    def test_inline_rust_test_command_uses_exact_test_label(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            crate = Path(tmp) / "locus-frontends"
            source = crate / "src" / "source" / "normalize.rs"
            source.parent.mkdir(parents=True)
            (crate / "Cargo.toml").write_text(
                '[package]\nname = "locus-frontends"\nversion = "0.1.0"\n',
                encoding="utf-8",
            )
            (crate / "src" / "lib.rs").write_text("mod source;\n", encoding="utf-8")
            source.write_text(
                "fn normalize_rust() {}\n"
                "#[cfg(test)] mod normalize_tests {\n"
                "    #[test] fn normalize_rust_rewrites_calls() { normalize_rust(); }\n"
                "}\n",
                encoding="utf-8",
            )
            graph = Graph(
                nodes={
                    "TARGET": Node(
                        "TARGET",
                        "normalize_rust",
                        "function",
                        "crates/locus-frontends/src/source/normalize.rs",
                    ),
                    "TEST": Node(
                        "TEST",
                        "normalize_rust_rewrites_calls",
                        "function",
                        "crates/locus-frontends/src/source/normalize.rs",
                        facts=("role:test", "rust_attribute:test"),
                        source=str(source),
                    ),
                },
                edges=[Edge("TEST", "TARGET", "calls", provenance="tree_sitter")],
            )

            result = retrieve_context(
                graph,
                "which tests cover normalize_rust",
                "affected_tests",
                hops=2,
            )

        self.assertEqual(
            result.metadata["affected_tests"]["commands"],
            ["cargo test -p locus-frontends normalize_rust_rewrites_calls --lib"],
        )

    def test_doc_stage_enumeration_reserves_all_numbered_stage_siblings(self) -> None:
        from graphgraph.planning import plan_context
        from graphgraph.retrieval.context import reserve_ordered_doc_siblings

        nodes = {
            "DOC": Node("DOC", "backbone-pipeline.md", "file", "docs/backbone-pipeline.md"),
        }
        edges = []
        for index in range(1, 9):
            node_id = f"STAGE_{index}"
            nodes[node_id] = Node(
                node_id,
                f"Stage {index}: operation {index}",
                "section",
                "docs/backbone-pipeline.md",
                summary=f"L{index * 10} stage {index}",
            )
            edges.append(Edge(node_id, "DOC", "section_of"))
        graph = Graph(nodes=nodes, edges=edges)
        plan = plan_context(
            "doc_summary",
            "what stages form the pipeline?",
            max_nodes=12,
        )

        selected, selected_edges = reserve_ordered_doc_siblings(
            graph,
            {"DOC", "STAGE_1"},
            [edges[0]],
            ("STAGE_1",),
            "what stages form the pipeline?",
            plan,
        )

        self.assertEqual(
            {node_id for node_id in selected if node_id.startswith("STAGE_")},
            {f"STAGE_{index}" for index in range(1, 9)},
        )
        self.assertEqual(
            {edge.source for edge in selected_edges if edge.type == "section_of"},
            {f"STAGE_{index}" for index in range(1, 9)},
        )

    def test_affected_test_candidate_cap_reports_omitted_direct_tests(self) -> None:
        nodes = {
            "EXPR": Node("EXPR", "Expr", "enum", "src/expression.rs"),
        }
        edges = []
        for index in range(14):
            node_id = f"TEST_{index:02d}"
            nodes[node_id] = Node(
                node_id,
                f"expr_case_{index:02d}",
                "function",
                f"tests/expr_case_{index:02d}.rs",
            )
            edges.append(Edge(
                node_id,
                "EXPR",
                "references",
                confidence=0.88,
                provenance="tree_sitter_type_reference",
            ))
        result = retrieve_context(
            Graph(nodes=nodes, edges=edges),
            "If Expr changes, which tests are affected?",
            "affected_tests",
            hops=2,
            anchor_limit=1,
            max_nodes=40,
        )
        from graphgraph.planning import QueryRoute
        from graphgraph.retrieval.context import reconcile_semantic_retrieval_receipt

        reconcile_semantic_retrieval_receipt(
            Graph(nodes=nodes, edges=edges),
            result,
            route=QueryRoute("affected_tests", 1.0, 1.0, ("explicit query class",)),
            automatic_route=False,
        )

        affected = result.metadata["affected_tests"]
        self.assertEqual(len(affected["direct"]), 12)
        self.assertEqual(affected["omitted_direct"], 2)
        self.assertEqual(result.metadata["answerability"]["status"], "incomplete")
        self.assertTrue(result.metadata["answerability"]["abstained"])

    def test_qualified_direct_lookup_uses_one_owner_exact_anchor_at_large_budget(self) -> None:
        graph = Graph(
            nodes={
                "TRAIT": Node(
                    "TRAIT",
                    "parse_to_ir",
                    "method",
                    "crates/core/src/pipeline.rs",
                    summary="L10 fn parse_to_ir [Pipeline::parse_to_ir]",
                ),
                "IMPL": Node(
                    "IMPL",
                    "parse_to_ir",
                    "method",
                    "crates/pipeline/src/lib.rs",
                    summary="L20 fn parse_to_ir [DiscoveryPipeline_for_LocusEngine::parse_to_ir]",
                ),
                "PARSE": Node("PARSE", "parse", "function", "crates/frontends/src/formula.rs"),
                "LIFT": Node("LIFT", "lift_expr", "function", "crates/engine/src/lift.rs"),
                "DOC": Node(
                    "DOC",
                    "binary-evidence-roadmap",
                    "paragraph",
                    "docs/roadmap/binary-evidence-roadmap.md",
                ),
                "SIBLING": Node(
                    "SIBLING",
                    "schedule_candidates",
                    "method",
                    "crates/pipeline/src/lib.rs",
                ),
            },
            edges=[
                Edge("IMPL", "PARSE", "calls", confidence=0.96, provenance="tree_sitter_path_resolved"),
                Edge("IMPL", "LIFT", "calls", confidence=0.96, provenance="tree_sitter_path_resolved"),
                Edge("IMPL", "SIBLING", "contains"),
                Edge("DOC", "IMPL", "references"),
            ],
        )

        result = retrieve_context(
            graph,
            "What does LocusEngine::parse_to_ir call?",
            "direct_lookup",
            hops=1,
            anchor_limit=12,
            max_nodes=42,
        )

        self.assertEqual(result.starts, ("IMPL",))
        self.assertEqual(result.metadata["anchor_strategy"], "exact_fast_path")
        self.assertTrue({"IMPL", "PARSE", "LIFT"} <= result.nodes)
        self.assertNotIn("TRAIT", result.nodes)
        self.assertNotIn("DOC", result.nodes)
        self.assertNotIn("SIBLING", result.nodes)

    def test_flow_summary_roots_production_symbols_above_prose_and_tests(self) -> None:
        query = (
            "How does expression parsing flow from frontends "
            "into the engine expression representation?"
        )
        graph = Graph(
            nodes={
                "AUDIT": Node(
                    "AUDIT",
                    query,
                    "paragraph",
                    "docs/audit.md",
                    facts=(query,),
                ),
                "TEST": Node(
                    "TEST",
                    "test_expression_parsing_flow_from_frontends_into_engine",
                    "function",
                    "tests/test_parse.py",
                    summary=query,
                ),
                "PARSE": Node(
                    "PARSE",
                    "parse_expr",
                    "function",
                    "frontends/parse.py",
                    summary="production frontend expression parser",
                ),
                "EXPR": Node("EXPR", "Expr", "class", "engine/expr.py"),
                "LIFT": Node("LIFT", "lift", "function", "engine/expr.py"),
            },
            edges=[
                Edge("TEST", "PARSE", "calls"),
                Edge("PARSE", "EXPR", "calls"),
                Edge("PARSE", "LIFT", "calls"),
            ],
        )

        result = retrieve_context(
            graph,
            query,
            "subsystem_summary",
            hops=1,
            max_nodes=40,
        )

        self.assertEqual(result.starts[0], "PARSE")
        self.assertNotIn("AUDIT", result.starts)
        self.assertNotIn("TEST", result.starts)
        self.assertTrue({"PARSE", "EXPR", "LIFT"} <= result.nodes)

    def test_broad_absent_capability_query_prioritizes_literal_roadmap_row(self) -> None:
        graph = Graph(
            nodes={
                "ABSENT": Node(
                    "ABSENT",
                    "Finite Automata Learning",
                    "paragraph",
                    "docs/roadmap/gap-analysis.md",
                    facts=(
                        "*   `[ ]` **Finite Automata Learning:** No bounded learner is implemented.",
                    ),
                    summary="L61",
                ),
                "GENERAL": Node(
                    "GENERAL",
                    "Implementation roadmap and likely tests",
                    "paragraph",
                    "docs/architecture/overview.md",
                    facts=(
                        "This capability roadmap describes bounded implementation areas and tests.",
                    ),
                    summary="L4",
                ),
            },
        )

        result = retrieve_context(
            graph,
            (
                "From the roadmap documentation, identify one capability that is "
                "currently marked absent, is small enough for a bounded implementation, "
                "and report the documented gap plus likely implementation area and tests."
            ),
            "doc_summary",
            hops=1,
        )

        self.assertEqual(result.starts[0], "ABSENT")
        self.assertIn("literal_document_status", result.matches[0].reasons)
        self.assertIn("[ ]", result.matches[0].node.facts[0])

    def test_absent_capability_query_rejects_checkbox_legend_as_evidence(self) -> None:
        graph = Graph(
            nodes={
                "LEGEND": Node(
                    "LEGEND",
                    "`[ ]` absent or not reliable enough to claim",
                    "paragraph",
                    "docs/roadmap/gap-analysis.md",
                    facts=("- `[ ]` absent or not reliable enough to claim.",),
                ),
                "PARTIAL": Node(
                    "PARTIAL",
                    "Finite VC dimension",
                    "paragraph",
                    "docs/roadmap/gap-analysis.md",
                    facts=(
                        "* `[~]` **Finite VC dimension:** A bounded fragment is implemented.",
                    ),
                ),
            },
        )

        result = retrieve_context(
            graph,
            "From the roadmap, identify one capability currently marked absent.",
            "doc_summary",
            hops=1,
        )

        status = result.metadata["document_status_evidence"]
        self.assertEqual(status["capability_rows"], 0)
        self.assertIn("no literal absent capability rows", status["warning"])
        self.assertTrue(result.metadata["answerability"]["abstained"])
        self.assertEqual(
            result.metadata["answerability"]["reason"],
            status["warning"],
        )
        self.assertEqual(result.matches, ())
        self.assertEqual(result.nodes, set())
        self.assertTrue(status["packet_constrained"])
        self.assertEqual(status["packet_status_rows"], [])
        self.assertEqual(status["conflicting_status_rows"], [])

    def test_absent_capability_query_projects_packet_to_matching_table_rows(self) -> None:
        path = "docs/roadmap/coverage-matrix.md"
        graph = Graph(
            nodes={
                "FILE": Node("FILE", "coverage-matrix.md", "markdown", path),
                "SECTION": Node("SECTION", "Capability coverage", "section", path),
                "LEGEND": Node(
                    "LEGEND",
                    "`[ ]` absent or not reliable enough to claim",
                    "paragraph",
                    path,
                    facts=("- `[ ]` absent or not reliable enough to claim.",),
                    parent="SECTION",
                ),
                "PARTIAL": Node(
                    "PARTIAL",
                    "Finite VC dimension",
                    "paragraph",
                    path,
                    facts=("| Finite VC dimension | `[~]` | Bounded classes only. |",),
                    parent="SECTION",
                ),
                "ABSENT": Node(
                    "ABSENT",
                    "Symbolic PAC learning",
                    "paragraph",
                    path,
                    facts=("| Symbolic PAC learning | `[ ]` | Not implemented. |",),
                    parent="SECTION",
                ),
            },
            edges=[
                Edge("SECTION", "FILE", "section_of"),
                Edge("SECTION", "LEGEND", "contains"),
                Edge("SECTION", "PARTIAL", "contains"),
                Edge("SECTION", "ABSENT", "contains"),
            ],
        )

        result = retrieve_context(
            graph,
            "From the roadmap, identify one capability currently marked absent.",
            "doc_summary",
            hops=1,
            scopes=(path,),
        )

        self.assertEqual(result.starts, ("ABSENT",))
        self.assertEqual(result.matches[0].node.id, "ABSENT")
        self.assertEqual(result.nodes, {"FILE", "SECTION", "ABSENT"})
        self.assertNotIn("LEGEND", result.nodes)
        self.assertNotIn("PARTIAL", result.nodes)
        status = result.metadata["document_status_evidence"]
        self.assertEqual(status["evidence"], ["ABSENT"])
        self.assertEqual(status["packet_status_rows"], ["ABSENT"])
        self.assertEqual(status["conflicting_status_rows"], [])
        self.assertTrue(status["packet_constrained"])
        self.assertFalse(result.metadata["answerability"]["abstained"])
        self.assertEqual(result.metadata["answerability"]["status"], "answerable")

    def test_absent_status_evidence_fulfills_redundant_marker_facet(self) -> None:
        path = "docs/roadmap/execution-backlog.md"
        graph = Graph(nodes={
            "ITEM": Node(
                "ITEM",
                "Reconcile the coverage survey",
                "paragraph",
                path,
                facts=("- `[ ]` Reconcile the coverage survey.",),
            ),
        })

        result = retrieve_context(
            graph,
            (
                "From this roadmap, identify one item currently marked absent "
                "and return only that status class."
            ),
            "doc_summary",
            hops=1,
            scopes=(path,),
        )

        self.assertEqual(result.starts, ("ITEM",))
        self.assertEqual(result.metadata["answerability"]["status"], "answerable")
        self.assertFalse(result.metadata["answerability"]["abstained"])
        self.assertNotIn("facet_coverage", result.metadata)

    def test_query_facets_compile_contract_and_covered_cases_canonically(self) -> None:
        from graphgraph.retrieval.context import facet_coverage, query_facets

        contract_facets = query_facets(
            "What bounded input contract does it have?"
        )
        case_facets = query_facets(
            "Which tests exercise finite_vc_dimension and shatters, "
            "and what cases do they cover?"
        )
        self.assertIn(
            ("bounded input contract", ("bounded", "input", "contract")),
            contract_facets,
        )
        self.assertNotIn("bounded input contract have", {
            label for label, _terms in contract_facets
        })
        self.assertIn(("covered cases", ("covered", "cases")), case_facets)
        self.assertNotIn("cases they", {label for label, _terms in case_facets})

        graph = Graph(
            nodes={
                "ROW": Node(
                    "ROW",
                    "Statistical Learning Theory",
                    "paragraph",
                    "docs/roadmap/gap-analysis.md",
                    facts=("Exact finite classes are supported up to 20 domain points.",),
                )
            },
        )
        coverage = facet_coverage(
            graph,
            {"ROW"},
            (("bounded input contract", ("bounded", "input", "contract")),),
        )
        self.assertEqual(coverage["unfulfilled"], [])

    def test_topic_local_roadmap_row_cannot_borrow_a_sibling_bound(self) -> None:
        path = "docs/roadmap/gap-analysis.md"
        graph = Graph(nodes={
            "GAME": Node(
                "GAME",
                "Game Theory",
                "paragraph",
                path,
                facts=(
                    "Game Theory computes an exact fully mixed Nash equilibrium "
                    "for a nondegenerate two-player 2×2 general-sum game. "
                    "General m×n equilibria and degenerate enumeration remain absent.",
                ),
            ),
            "LEARNING": Node(
                "LEARNING",
                "Statistical Learning Theory",
                "paragraph",
                path,
                facts=("Exact finite classes are supported up to 20 domain points.",),
            ),
        })

        result = retrieve_context(
            graph,
            (
                "From the Game Theory roadmap row, what is the bounded input "
                "contract for mixed_nash_2x2 and what remains unsupported?"
            ),
            "doc_summary",
            hops=1,
            scopes=(path,),
        )

        self.assertEqual(result.starts, ("GAME",))
        self.assertNotIn("LEARNING", result.nodes)
        self.assertEqual(result.metadata["facet_coverage"]["unfulfilled"], [])
        self.assertEqual(result.metadata["answerability"]["status"], "answerable")

    def test_blast_radius_binds_roadmap_paragraph_to_qualified_api(self) -> None:
        code_path = "crates/locus-engine/src/game_theory.rs"
        doc_path = "docs/roadmap/gap-analysis.md"
        graph = Graph(
            nodes={
                "API": Node(
                    "API",
                    "mixed_nash_2x2",
                    "function",
                    code_path,
                    summary="pub fn mixed_nash_2x2",
                ),
                "VERIFY": Node("VERIFY", "verify_mixed_nash_2x2", "function", code_path),
                "RESULT": Node("RESULT", "MixedNash2x2", "struct", code_path),
                "TEST": Node(
                    "TEST",
                    "general_sum_matching_pennies_is_uniform",
                    "function",
                    code_path,
                    facts=("role:test", "rust_attribute:test"),
                ),
                "GAME_DOC": Node(
                    "GAME_DOC",
                    "Game Theory",
                    "paragraph",
                    doc_path,
                    facts=(
                        "Game Theory computes the exact mixed Nash equilibrium "
                        "of a two-player 2×2 general-sum game.",
                    ),
                ),
                "AUDIT_DOC": Node(
                    "AUDIT_DOC",
                    "Tracking audit docs",
                    "paragraph",
                    "docs/roadmap/coverage-matrix.md",
                    facts=("Tracking docs include the gap analysis and this roadmap.",),
                ),
            },
            edges=[
                Edge("API", "VERIFY", "calls"),
                Edge("API", "RESULT", "returns"),
                Edge("TEST", "API", "calls"),
            ],
        )

        result = retrieve_context(
            graph,
            (
                "What is the blast radius of changing game_theory::mixed_nash_2x2, "
                "including callers, export, tests, and the roadmap paragraph that "
                "documents this API?"
            ),
            "blast_radius",
            hops=2,
            max_nodes=16,
        )

        self.assertIn("GAME_DOC", result.starts)
        self.assertIn("GAME_DOC", result.nodes)
        self.assertNotIn("AUDIT_DOC", result.starts)
        self.assertEqual(result.metadata["facet_coverage"]["unfulfilled"], [])
        self.assertEqual(result.metadata["answerability"]["status"], "answerable")

    def test_compound_game_theory_abstention_prefers_api_connected_test(self) -> None:
        code_path = "crates/locus-engine/src/game_theory.rs"
        doc_path = "docs/roadmap/gap-analysis.md"
        graph = Graph(
            nodes={
                "API": Node("API", "mixed_nash_2x2", "function", code_path),
                "VERIFY": Node("VERIFY", "verify_mixed_nash_2x2", "function", code_path),
                "RESULT": Node("RESULT", "MixedNash2x2", "struct", code_path),
                "ZERO_SUM": Node("ZERO_SUM", "mixed_zero_sum_2x2", "function", code_path),
                "RIGHT_TEST": Node(
                    "RIGHT_TEST",
                    "dominant_or_degenerate_games_have_no_fully_mixed_solution",
                    "function",
                    code_path,
                    facts=("role:test", "rust_attribute:test"),
                ),
                "WRONG_TEST": Node(
                    "WRONG_TEST",
                    "a_saddle_point_game_has_no_mixed_solution",
                    "function",
                    code_path,
                    facts=("role:test", "rust_attribute:test"),
                ),
                "GAME_DOC": Node(
                    "GAME_DOC",
                    "Game Theory",
                    "paragraph",
                    doc_path,
                    facts=(
                        "Game Theory computes the exact fully mixed Nash equilibrium "
                        "of a nondegenerate two-player 2×2 general-sum game.",
                    ),
                ),
            },
            edges=[
                Edge("API", "VERIFY", "calls"),
                Edge("API", "RESULT", "returns"),
                Edge("RIGHT_TEST", "API", "calls"),
                Edge("WRONG_TEST", "ZERO_SUM", "calls"),
            ],
        )

        result = retrieve_context(
            graph,
            (
                "From the Game Theory roadmap row, explain the new general-sum "
                "2x2 mixed Nash API, its result, self-verification, abstention "
                "cases, and tests."
            ),
            "doc_summary",
            hops=1,
            scopes=(doc_path, code_path),
        )

        self.assertIn("API", result.starts)
        self.assertIn("RIGHT_TEST", result.starts)
        self.assertNotIn("WRONG_TEST", result.starts)
        self.assertEqual(result.metadata["facet_coverage"]["unfulfilled"], [])
        self.assertEqual(
            [item["id"] for item in result.metadata["affected_tests"]["direct"]],
            ["RIGHT_TEST"],
        )
        self.assertEqual(
            result.metadata["hybrid_intents"],
            ["doc_summary", "affected_tests"],
        )

    def test_affected_command_contract_covers_every_direct_test(self) -> None:
        from graphgraph.planning import QueryRoute
        from graphgraph.retrieval import reconcile_retrieval_receipt

        with tempfile.TemporaryDirectory() as tmp:
            crate = Path(tmp) / "locus-engine"
            source = crate / "src" / "game_theory.rs"
            source.parent.mkdir(parents=True)
            (crate / "Cargo.toml").write_text(
                '[package]\nname = "locus-engine"\nversion = "0.1.0"\n',
                encoding="utf-8",
            )
            (crate / "src" / "lib.rs").write_text(
                "mod game_theory;\n",
                encoding="utf-8",
            )
            source.write_text(
                "pub fn mixed_nash_2x2() {}\n"
                "#[cfg(test)] mod tests {\n"
                "  #[test] fn battle_of_the_sexes() { mixed_nash_2x2(); }\n"
                "  #[test] fn degenerate_abstains() { mixed_nash_2x2(); }\n"
                "}\n",
                encoding="utf-8",
            )
            code_path = "crates/locus-engine/src/game_theory.rs"
            graph = Graph(
                nodes={
                    "API": Node(
                        "API",
                        "mixed_nash_2x2",
                        "function",
                        code_path,
                        source=str(source),
                    ),
                    "TEST_A": Node(
                        "TEST_A",
                        "battle_of_the_sexes",
                        "function",
                        code_path,
                        facts=("role:test", "rust_attribute:test"),
                        source=str(source),
                    ),
                    "TEST_B": Node(
                        "TEST_B",
                        "degenerate_abstains",
                        "function",
                        code_path,
                        facts=("role:test", "rust_attribute:test"),
                        source=str(source),
                    ),
                    "DOC_NOISE": Node(
                        "DOC_NOISE",
                        "One run",
                        "paragraph",
                        "docs/roadmap/bridge-plan.md",
                    ),
                },
                edges=[
                    Edge("TEST_A", "API", "calls"),
                    Edge("TEST_B", "API", "calls"),
                ],
            )
            result = retrieve_context(
                graph,
                (
                    "Which tests directly exercise mixed_nash_2x2, and what is "
                    "the smallest exact Cargo command that runs every one?"
                ),
                "affected_tests",
                hops=2,
            )
            errors = reconcile_retrieval_receipt(
                graph,
                result,
                route=QueryRoute("affected_tests", 1.0, 1.0, ("explicit query class",)),
                automatic_route=False,
            )

        self.assertEqual(errors, ())
        self.assertEqual(
            result.metadata["affected_tests"]["commands"],
            ["cargo test -p locus-engine game_theory::tests --lib"],
        )
        self.assertEqual(
            result.metadata["affected_tests"]["command_selection"]["uncovered_direct_tests"],
            [],
        )
        self.assertNotIn("DOC_NOISE", result.starts)
        self.assertEqual(result.metadata["facet_coverage"]["unfulfilled"], [])
        self.assertEqual(result.metadata["answerability"]["status"], "answerable")

    def test_blast_radius_preserves_explicit_changed_markdown_root(self) -> None:
        graph = Graph(
            nodes={
                "CODE": Node(
                    "CODE",
                    "finite_vc_dimension",
                    "function",
                    "crates/locus-engine/src/learning_theory.rs",
                ),
                "LIB": Node(
                    "LIB",
                    "lib.rs",
                    "rust",
                    "crates/locus-engine/src/lib.rs",
                ),
                "DOC": Node(
                    "DOC",
                    "gap-analysis.md",
                    "markdown",
                    "docs/roadmap/gap-analysis.md",
                ),
                "UNRELATED": Node(
                    "UNRELATED",
                    "Herbie FFI",
                    "paragraph",
                    "docs/integrations/herbie.md",
                    facts=("Foreign function notes.",),
                ),
            },
            edges=[Edge("LIB", "CODE", "contains")],
        )

        result = retrieve_context(
            graph,
            "What code, tests, and documentation are affected?",
            "blast_radius",
            hops=2,
            anchor_paths=(
                "crates/locus-engine/src/learning_theory.rs",
                "crates/locus-engine/src/lib.rs",
                "docs/roadmap/gap-analysis.md",
            ),
        )

        self.assertIn("DOC", result.starts)
        self.assertIn("DOC", result.nodes)
        self.assertNotIn("UNRELATED", result.starts)
        doc_receipt = next(
            item
            for item in result.metadata["anchor_paths"]
            if item["path"] == "docs/roadmap/gap-analysis.md"
        )
        self.assertEqual(doc_receipt["role"], "primary_root")
        self.assertEqual(doc_receipt["anchors"], ["DOC"])

    def test_affected_anchor_query_compiles_exact_symbols_without_runs_noise(self) -> None:
        from graphgraph.retrieval.context import structural_anchor_query

        compiled = structural_anchor_query(
            (
                "Which tests directly exercise finite_vc_dimension and shatters, "
                "what cases do they cover, and what exact Cargo command runs them?"
            ),
            "affected_tests",
        )

        self.assertEqual(compiled, "finite_vc_dimension shatters")
        self.assertNotIn("runs", compiled)

    def test_affected_tests_broadens_inline_command_to_cover_all_direct_roots(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            crate = Path(tmp) / "locus-engine"
            source = crate / "src" / "learning_theory.rs"
            source.parent.mkdir(parents=True)
            (crate / "Cargo.toml").write_text(
                '[package]\nname = "locus-engine"\nversion = "0.1.0"\n',
                encoding="utf-8",
            )
            (crate / "src" / "lib.rs").write_text(
                "mod learning_theory;\n",
                encoding="utf-8",
            )
            source.write_text(
                "fn finite_vc_dimension() {}\n"
                "fn shatters() {}\n"
                "#[cfg(test)] mod tests {\n"
                "  #[test] fn complete_class() { finite_vc_dimension(); }\n"
                "  #[test] fn subset_contract() { shatters(); }\n"
                "}\n",
                encoding="utf-8",
            )
            graph = Graph(
                nodes={
                    "VC": Node(
                        "VC",
                        "finite_vc_dimension",
                        "function",
                        "crates/locus-engine/src/learning_theory.rs",
                    ),
                    "SHATTERS": Node(
                        "SHATTERS",
                        "shatters",
                        "function",
                        "crates/locus-engine/src/learning_theory.rs",
                    ),
                    "SHATTERED_POINTS": Node(
                        "SHATTERED_POINTS",
                        "shattered_points",
                        "field",
                        "crates/locus-engine/src/learning_theory.rs",
                    ),
                    "TEST_VC": Node(
                        "TEST_VC",
                        "complete_class",
                        "function",
                        "crates/locus-engine/src/learning_theory.rs",
                        facts=("role:test", "rust_attribute:test"),
                        source=str(source),
                    ),
                    "TEST_SUBSET": Node(
                        "TEST_SUBSET",
                        "subset_contract",
                        "function",
                        "crates/locus-engine/src/learning_theory.rs",
                        facts=("role:test", "rust_attribute:test"),
                        source=str(source),
                    ),
                },
                edges=[
                    Edge("TEST_VC", "VC", "calls"),
                    # Deliberately omit the real shatters edge to model partial
                    # call extraction. The bounded source check below must
                    # still prove that the module command exercises it.
                    Edge("TEST_SUBSET", "VC", "calls"),
                ],
            )
            result = retrieve_context(
                graph,
                (
                    "Which tests directly exercise finite_vc_dimension and shatters, "
                    "what cases do they cover, and what exact Cargo command runs them?"
                ),
                "affected_tests",
                hops=2,
            )
            path_result = retrieve_context(
                graph,
                (
                    "Which tests directly exercise finite_vc_dimension and shatters, "
                    "what cases do they cover, and what exact Cargo command runs them?"
                ),
                "affected_tests",
                hops=2,
                anchor_paths=("crates/locus-engine/src/learning_theory.rs",),
            )

        affected = result.metadata["affected_tests"]
        self.assertEqual(result.starts, ("VC", "SHATTERS"))
        self.assertEqual(path_result.starts, ("VC", "SHATTERS"))
        self.assertEqual(
            affected["commands"],
            ["cargo test -p locus-engine learning_theory::tests --lib"],
        )
        self.assertEqual(affected["command_selection"]["uncovered_roots"], [])
        self.assertEqual(
            affected["command_selection"]["structurally_uncovered_roots"],
            ["SHATTERS"],
        )
        self.assertEqual(
            affected["command_selection"]["execution_scope_covered_roots"],
            ["SHATTERS"],
        )
        self.assertEqual(
            affected["command_provenance"][0]["selection_scope"],
            "inline_test_module",
        )

    def test_changed_path_module_command_supersedes_redundant_exact_filter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            crate = Path(tmp) / "locus-engine"
            source = crate / "src" / "learning_theory.rs"
            source.parent.mkdir(parents=True)
            (crate / "Cargo.toml").write_text(
                '[package]\nname = "locus-engine"\nversion = "0.1.0"\n',
                encoding="utf-8",
            )
            (crate / "src" / "lib.rs").write_text("mod learning_theory;\n", encoding="utf-8")
            source.write_text(
                "fn finite_vc_dimension() {}\n"
                "fn shatters() {}\n"
                "#[cfg(test)] mod tests {\n"
                "  #[test] fn both_contracts() { finite_vc_dimension(); shatters(); }\n"
                "  #[test] fn malformed_contract() { finite_vc_dimension(); }\n"
                "}\n",
                encoding="utf-8",
            )
            graph = Graph(
                nodes={
                    "VC": Node(
                        "VC",
                        "finite_vc_dimension",
                        "function",
                        "crates/locus-engine/src/learning_theory.rs",
                    ),
                    "SHATTERS": Node(
                        "SHATTERS",
                        "shatters",
                        "function",
                        "crates/locus-engine/src/learning_theory.rs",
                    ),
                    "TEST": Node(
                        "TEST",
                        "both_contracts",
                        "function",
                        "crates/locus-engine/src/learning_theory.rs",
                        facts=("role:test", "rust_attribute:test"),
                        source=str(source),
                    ),
                    "TEST_MALFORMED": Node(
                        "TEST_MALFORMED",
                        "malformed_contract",
                        "function",
                        "crates/locus-engine/src/learning_theory.rs",
                        facts=("role:test", "rust_attribute:test"),
                        source=str(source),
                    ),
                },
                edges=[
                    Edge("TEST", "VC", "calls"),
                    Edge("TEST", "SHATTERS", "calls"),
                    Edge("TEST_MALFORMED", "VC", "calls"),
                ],
            )
            result = retrieve_context(
                graph,
                "Which tests cover finite_vc_dimension and shatters?",
                "affected_tests",
                hops=2,
                anchor_paths=("crates/locus-engine/src/learning_theory.rs",),
            )

        affected = result.metadata["affected_tests"]
        self.assertEqual(
            affected["commands"],
            ["cargo test -p locus-engine learning_theory::tests --lib"],
        )
        self.assertEqual(
            affected["command_selection"]["superseded_commands"],
            ["cargo test -p locus-engine both_contracts --lib"],
        )

    def test_zero_concept_links_are_declared_unavailable_with_threshold(self) -> None:
        graph = Graph(
            nodes={"A": Node("A", "Architecture", "paragraph", "docs/architecture.md", facts=("Architecture.",))},
            metadata={
                "source_concepts_eligible": "100",
                "source_concepts_linked_nodes": "0",
                "source_concepts_scope": "full_graph_snapshot",
            },
        )

        result = retrieve_context(
            graph,
            "Summarize the architecture documentation",
            "doc_summary",
            hops=1,
        )

        semantic = result.metadata["quality"]["semantic_support"]
        self.assertEqual(semantic["status"], "unavailable")
        self.assertFalse(semantic["supported"])
        self.assertEqual(semantic["minimum_supported_coverage_ratio"], 0.2)
        self.assertIn("no verified registry-evidence links", semantic["diagnostic_reason"])
        self.assertEqual(semantic["retrieval_mode"], "lexical_document_fallback")
