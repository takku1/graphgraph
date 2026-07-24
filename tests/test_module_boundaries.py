from __future__ import annotations

import unittest
from inspect import signature


class NativeServiceBoundaryTest(unittest.TestCase):
    def test_retrieval_orchestrator_uses_explicit_stage_modules(self) -> None:
        from importlib import import_module
        from pathlib import Path

        from graphgraph.retrieval import context

        root = Path(__file__).resolve().parents[1] / "src" / "graphgraph" / "retrieval"
        context_source = (root / "context.py").read_text(encoding="utf-8")

        stages = {
            "anchors": context.anchors,
            "document_status": context.document_status,
            "expansion": context.expansion,
            "facets": context.facet_stage,
            "quality": context.quality,
            "reservations": context.reservations,
            "scoping": context.scoping,
            "search": context.search,
            "test_recommendations": context.test_recommendations,
        }
        for stage, module in stages.items():
            self.assertIs(module, import_module(f"graphgraph.retrieval.{stage}"))
            self.assertNotIn(f"from .{stage} import (", context_source)
        self.assertFalse(hasattr(context, "apply_shape_budget"))
        self.assertFalse(hasattr(context, "expand_context"))

    def test_native_facade_exports_domain_module_contracts(self) -> None:
        from graphgraph.services import native
        from graphgraph.services.freshness import (
            inspect_saved_graph_freshness,
            refresh_receipt,
            scope_freshness,
        )
        from graphgraph.services.lifecycle import (
            GraphBuildStatus,
            ensure_native_graph,
            refresh_saved_graph,
            remove_paths_validated_graph,
            scan_validated_graph,
            update_paths_validated_graph,
        )
        from graphgraph.services.native_context import render_native_context
        from graphgraph.services.project_status import build_project_status, graph_shape

        exports = {
            "GraphBuildStatus": GraphBuildStatus,
            "scan_validated_graph": scan_validated_graph,
            "update_paths_validated_graph": update_paths_validated_graph,
            "refresh_saved_graph": refresh_saved_graph,
            "remove_paths_validated_graph": remove_paths_validated_graph,
            "ensure_native_graph": ensure_native_graph,
            "inspect_saved_graph_freshness": inspect_saved_graph_freshness,
            "scope_freshness": scope_freshness,
            "refresh_receipt": refresh_receipt,
            "graph_shape": graph_shape,
            "build_project_status": build_project_status,
            "render_native_context": render_native_context,
        }
        for name, value in exports.items():
            self.assertEqual(signature(getattr(native, name)), signature(value))

    def test_cli_and_mcp_depend_on_domain_seams_not_native_monolith(self) -> None:
        from pathlib import Path

        root = Path(__file__).resolve().parents[1] / "src" / "graphgraph"
        cli = "\n".join(
            (root / "cli" / name).read_text(encoding="utf-8")
            for name in ("lifecycle.py", "retrieval.py", "diagnostics.py")
        )
        mcp = "\n".join(
            (root / "mcp" / name).read_text(encoding="utf-8") for name in ("retrieval_tools.py", "graph_management.py")
        )

        self.assertNotIn("from ..services.native import", cli)
        self.assertNotIn("from ..services.native import", mcp)
        for module in ("freshness", "lifecycle", "project_status"):
            self.assertIn(f"from ..services.{module} import", cli + mcp)

    def test_mcp_server_reexports_dedicated_dispatch(self) -> None:
        from pathlib import Path

        from graphgraph.mcp.dispatch import dispatch
        from graphgraph.mcp.server import dispatch as server_dispatch

        server_source = (Path(__file__).resolve().parents[1] / "src" / "graphgraph" / "mcp" / "server.py").read_text(
            encoding="utf-8"
        )
        self.assertIs(server_dispatch, dispatch)
        self.assertNotIn("def dispatch(", server_source)

    def test_lifecycle_contract_and_freshness_bodies_live_in_domain_modules(self) -> None:
        from pathlib import Path

        from graphgraph.services.freshness import inspect_saved_graph_freshness
        from graphgraph.services.lifecycle import GraphBuildStatus, manifest_path_for_graph

        root = Path(__file__).resolve().parents[1] / "src" / "graphgraph" / "services"
        native_source = (root / "native.py").read_text(encoding="utf-8")
        freshness_source = (root / "freshness.py").read_text(encoding="utf-8")
        lifecycle_source = (root / "lifecycle.py").read_text(encoding="utf-8")

        self.assertEqual(GraphBuildStatus.__module__, "graphgraph.services.lifecycle")
        self.assertEqual(manifest_path_for_graph.__module__, "graphgraph.services.lifecycle")
        self.assertEqual(inspect_saved_graph_freshness.__module__, "graphgraph.services.freshness")
        self.assertNotIn("class GraphBuildStatus", native_source)
        self.assertNotIn("def manifest_path_for_graph", native_source)
        self.assertNotIn("def inspect_saved_graph_freshness", native_source)
        self.assertNotIn("_delegate(", freshness_source)
        self.assertNotIn("from . import native as _native", lifecycle_source)

    def test_runtime_probe_bodies_live_outside_native_monolith(self) -> None:
        from pathlib import Path

        from graphgraph.services.runtime_probes import (
            _read_package_status,
            _resolve_cargo_workspace_members,
            _run_package_probes,
            _run_probe,
            _runtime_notes,
        )

        root = Path(__file__).resolve().parents[1] / "src" / "graphgraph" / "services"
        native_source = (root / "native.py").read_text(encoding="utf-8")
        runtime_source = (root / "runtime_probes.py").read_text(encoding="utf-8")
        functions = (
            _read_package_status,
            _resolve_cargo_workspace_members,
            _run_package_probes,
            _run_probe,
            _runtime_notes,
        )

        self.assertTrue(all(function.__module__ == "graphgraph.services.runtime_probes" for function in functions))
        for function in functions:
            self.assertNotIn(f"def {function.__name__}", native_source)
            self.assertIn(f"def {function.__name__}", runtime_source)

    def test_project_status_bodies_live_in_project_status_module(self) -> None:
        from pathlib import Path

        from graphgraph.services.project_status import (
            _absent_graph_status,
            _member_call_snapshot,
            _parse_receiver_classes,
            _symbol_extraction_status,
            build_project_status,
            graph_shape,
        )

        root = Path(__file__).resolve().parents[1] / "src" / "graphgraph" / "services"
        native_source = (root / "native.py").read_text(encoding="utf-8")
        status_source = (root / "project_status.py").read_text(encoding="utf-8")
        functions = (
            _absent_graph_status,
            _member_call_snapshot,
            _parse_receiver_classes,
            _symbol_extraction_status,
            build_project_status,
            graph_shape,
        )

        self.assertTrue(all(function.__module__ == "graphgraph.services.project_status" for function in functions))
        for function in functions:
            self.assertNotIn(f"def {function.__name__}", native_source)
            self.assertIn(f"def {function.__name__}", status_source)
        self.assertNotIn("_delegate(", status_source)
        self.assertNotIn("from . import native", status_source)

    def test_native_context_body_lives_in_native_context_module(self) -> None:
        from pathlib import Path

        from graphgraph.services.native_context import render_native_context

        root = Path(__file__).resolve().parents[1] / "src" / "graphgraph" / "services"
        native_source = (root / "native.py").read_text(encoding="utf-8")
        context_source = (root / "native_context.py").read_text(encoding="utf-8")

        self.assertEqual(render_native_context.__module__, "graphgraph.services.native_context")
        self.assertNotIn("def render_native_context", native_source)
        self.assertIn("def render_native_context", context_source)
        self.assertNotIn("from . import native", context_source)

    def test_lifecycle_implementation_bodies_live_outside_native_facade(self) -> None:
        from pathlib import Path

        from graphgraph.services.lifecycle import (
            _all_paths_outside_tree,
            _full_rescan_fallback,
            ensure_native_graph,
            refresh_saved_graph,
            remove_paths_validated_graph,
            scan_validated_graph,
            update_paths_validated_graph,
        )

        root = Path(__file__).resolve().parents[1] / "src" / "graphgraph" / "services"
        native_source = (root / "native.py").read_text(encoding="utf-8")
        lifecycle_source = (root / "lifecycle.py").read_text(encoding="utf-8")
        functions = (
            _all_paths_outside_tree,
            _full_rescan_fallback,
            ensure_native_graph,
            refresh_saved_graph,
            remove_paths_validated_graph,
            scan_validated_graph,
            update_paths_validated_graph,
        )

        self.assertTrue(all(function.__module__ == "graphgraph.services.lifecycle" for function in functions))
        for function in functions:
            self.assertNotIn(f"def {function.__name__}", native_source)
            self.assertIn(f"def {function.__name__}", lifecycle_source)
        self.assertNotIn("def _native(", lifecycle_source)


