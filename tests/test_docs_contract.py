from __future__ import annotations

import re
import unittest
from pathlib import Path
from urllib.parse import unquote, urlparse

from graphgraph.cli.parser import build_parser

ROOT = Path(__file__).resolve().parents[1]
MARKDOWN_LINK = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")


class DocumentationContractTest(unittest.TestCase):
    def test_every_doc_has_an_inbound_index_link(self) -> None:
        # T09: docs/README.md is the authoritative map. Every operational and
        # reference document must be reachable from it (directly or through a
        # linked index like findings/), so nothing rots unlinked. Scratch under
        # docs/notes/ is the one explicit archival exception.
        docs_root = ROOT / "docs"
        readme = (docs_root / "README.md").resolve()
        reachable: set[Path] = set()
        frontier = [readme]
        while frontier:
            current = frontier.pop()
            if current in reachable or not current.exists():
                continue
            reachable.add(current)
            for raw in MARKDOWN_LINK.findall(current.read_text(encoding="utf-8", errors="replace")):
                target = unquote(urlparse(raw).path).split("#")[0]
                if not target or not target.endswith(".md"):
                    continue
                frontier.append((current.parent / target).resolve())

        archived = {"notes"}
        orphans = [
            doc.relative_to(docs_root).as_posix()
            for doc in sorted(docs_root.rglob("*.md"))
            if doc.name != "README.md"
            and doc.relative_to(docs_root).parts[0] not in archived
            and doc.resolve() not in reachable
        ]
        self.assertEqual(
            orphans, [], f"docs not reachable from docs/README.md: {orphans}"
        )

    def test_local_markdown_links_resolve_without_file_uris(self) -> None:
        failures: list[str] = []
        files = [ROOT / "README.md", *sorted((ROOT / "docs").rglob("*.md"))]

        for document in files:
            text = document.read_text(encoding="utf-8", errors="replace")
            for match in MARKDOWN_LINK.finditer(text):
                raw_target = match.group(1).strip().strip("<>")
                parsed = urlparse(raw_target)
                if parsed.scheme in {"http", "https", "mailto"} or raw_target.startswith("#"):
                    continue
                if parsed.scheme:
                    failures.append(
                        f"{document.relative_to(ROOT)} uses non-portable URI {raw_target!r}"
                    )
                    continue
                relative = unquote(raw_target.split("#", 1)[0])
                if not relative:
                    continue
                target = (document.parent / relative).resolve()
                if not target.exists():
                    failures.append(
                        f"{document.relative_to(ROOT)} links missing path {raw_target!r}"
                    )

        self.assertEqual(failures, [], "\n".join(failures))

    def test_start_here_uses_executable_validation_and_snippet_commands(self) -> None:
        text = (ROOT / "docs" / "start-here.md").read_text(encoding="utf-8")

        self.assertIn(
            "graphgraph validate-graph --graph .graphgraph/graph.gg",
            text,
        )
        self.assertNotIn("graphgraph validate --graph", text)
        self.assertIn("graphgraph snippets --starts", text)

        parser = build_parser()
        for argv in (
            ["doctor"],
            ["scan", "--depth", "symbols", "--docs"],
            ["context", "how does X work", "--query-class", "subsystem_summary"],
            ["validate-graph", "--graph", ".graphgraph/graph.gg"],
            ["query", "where is X defined", "--show-stats"],
            ["snippets", "--starts", "node_id"],
            [
                "context",
                "what changed?",
                "--changed-files",
                "src/example.py",
                "--json",
                "--validate",
            ],
        ):
            with self.subTest(argv=argv):
                parser.parse_args(argv)

    def test_architecture_uses_current_public_packet_names(self) -> None:
        text = (ROOT / "docs" / "architecture.md").read_text(encoding="utf-8")

        self.assertIn("| `gg` |", text)
        self.assertIn("| `gg_hybrid` |", text)
        self.assertNotIn("1hop gg_max", text)
        self.assertNotIn("2hop gg_max", text)

    def test_skill_avoids_stale_project_specific_measurements_and_language_claims(self) -> None:
        text = (
            ROOT / "src" / "graphgraph" / "assets" / "graphgraph_skill.md"
        ).read_text(encoding="utf-8")

        self.assertNotRegex(text, r"Current member-call resolution is ~\d")
        self.assertIn("Run `graphgraph status`", text)
        self.assertIn("| C#/Java |", text)
        self.assertNotIn("| Others | none -- symbols are extracted", text)


if __name__ == "__main__":
    unittest.main()
