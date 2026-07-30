from __future__ import annotations

import unittest

from graphgraph.analysis.document_authority import (
    authority_rank,
    document_authority,
    document_recency,
    parse_authority_map,
)

_README = """
# index

## Operational
- [Start Here](start-here.md)

## Architecture & reference
- [Architecture](architecture.md)

## Findings — gray-box evaluation cycles
- [Cycle 2](findings/2026-07-22-graybox-cycle2-vision.md)
- [Cycle 3](findings/2026-07-22-graybox-cycle3-crosslang.md)

## Comparisons
- [neo4j vs graphgraph](neo4j_vs_graphgraph.md)

## Research & hypotheses
- [kiminotes](kiminotes.md)

## Archive / scratch
"""


class DocumentAuthorityTest(unittest.TestCase):
    def test_section_membership_determines_tier(self) -> None:
        mapping = parse_authority_map(_README)
        self.assertEqual(mapping["start-here.md"], "current")
        self.assertEqual(mapping["architecture.md"], "current")
        self.assertEqual(mapping["findings/2026-07-22-graybox-cycle2-vision.md"], "historical")
        self.assertEqual(mapping["neo4j_vs_graphgraph.md"], "reference")
        self.assertEqual(mapping["kiminotes.md"], "research")

    def test_notes_are_scratch_regardless_of_index(self) -> None:
        self.assertEqual(document_authority("notes/initial.md"), "notes")

    def test_unindexed_doc_defaults_to_current(self) -> None:
        # Reachable-but-unclassified is at least live reference, never scratch.
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            readme = Path(tmp) / "README.md"
            readme.write_text("# empty index\n", encoding="utf-8")
            self.assertEqual(document_authority("whatever.md", docs_readme=readme), "current")

    def test_current_outranks_historical(self) -> None:
        self.assertGreater(authority_rank("current"), authority_rank("historical"))
        self.assertGreater(authority_rank("historical"), authority_rank("notes"))

    def test_recency_breaks_ties_between_dated_peers(self) -> None:
        newer = document_recency("findings/2026-07-22-graybox-cycle3-x.md")
        older = document_recency("findings/2026-07-22-graybox-cycle2-x.md")
        self.assertGreater(newer, older)
        # Undated docs carry an empty date so recency never dominates the tier.
        self.assertEqual(document_recency("architecture.md"), ("", 0))

    def test_repo_readme_classifies_real_docs(self) -> None:
        # End-to-end against the shipped docs/README.md (the single source).
        self.assertEqual(document_authority("architecture.md"), "current")
        self.assertEqual(
            document_authority("findings/2026-07-27-graybox-comprehensive.md"), "current"
        )


class AuthorityRankingWiringTest(unittest.TestCase):
    """The signal, wired into search as a tiebreaker below score."""

    def test_current_doc_wins_a_tie_against_a_historical_finding(self) -> None:
        from graphgraph.graph.core import Graph, Node
        from graphgraph.retrieval.search import search_nodes

        current = Node("cur", "spec", "markdown", "docs/architecture.md", summary="routing spec")
        finding = Node(
            "old", "spec", "markdown",
            "docs/findings/2026-07-22-graybox-cycle2-vision.md", summary="routing spec",
        )
        graph = Graph(nodes={"cur": current, "old": finding}, edges=[])
        order = [m.node.id for m in search_nodes(graph, "routing spec", limit=5)]
        self.assertLess(order.index("cur"), order.index("old"))

    def test_code_nodes_share_a_neutral_rank(self) -> None:
        # Authority must not perturb code-node ordering: they all resolve to the
        # same neutral rank, so score/path alone decide.
        from graphgraph.graph.core import Node
        from graphgraph.retrieval.search import _node_authority_rank

        a = _node_authority_rank(Node("a", "f", "function", "src/a.py"))
        b = _node_authority_rank(Node("b", "g", "function", "pkg/deep/b.py"))
        self.assertEqual(a, b)


if __name__ == "__main__":
    unittest.main()
