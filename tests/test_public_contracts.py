from __future__ import annotations

import argparse
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _subparser(parser: argparse.ArgumentParser, name: str) -> argparse.ArgumentParser:
    action = next(
        action
        for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    )
    return action.choices[name]


def _option_choices(parser: argparse.ArgumentParser, option: str) -> tuple[str, ...]:
    action = next(action for action in parser._actions if option in action.option_strings)
    return tuple(action.choices or ())


def _tool(name: str) -> dict[str, object]:
    from graphgraph.mcp.server import TOOLS

    return next(tool for tool in TOOLS if tool["name"] == name)


def _property(tool_name: str, property_name: str) -> dict[str, object]:
    tool = _tool(tool_name)
    schema = tool["inputSchema"]
    assert isinstance(schema, dict)
    properties = schema["properties"]
    assert isinstance(properties, dict)
    value = properties[property_name]
    assert isinstance(value, dict)
    return value


class PublicContractParityTest(unittest.TestCase):
    def test_packet_formats_match_cli_mcp_http_dispatch_and_descriptions(self) -> None:
        from graphgraph.cli.parser import build_parser
        from graphgraph.mcp.server import FORMAT_TABLE
        from graphgraph.packet_targets import TARGET_NAMES, TARGET_SPECS
        from graphgraph.platform import server

        parser = build_parser()
        for command in ("final", "query", "context"):
            self.assertEqual(
                _option_choices(_subparser(parser, command), "--packet"),
                TARGET_NAMES,
            )

        platform_compile = _subparser(_subparser(parser, "platform"), "compile")
        self.assertEqual(_option_choices(platform_compile, "--packet"), TARGET_NAMES)
        self.assertEqual(platform_compile.get_default("packet"), "gg")

        for tool_name in ("final_packet", "query_context", "compile_context"):
            packet = _property(tool_name, "packet")
            self.assertEqual(tuple(packet["enum"]), TARGET_NAMES)
        self.assertEqual(_property("compile_context", "packet")["default"], "gg")

        self.assertTrue(all(target.encoder and target.validator for target in TARGET_SPECS))
        self.assertEqual(server.TARGET_NAMES, TARGET_NAMES)
        self.assertEqual(tuple(row["format"] for row in FORMAT_TABLE), TARGET_NAMES)

    def test_query_classes_match_cli_mcp_and_domain_behavior(self) -> None:
        from graphgraph.cli.parser import build_parser
        from graphgraph.graph.traversal import POLICIES
        from graphgraph.planning.packet import _PACKET_BY_CLASS
        from graphgraph.planning.routing import QUERY_CLASS_NAMES

        parser = build_parser()
        explicit = QUERY_CLASS_NAMES
        automatic = ("auto", *QUERY_CLASS_NAMES)
        for command in ("plan", "render"):
            self.assertEqual(
                _option_choices(_subparser(parser, command), "--query-class"),
                explicit,
            )
        for command in ("final", "query", "context"):
            self.assertEqual(
                _option_choices(_subparser(parser, command), "--query-class"),
                automatic,
            )

        for tool_name in ("plan_context", "final_packet", "describe_traversal"):
            self.assertEqual(tuple(_property(tool_name, "query_class")["enum"]), explicit)
        for tool_name in ("query_context", "compile_context"):
            self.assertEqual(tuple(_property(tool_name, "query_class")["enum"]), automatic)

        implemented = set(POLICIES) | set(_PACKET_BY_CLASS) | {"doc_summary"}
        self.assertEqual(set(QUERY_CLASS_NAMES), implemented)

    def test_compiler_passes_match_cli_mcp_http_and_capabilities(self) -> None:
        from graphgraph.cli.parser import build_parser
        from graphgraph.cli.platform import platform_capabilities
        from graphgraph.platform import server
        from graphgraph.platform.compiler import COMPILER_PASS_NAMES, compiler_pass_table

        parser = build_parser()
        platform = _subparser(parser, "platform")
        compile_parser = _subparser(platform, "compile")
        transform_parser = _subparser(platform, "transform")
        self.assertEqual(_option_choices(compile_parser, "--pass"), COMPILER_PASS_NAMES)
        transform_action = next(
            action for action in transform_parser._actions if action.dest == "passes"
        )
        self.assertEqual(tuple(transform_action.choices or ()), COMPILER_PASS_NAMES)

        passes = _property("compile_context", "passes")
        items = passes["items"]
        assert isinstance(items, dict)
        self.assertEqual(tuple(items["enum"]), COMPILER_PASS_NAMES)
        self.assertEqual(server.COMPILER_PASS_NAMES, COMPILER_PASS_NAMES)
        self.assertEqual(tuple(platform_capabilities()["passes"]), COMPILER_PASS_NAMES)
        specs = platform_capabilities()["pass_specs"]
        self.assertEqual(specs, list(compiler_pass_table()))
        for spec in specs:
            self.assertTrue(spec["version"])
            self.assertTrue(spec["requires"])
            self.assertTrue(spec["produces"])
            self.assertIn(spec["cache_scope"], {"none", "compiler"})
            self.assertTrue(spec["cost"]["complexity"])

    def test_architecture_contract_tables_are_generated_from_registries(self) -> None:
        from graphgraph.packet_targets import packet_format_markdown_table
        from graphgraph.planning.routing import query_class_markdown_table

        architecture = (
            ROOT / "docs" / "architecture" / "system-architecture.md"
        ).read_text(encoding="utf-8")
        self.assertIn(packet_format_markdown_table(), architecture)
        self.assertIn(query_class_markdown_table(), architecture)


if __name__ == "__main__":
    unittest.main()
