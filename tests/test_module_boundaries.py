from __future__ import annotations

import unittest


class ServiceDomainBoundaryTest(unittest.TestCase):
    def test_retrieval_orchestrator_uses_explicit_stage_modules(self) -> None:
        from pathlib import Path

        from graphgraph.retrieval import context

        root = Path(__file__).resolve().parents[1] / "src" / "graphgraph" / "retrieval"
        context_source = (root / "context.py").read_text(encoding="utf-8")

        phases = ("request_feasibility", "anchor_search", "result_assembly")
        for phase in phases:
            self.assertIn(f"from .{phase} import", context_source)
        for old_stage in ("anchors", "document_status", "expansion", "facets", "quality", "reservations", "scoping", "search"):
            self.assertNotIn(f"from .{old_stage} import", context_source)
            self.assertFalse(hasattr(context, old_stage))
        self.assertFalse(hasattr(context, "apply_shape_budget"))
        self.assertFalse(hasattr(context, "expand_context"))

    def test_native_compatibility_facade_is_removed(self) -> None:
        from pathlib import Path

        services = Path(__file__).resolve().parents[1] / "src" / "graphgraph" / "services"
        self.assertFalse((services / "native.py").exists())

    def test_tree_knapsack_compatibility_shim_is_removed(self) -> None:
        from pathlib import Path

        retrieval = Path(__file__).resolve().parents[1] / "src" / "graphgraph" / "retrieval"
        self.assertFalse((retrieval / "tree_knapsack.py").exists())
        self.assertTrue((retrieval / "selection.py").exists())

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
        freshness_source = (root / "freshness.py").read_text(encoding="utf-8")
        lifecycle_source = (root / "lifecycle.py").read_text(encoding="utf-8")

        self.assertEqual(GraphBuildStatus.__module__, "graphgraph.services.lifecycle")
        self.assertEqual(manifest_path_for_graph.__module__, "graphgraph.services.lifecycle")
        self.assertEqual(inspect_saved_graph_freshness.__module__, "graphgraph.services.freshness")
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
            self.assertIn(f"def {function.__name__}", status_source)
        self.assertNotIn("_delegate(", status_source)
        self.assertNotIn("from . import native", status_source)

    def test_compiler_driver_body_lives_in_compiler_driver_module(self) -> None:
        from pathlib import Path

        from graphgraph.services.compiler_driver import CompilerDriver

        root = Path(__file__).resolve().parents[1] / "src" / "graphgraph" / "services"
        driver_source = (root / "compiler_driver.py").read_text(encoding="utf-8")

        self.assertEqual(CompilerDriver.__module__, "graphgraph.services.compiler_driver")
        self.assertIn("class CompilerDriver", driver_source)
        self.assertNotIn("from . import native", driver_source)

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
            self.assertIn(f"def {function.__name__}", lifecycle_source)
        self.assertNotIn("def _native(", lifecycle_source)