class CliDomainBoundaryTest(unittest.TestCase):
    def test_eval_command_lives_in_evaluation_domain(self) -> None:
        from pathlib import Path

        from graphgraph.cli.commands import cmd_eval as compatibility_cmd_eval
        from graphgraph.cli.evaluation import cmd_eval

        root = Path(__file__).resolve().parents[1] / "src" / "graphgraph" / "cli"
        commands_source = (root / "commands.py").read_text(encoding="utf-8")
        parser_source = (root / "parser.py").read_text(encoding="utf-8")

        self.assertIs(compatibility_cmd_eval, cmd_eval)
        self.assertEqual(cmd_eval.__module__, "graphgraph.cli.evaluation")
        self.assertNotIn("def cmd_eval", commands_source)
        self.assertIn('_lazy_cmd("evaluation", "cmd_eval")', parser_source)

    def test_graph_io_commands_live_in_graph_io_domain(self) -> None:
        from pathlib import Path

        from graphgraph.cli import commands
        from graphgraph.cli.graph_io import (
            cmd_compare,
            cmd_export,
            cmd_ingest,
            cmd_validate,
            cmd_validate_graph,
        )

        root = Path(__file__).resolve().parents[1] / "src" / "graphgraph" / "cli"
        commands_source = (root / "commands.py").read_text(encoding="utf-8")
        parser_source = (root / "parser.py").read_text(encoding="utf-8")
        functions = (cmd_compare, cmd_export, cmd_ingest, cmd_validate, cmd_validate_graph)

        self.assertTrue(all(function.__module__ == "graphgraph.cli.graph_io" for function in functions))
        for function in functions:
            self.assertIs(getattr(commands, function.__name__), function)
            self.assertNotIn(f"def {function.__name__}", commands_source)
        self.assertIn('_lazy_cmd("graph_io"', parser_source)

    def test_description_commands_live_in_descriptions_domain(self) -> None:
        from pathlib import Path

        from graphgraph.cli import commands
        from graphgraph.cli.descriptions import cmd_frontends, cmd_ontology, cmd_traversal

        root = Path(__file__).resolve().parents[1] / "src" / "graphgraph" / "cli"
        commands_source = (root / "commands.py").read_text(encoding="utf-8")
        parser_source = (root / "parser.py").read_text(encoding="utf-8")
        functions = (cmd_frontends, cmd_ontology, cmd_traversal)

        self.assertTrue(all(function.__module__ == "graphgraph.cli.descriptions" for function in functions))
        for function in functions:
            self.assertIs(getattr(commands, function.__name__), function)
            self.assertNotIn(f"def {function.__name__}", commands_source)
        self.assertIn('_lazy_cmd("descriptions"', parser_source)

    def test_cache_command_lives_in_cache_domain(self) -> None:
        from pathlib import Path

        from graphgraph.cli.cache import cmd_cache
        from graphgraph.cli.commands import cmd_cache as compatibility_cmd_cache

        root = Path(__file__).resolve().parents[1] / "src" / "graphgraph" / "cli"
        commands_source = (root / "commands.py").read_text(encoding="utf-8")
        parser_source = (root / "parser.py").read_text(encoding="utf-8")

        self.assertIs(compatibility_cmd_cache, cmd_cache)
        self.assertEqual(cmd_cache.__module__, "graphgraph.cli.cache")
        self.assertNotIn("def cmd_cache", commands_source)
        self.assertIn('_lazy_cmd("cache", "cmd_cache")', parser_source)

    def test_install_commands_are_wired_from_install_domain(self) -> None:
        from pathlib import Path

        from graphgraph.cli import commands
        from graphgraph.cli.install import cmd_artifacts, cmd_install

        root = Path(__file__).resolve().parents[1] / "src" / "graphgraph" / "cli"
        parser_source = (root / "parser.py").read_text(encoding="utf-8")

        self.assertIs(commands.cmd_artifacts, cmd_artifacts)
        self.assertIs(commands.cmd_install, cmd_install)
        self.assertIn('_lazy_cmd("install"', parser_source)

    def test_lifecycle_commands_live_in_lifecycle_domain(self) -> None:
        from pathlib import Path

        from graphgraph.cli import commands
        from graphgraph.cli.lifecycle import (
            _run_scan,
            _run_update,
            cmd_remove,
            cmd_scan,
            cmd_update,
        )

        root = Path(__file__).resolve().parents[1] / "src" / "graphgraph" / "cli"
        commands_source = (root / "commands.py").read_text(encoding="utf-8")
        parser_source = (root / "parser.py").read_text(encoding="utf-8")
        functions = (cmd_scan, _run_scan, cmd_update, _run_update, cmd_remove)

        self.assertTrue(all(function.__module__ == "graphgraph.cli.lifecycle" for function in functions))
        for function in functions:
            self.assertIs(getattr(commands, function.__name__), function)
            self.assertNotIn(f"def {function.__name__}", commands_source)
        self.assertIn('_lazy_cmd("lifecycle"', parser_source)

    def test_retrieval_commands_live_in_retrieval_domain(self) -> None:
        from pathlib import Path

        from graphgraph.cli import commands
        from graphgraph.cli.retrieval import (
            cmd_context,
            cmd_final,
            cmd_query,
            cmd_render,
            cmd_snippets,
        )

        root = Path(__file__).resolve().parents[1] / "src" / "graphgraph" / "cli"
        commands_source = (root / "commands.py").read_text(encoding="utf-8")
        parser_source = (root / "parser.py").read_text(encoding="utf-8")
        functions = (cmd_render, cmd_final, cmd_query, cmd_snippets, cmd_context)

        self.assertTrue(all(function.__module__ == "graphgraph.cli.retrieval" for function in functions))
        for function in functions:
            self.assertIs(getattr(commands, function.__name__), function)
            self.assertNotIn(f"def {function.__name__}", commands_source)
        self.assertIn('_lazy_cmd("retrieval"', parser_source)

    def test_planning_and_diagnostic_commands_own_remaining_bodies(self) -> None:
        from pathlib import Path

        from graphgraph.cli import commands
        from graphgraph.cli.diagnostics import cmd_doctor, cmd_status
        from graphgraph.cli.planning_commands import cmd_plan, cmd_profile, cmd_select

        root = Path(__file__).resolve().parents[1] / "src" / "graphgraph" / "cli"
        commands_source = (root / "commands.py").read_text(encoding="utf-8")
        parser_source = (root / "parser.py").read_text(encoding="utf-8")
        planning = (cmd_plan, cmd_profile, cmd_select)
        diagnostics = (cmd_doctor, cmd_status)

        self.assertTrue(all(function.__module__ == "graphgraph.cli.planning_commands" for function in planning))
        self.assertTrue(all(function.__module__ == "graphgraph.cli.diagnostics" for function in diagnostics))
        for function in (*planning, *diagnostics):
            self.assertIs(getattr(commands, function.__name__), function)
            self.assertNotIn(f"def {function.__name__}", commands_source)
        self.assertIn('_lazy_cmd("diagnostics"', parser_source)
        self.assertIn('_lazy_cmd("planning_commands"', parser_source)