class CliDomainBoundaryTest(unittest.TestCase):
    def test_command_compatibility_facade_is_removed(self) -> None:
        from pathlib import Path

        cli = Path(__file__).resolve().parents[1] / "src" / "graphgraph" / "cli"
        self.assertFalse((cli / "commands.py").exists())

    def test_eval_command_lives_in_evaluation_domain(self) -> None:
        from pathlib import Path

        from graphgraph.cli.evaluation import cmd_eval

        root = Path(__file__).resolve().parents[1] / "src" / "graphgraph" / "cli"
        parser_source = (root / "parser.py").read_text(encoding="utf-8")

        self.assertEqual(cmd_eval.__module__, "graphgraph.cli.evaluation")
        self.assertIn('_lazy_cmd("evaluation", "cmd_eval")', parser_source)

    def test_graph_io_commands_live_in_graph_io_domain(self) -> None:
        from pathlib import Path

        from graphgraph.cli.graph_io import (
            cmd_compare,
            cmd_export,
            cmd_ingest,
            cmd_validate,
            cmd_validate_graph,
        )

        root = Path(__file__).resolve().parents[1] / "src" / "graphgraph" / "cli"
        parser_source = (root / "parser.py").read_text(encoding="utf-8")
        functions = (cmd_compare, cmd_export, cmd_ingest, cmd_validate, cmd_validate_graph)

        self.assertTrue(all(function.__module__ == "graphgraph.cli.graph_io" for function in functions))
        for function in functions:
            self.assertTrue(callable(function))
        self.assertIn('_lazy_cmd("graph_io"', parser_source)

    def test_description_commands_live_in_descriptions_domain(self) -> None:
        from pathlib import Path

        from graphgraph.cli.descriptions import cmd_frontends, cmd_ontology, cmd_traversal

        root = Path(__file__).resolve().parents[1] / "src" / "graphgraph" / "cli"
        parser_source = (root / "parser.py").read_text(encoding="utf-8")
        functions = (cmd_frontends, cmd_ontology, cmd_traversal)

        self.assertTrue(all(function.__module__ == "graphgraph.cli.descriptions" for function in functions))
        for function in functions:
            self.assertTrue(callable(function))
        self.assertIn('_lazy_cmd("descriptions"', parser_source)

    def test_cache_command_lives_in_cache_domain(self) -> None:
        from pathlib import Path

        from graphgraph.cli.cache import cmd_cache

        root = Path(__file__).resolve().parents[1] / "src" / "graphgraph" / "cli"
        parser_source = (root / "parser.py").read_text(encoding="utf-8")

        self.assertEqual(cmd_cache.__module__, "graphgraph.cli.cache")
        self.assertIn('_lazy_cmd("cache", "cmd_cache")', parser_source)

    def test_install_commands_are_wired_from_install_domain(self) -> None:
        from pathlib import Path

        from graphgraph.cli.install import cmd_artifacts, cmd_install

        root = Path(__file__).resolve().parents[1] / "src" / "graphgraph" / "cli"
        parser_source = (root / "parser.py").read_text(encoding="utf-8")

        self.assertEqual(cmd_artifacts.__module__, "graphgraph.cli.install")
        self.assertEqual(cmd_install.__module__, "graphgraph.cli.install")
        self.assertIn('_lazy_cmd("install"', parser_source)

    def test_lifecycle_commands_live_in_lifecycle_domain(self) -> None:
        from pathlib import Path

        from graphgraph.cli.lifecycle import (
            _run_scan,
            _run_update,
            cmd_remove,
            cmd_scan,
            cmd_update,
        )

        root = Path(__file__).resolve().parents[1] / "src" / "graphgraph" / "cli"
        parser_source = (root / "parser.py").read_text(encoding="utf-8")
        functions = (cmd_scan, _run_scan, cmd_update, _run_update, cmd_remove)

        self.assertTrue(all(function.__module__ == "graphgraph.cli.lifecycle" for function in functions))
        for function in functions:
            self.assertTrue(callable(function))
        self.assertIn('_lazy_cmd("lifecycle"', parser_source)

    def test_retrieval_commands_live_in_retrieval_domain(self) -> None:
        from pathlib import Path

        from graphgraph.cli.retrieval import (
            cmd_context,
            cmd_final,
            cmd_query,
            cmd_render,
            cmd_snippets,
        )

        root = Path(__file__).resolve().parents[1] / "src" / "graphgraph" / "cli"
        parser_source = (root / "parser.py").read_text(encoding="utf-8")
        functions = (cmd_render, cmd_final, cmd_query, cmd_snippets, cmd_context)

        self.assertTrue(all(function.__module__ == "graphgraph.cli.retrieval" for function in functions))
        for function in functions:
            self.assertTrue(callable(function))
        self.assertIn('_lazy_cmd("retrieval"', parser_source)

    def test_planning_and_diagnostic_commands_own_remaining_bodies(self) -> None:
        from pathlib import Path

        from graphgraph.cli.diagnostics import cmd_doctor, cmd_status
        from graphgraph.cli.planning_commands import cmd_plan, cmd_profile, cmd_select

        root = Path(__file__).resolve().parents[1] / "src" / "graphgraph" / "cli"
        parser_source = (root / "parser.py").read_text(encoding="utf-8")
        planning = (cmd_plan, cmd_profile, cmd_select)
        diagnostics = (cmd_doctor, cmd_status)

        self.assertTrue(all(function.__module__ == "graphgraph.cli.planning_commands" for function in planning))
        self.assertTrue(all(function.__module__ == "graphgraph.cli.diagnostics" for function in diagnostics))
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
            handle_query_relations,
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
            handle_query_relations,
            handle_select_symbols,
            handle_search_nodes,
        )

        self.assertTrue(
            {"query_context", "query_relations", "final_packet", "search_nodes", "select_symbols"}
            <= RETRIEVAL_TOOL_NAMES
        )
        for handler in handlers:
            self.assertEqual(handler.__module__, "graphgraph.mcp.retrieval_tools")
            self.assertIs(getattr(server, handler.__name__), handler)
            self.assertNotIn(f"def {handler.__name__}", server_source)
        self.assertNotIn("def handle_tools_call", server_source)
        self.assertLess(len(server_source.splitlines()), 100)


class ResearchBoundaryTest(unittest.TestCase):
    """`graphgraph.research` is a laboratory, never a runtime dependency.

    The tournament protocol only produces interpretable results if research
    code cannot leak into production control flow: a candidate whose formula is
    already executing in the shipped path has no measurable causal effect left
    to isolate. Tests and benchmarks are allowed consumers; production is not.
    """

    def test_production_modules_never_import_the_research_package(self) -> None:
        import ast
        from pathlib import Path

        src = Path(__file__).resolve().parents[1] / "src" / "graphgraph"
        offenders: list[str] = []
        for path in sorted(src.rglob("*.py")):
            if "research" in path.relative_to(src).parts:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    # level>0 is relative; resolve against the package path.
                    prefix = "." * node.level
                    names = [f"{prefix}{node.module or ''}"]
                else:
                    continue
                for name in names:
                    bare = name.lstrip(".")
                    if bare == "research" or bare.startswith("research."):
                        offenders.append(f"{path.relative_to(src)}:{node.lineno} -> {name}")
                    if bare == "graphgraph.research" or bare.startswith("graphgraph.research."):
                        offenders.append(f"{path.relative_to(src)}:{node.lineno} -> {name}")
        self.assertEqual(offenders, [], f"production imports of graphgraph.research: {offenders}")

    def test_the_boundary_check_can_actually_fail(self) -> None:
        # Guard against the scan silently passing because it matched nothing:
        # the research package must exist and be importable on its own.
        from pathlib import Path

        src = Path(__file__).resolve().parents[1] / "src" / "graphgraph"
        self.assertTrue((src / "research" / "__init__.py").exists())
        production = [p for p in src.rglob("*.py") if "research" not in p.relative_to(src).parts]
        self.assertGreater(len(production), 50)


if __name__ == "__main__":
    unittest.main()