class McpDomainBoundaryTest(unittest.TestCase):
    def test_description_tools_live_in_descriptions_domain(self) -> None:
        from pathlib import Path

        from graphgraph.mcp.descriptions import (
            DESCRIPTION_TOOL_NAMES,
            DESCRIPTION_TOOLS,
            handle_description_tool,
        )
        from graphgraph.mcp.server import TOOLS

        root = Path(__file__).resolve().parents[1] / "src" / "graphgraph" / "mcp"
        server_source = (root / "server.py").read_text(encoding="utf-8")

        self.assertEqual(
            DESCRIPTION_TOOL_NAMES,
            frozenset(
                {
                    "describe_formats",
                    "describe_ontology",
                    "describe_frontends",
                    "describe_traversal",
                }
            ),
        )
        self.assertEqual({tool["name"] for tool in DESCRIPTION_TOOLS}, DESCRIPTION_TOOL_NAMES)
        self.assertTrue(DESCRIPTION_TOOL_NAMES <= {tool["name"] for tool in TOOLS})
        self.assertEqual(handle_description_tool.__module__, "graphgraph.mcp.descriptions")
        for name in DESCRIPTION_TOOL_NAMES:
            self.assertNotIn(f'"name": "{name}"', server_source)
        self.assertIn("from .descriptions import (", server_source)

    def test_advanced_tools_live_in_platform_domain(self) -> None:
        from pathlib import Path

        from graphgraph.mcp.platform_tools import (
            PLATFORM_TOOL_NAMES,
            PLATFORM_TOOLS,
            handle_platform_tool,
        )
        from graphgraph.mcp.server import TOOLS

        root = Path(__file__).resolve().parents[1] / "src" / "graphgraph" / "mcp"
        server_source = (root / "server.py").read_text(encoding="utf-8")

        self.assertEqual(
            PLATFORM_TOOL_NAMES,
            frozenset(
                {
                    "compile_context",
                    "repair_context",
                    "graph_change",
                    "memory_context",
                    "graph_at_time",
                }
            ),
        )
        self.assertEqual({tool["name"] for tool in PLATFORM_TOOLS}, PLATFORM_TOOL_NAMES)
        self.assertTrue(PLATFORM_TOOL_NAMES <= {tool["name"] for tool in TOOLS})
        self.assertEqual(handle_platform_tool.__module__, "graphgraph.mcp.platform_tools")
        for name in PLATFORM_TOOL_NAMES:
            self.assertNotIn(f'"name": "{name}"', server_source)
        self.assertIn("from .platform_tools import (", server_source)

    def test_graph_management_tools_live_in_graph_management_domain(self) -> None:
        from pathlib import Path

        from graphgraph.mcp import server
        from graphgraph.mcp.graph_management import (
            GRAPH_MANAGEMENT_TOOL_NAMES,
            GRAPH_MANAGEMENT_TOOLS,
            handle_build_graph,
            handle_export_graph,
            handle_remove_graph_files,
            handle_update_graph_files,
        )

        root = Path(__file__).resolve().parents[1] / "src" / "graphgraph" / "mcp"
        server_source = (root / "server.py").read_text(encoding="utf-8")
        handlers = (
            handle_build_graph,
            handle_update_graph_files,
            handle_remove_graph_files,
            handle_export_graph,
        )

        self.assertEqual(
            GRAPH_MANAGEMENT_TOOL_NAMES,
            frozenset({"build_graph", "update_graph_files", "remove_graph_files", "export_graph"}),
        )
        self.assertEqual(
            {tool["name"] for tool in GRAPH_MANAGEMENT_TOOLS},
            GRAPH_MANAGEMENT_TOOL_NAMES,
        )
        for handler in handlers:
            self.assertEqual(handler.__module__, "graphgraph.mcp.graph_management")
            self.assertIs(getattr(server, handler.__name__), handler)
            self.assertNotIn(f"def {handler.__name__}", server_source)
        for name in GRAPH_MANAGEMENT_TOOL_NAMES:
            self.assertNotIn(f'"name": "{name}"', server_source)

    def test_retrieval_tools_live_outside_server_facade(self) -> None:
        from pathlib import Path

        from graphgraph.mcp import server
        from graphgraph.mcp.retrieval_tools import (
            RETRIEVAL_TOOL_NAMES,
            build_final_packet,
            build_full_graph,
            build_query_context,
            handle_project_status,
            handle_search_nodes,
            handle_select_symbols,
            handle_source_snippets,
        )

        root = Path(__file__).resolve().parents[1] / "src" / "graphgraph" / "mcp"
        server_source = (root / "server.py").read_text(encoding="utf-8")
        handlers = (
            build_final_packet,
            build_full_graph,
            build_query_context,
            handle_source_snippets,
            handle_project_status,
            handle_select_symbols,
            handle_search_nodes,
        )

        self.assertTrue({"query_context", "final_packet", "search_nodes", "select_symbols"} <= RETRIEVAL_TOOL_NAMES)
        for handler in handlers:
            self.assertEqual(handler.__module__, "graphgraph.mcp.retrieval_tools")
            self.assertIs(getattr(server, handler.__name__), handler)
            self.assertNotIn(f"def {handler.__name__}", server_source)
        self.assertNotIn("def handle_tools_call", server_source)
        self.assertLess(len(server_source.splitlines()), 100)


if __name__ == "__main__":
    unittest.main()
