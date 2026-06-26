from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from graphgraph import Edge, Graph, Node, Policy, Query, choose_packet, select_policies, validate_packet, scan_directory
from graphgraph.ast_scanner import extract_symbols
from graphgraph.io import load_graph, load_policies, save_graph, load_gg, save_gg, load_csv_edges, load_any
from graphgraph.mcp_server import dispatch
from graphgraph.packets import render_lowlevel, render_semantic_arrow, render_gg_max, render_sql, render_svo
from graphgraph.policies import render_policy_packet


def sample_graph() -> Graph:
    return Graph(
        nodes={
            "N1": Node("N1", "AuthService", "service", "server/auth.py"),
            "N2": Node("N2", "TokenStore", "data", "server/tokens.py"),
            "N3": Node("N3", "AuditLog", "data", "server/audit.py"),
        },
        edges=[
            Edge("N1", "N2", "reads", 0.9),
            Edge("N2", "N3", "writes", 0.8),
        ],
    )


class GraphGraphCoreTest(unittest.TestCase):
    def test_expand_two_hops(self) -> None:
        graph = sample_graph()
        nodes, edges = graph.expand(["N1"], hops=2)
        self.assertEqual(nodes, {"N1", "N2", "N3"})
        self.assertEqual([(edge.source, edge.target, edge.type) for edge in edges], [("N1", "N2", "reads"), ("N2", "N3", "writes")])

    def test_expand_with_max_nodes_budget(self) -> None:
        graph = sample_graph()
        # N1 expands to N2 (hop 1) and N3 (hop 2). With max_nodes=2, it should truncate N3 and its edge.
        nodes, edges = graph.expand(["N1"], hops=2, max_nodes=2)
        self.assertEqual(nodes, {"N1", "N2"})
        self.assertEqual([(edge.source, edge.target, edge.type) for edge in edges], [("N1", "N2", "reads")])

    def test_render_and_validate_lowlevel(self) -> None:
        graph = sample_graph()
        nodes, edges = graph.expand(["N1"], hops=1)
        packet = render_lowlevel(graph, nodes, edges)
        result = validate_packet(packet)
        self.assertTrue(result.ok, result.errors)
        self.assertEqual(result.format, "lowlevel")
        self.assertEqual(result.node_count, 2)
        self.assertEqual(result.edge_count, 1)

    def test_render_and_validate_sql(self) -> None:
        graph = sample_graph()
        nodes, edges = graph.expand(["N1"], hops=1)
        packet = render_sql(graph, nodes, edges)
        result = validate_packet(packet)
        self.assertTrue(result.ok, result.errors)
        self.assertEqual(result.format, "sql")

    def test_render_and_validate_semantic_arrow(self) -> None:
        graph = sample_graph()
        nodes, edges = graph.expand(["N1"], hops=2)
        packet = render_semantic_arrow(graph, nodes, edges)
        result = validate_packet(packet)
        self.assertTrue(result.ok, result.errors)
        self.assertEqual(result.format, "semantic_arrow")
        self.assertEqual(result.node_count, 3)
        self.assertEqual(result.edge_count, 2)

    def test_render_and_validate_gg_max(self) -> None:
        graph = sample_graph()
        nodes, edges = graph.expand(["N1"], hops=2)
        packet = render_gg_max(graph, nodes, edges)
        result = validate_packet(packet)
        self.assertTrue(result.ok, result.errors)
        self.assertEqual(result.format, "gg_max")
        self.assertEqual(result.node_count, 3)
        self.assertEqual(result.edge_count, 2)

    def test_render_and_validate_gg_max_hybrid(self) -> None:
        graph = sample_graph()
        nodes, edges = graph.expand(["N1"], hops=2)
        from graphgraph.packets import render_packet
        packet = render_packet(graph, nodes, edges, "gg_max_hybrid")
        result = validate_packet(packet)
        self.assertTrue(result.ok, result.errors)
        self.assertEqual(result.format, "gg_max_hybrid")
        self.assertEqual(result.node_count, 3)
        self.assertEqual(result.edge_count, 2)

    def test_validation_rejects_missing_node(self) -> None:
        packet = """<g>
<r>
1:reads
</r>
<n>
N1:AuthService
</n>
<a>
N1,N2,1,0.9
</a>
</g>"""
        result = validate_packet(packet)
        self.assertFalse(result.ok)
        self.assertIn("edge target missing from nodes: N2", result.errors)

    def test_policy_selection(self) -> None:
        policies = [
            Policy("P1", "frontend", "must", ("src/ui/**",), ("frontend",), "UI compact"),
            Policy("P2", "security", "must", ("server/auth/**",), ("security",), "SEC compact"),
        ]
        query = Query("update button", "direct_lookup", paths=("src/ui/Button.tsx",), tags=("frontend",))
        selected = select_policies(policies, query)
        self.assertEqual([policy.id for policy in selected], ["P1"])
        self.assertEqual(render_policy_packet(selected), "P1:must:UI compact")

    def test_choose_packet_empirical_alignment(self) -> None:
        # Empirical data: direct/reverse → sql (low overhead at 1-hop)
        self.assertEqual(choose_packet("direct_lookup").packet, "sql")
        self.assertEqual(choose_packet("direct_lookup").hops, 1)
        self.assertEqual(choose_packet("reverse_lookup").packet, "sql")
        self.assertEqual(choose_packet("reverse_lookup").hops, 1)
        # blast_radius / multi_hop → gg_max 2-hop (token floor for topology)
        self.assertEqual(choose_packet("blast_radius").hops, 2)
        self.assertEqual(choose_packet("blast_radius").packet, "gg_max")
        self.assertEqual(choose_packet("multi_hop_path").hops, 2)
        self.assertEqual(choose_packet("multi_hop_path").packet, "gg_max")
        # summary → hybrid (needs inline facts)
        self.assertEqual(choose_packet("subsystem_summary").packet, "gg_max_hybrid")
        # unknown → conservative 2-hop gg_max
        self.assertEqual(choose_packet("unknown_xyz").hops, 2)
        self.assertEqual(choose_packet("unknown_xyz").packet, "gg_max")

    def test_load_graph_and_policies(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            graph_path = root / "graph.json"
            policies_path = root / "policies.json"
            graph_path.write_text(
                json.dumps(
                    {
                        "nodes": [{"id": "N1", "label": "A"}, {"id": "N2", "label": "B"}],
                        "edges": [{"source": "N1", "target": "N2", "type": "calls", "weight": 0.7}],
                    }
                ),
                encoding="utf-8",
            )
            policies_path.write_text(
                json.dumps(
                    [
                        {
                            "id": "P1",
                            "kind": "frontend",
                            "priority": "must",
                            "applies_to": ["src/**"],
                            "task_tags": ["frontend"],
                            "compact": "UI compact",
                        }
                    ]
                ),
                encoding="utf-8",
            )
            self.assertEqual(len(load_graph(graph_path).edges), 1)
            self.assertEqual(load_policies(policies_path)[0].id, "P1")

    def test_load_graph_fallback_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            graph_path = root / "graph.json"
            graph_path.write_text(
                json.dumps(
                    {
                        "nodes": [
                            {
                                "id": "N1",
                                "name": "AuthService",
                                "file_type": "service",
                                "source_file": "server/auth.py",
                                "properties": {"description": "Handles authentication"}
                            },
                            {
                                "id": "N2",
                                "type": "data",
                                "facts": None
                            }
                        ],
                        "edges": [{"source": "N1", "target": "N2", "relation": "reads"}],
                    }
                ),
                encoding="utf-8",
            )
            graph = load_graph(graph_path)
            n1 = graph.nodes["N1"]
            self.assertEqual(n1.label, "AuthService")
            self.assertEqual(n1.kind, "service")
            self.assertEqual(n1.path, "server/auth.py")
            self.assertEqual(n1.summary, "Handles authentication")
            self.assertEqual(n1.facts, ())

            n2 = graph.nodes["N2"]
            self.assertEqual(n2.label, "N2")
            self.assertEqual(n2.kind, "data")
            self.assertEqual(n2.path, "")
            self.assertEqual(n2.summary, "")
            self.assertEqual(n2.facts, ())

    def test_save_graph_and_ingest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path = root / "input_graph.json"
            output_path = root / "output_graph.json"
            input_path.write_text(
                json.dumps(
                    {
                        "nodes": [{"id": "N1", "name": "A", "file_type": "code", "properties": {"description": "summary text"}}],
                        "links": [{"source": "N1", "target": "N1", "relation": "calls"}]
                    }
                ),
                encoding="utf-8"
            )
            graph = load_graph(input_path)
            save_graph(graph, output_path)

            data = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertIn("nodes", data)
            self.assertIn("edges", data)
            self.assertEqual(data["nodes"][0]["label"], "A")
            self.assertEqual(data["nodes"][0]["kind"], "code")
            self.assertEqual(data["nodes"][0]["summary"], "summary text")
            self.assertEqual(data["edges"][0]["type"], "calls")

    def test_default_path_resolution(self) -> None:
        from graphgraph.io import find_graph_path, find_policies_path
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            with self.assertRaises(FileNotFoundError):
                find_graph_path(workspace_root=root)

            self.assertIsNone(find_policies_path(workspace_root=root))

            gg_dir = root / ".graphgraph"
            gg_dir.mkdir()
            mock_graph = gg_dir / "graph.json"
            mock_graph.write_text("{}", encoding="utf-8")

            self.assertEqual(find_graph_path(workspace_root=root), mock_graph)

            mock_policies = root / "policies.json"
            mock_policies.write_text("[]", encoding="utf-8")
            self.assertEqual(find_policies_path(workspace_root=root), mock_policies)

    def test_mcp_plan_context(self) -> None:
        response = dispatch({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "plan_context", "arguments": {"query_class": "blast_radius"}}})
        assert response is not None
        text = response["result"]["content"][0]["text"]
        self.assertIn('"hops": 2', text)
        self.assertIn('"packet": "gg_max"', text)

    def test_mcp_plan_context_direct_lookup(self) -> None:
        response = dispatch({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "plan_context", "arguments": {"query_class": "direct_lookup"}}})
        assert response is not None
        text = response["result"]["content"][0]["text"]
        data = json.loads(text)
        self.assertEqual(data["packet"], "sql")
        self.assertEqual(data["hops"], 1)

    def test_mcp_describe_formats(self) -> None:
        response = dispatch({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "describe_formats", "arguments": {}}})
        assert response is not None
        text = response["result"]["content"][0]["text"]
        data = json.loads(text)
        formats = [f["format"] for f in data]
        self.assertIn("gg_max", formats)
        self.assertIn("sql", formats)
        self.assertIn("semantic_arrow", formats)

    def test_mcp_validate_packet(self) -> None:
        graph = sample_graph()
        nodes, edges = graph.expand(["N1"], hops=2)
        packet = render_gg_max(graph, nodes, edges)
        response = dispatch({"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "validate_packet", "arguments": {"packet": packet}}})
        assert response is not None
        data = json.loads(response["result"]["content"][0]["text"])
        self.assertTrue(data["ok"])
        self.assertEqual(data["format"], "gg_max")

    def test_mcp_search_nodes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            graph_path = root / "graph.json"
            graph_path.write_text(
                json.dumps({
                    "nodes": [
                        {"id": "N1", "label": "AuthService", "kind": "service", "path": "server/auth.py"},
                        {"id": "N2", "label": "TokenStore", "kind": "data", "path": "server/tokens.py"},
                    ],
                    "edges": [],
                }),
                encoding="utf-8",
            )
            response = dispatch({
                "jsonrpc": "2.0", "id": 5, "method": "tools/call",
                "params": {"name": "search_nodes", "arguments": {"query": "auth", "graph_path": str(graph_path)}},
            })
            assert response is not None
            data = json.loads(response["result"]["content"][0]["text"])
            ids = [m["id"] for m in data["matches"]]
            self.assertIn("N1", ids)
            self.assertNotIn("N2", ids)

    def test_mcp_build_graph_scan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # Create a small Python package
            (root / "main.py").write_text("from utils import helper\n", encoding="utf-8")
            (root / "utils.py").write_text("def helper(): pass\n", encoding="utf-8")
            output = root / "graph.json"
            response = dispatch({
                "jsonrpc": "2.0", "id": 6, "method": "tools/call",
                "params": {"name": "build_graph", "arguments": {
                    "directory": str(root),
                    "output_path": str(output),
                }},
            })
            assert response is not None
            data = json.loads(response["result"]["content"][0]["text"])
            self.assertEqual(data["action"], "scanned")
            self.assertGreaterEqual(data["nodes"], 2)
            self.assertTrue(output.exists())

    def test_scanner_detects_imports(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "app.py").write_text("from db import connect\nfrom utils import helper\n", encoding="utf-8")
            (root / "db.py").write_text("def connect(): pass\n", encoding="utf-8")
            (root / "utils.py").write_text("def helper(): pass\n", encoding="utf-8")
            graph = scan_directory(root)
            self.assertEqual(len(graph.nodes), 3)
            edge_pairs = {(e.source, e.target) for e in graph.edges}
            app_id = next(nid for nid, n in graph.nodes.items() if n.label == "app.py")
            db_id = next(nid for nid, n in graph.nodes.items() if n.label == "db.py")
            utils_id = next(nid for nid, n in graph.nodes.items() if n.label == "utils.py")
            self.assertIn((app_id, db_id), edge_pairs)
            self.assertIn((app_id, utils_id), edge_pairs)

    def test_scanner_skips_pycache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "__pycache__").mkdir()
            (root / "__pycache__" / "app.cpython-312.pyc").write_bytes(b"")
            (root / "app.py").write_text("pass\n", encoding="utf-8")
            graph = scan_directory(root)
            for node in graph.nodes.values():
                self.assertNotIn("__pycache__", node.path)
            self.assertEqual(len(graph.nodes), 1)

    def test_scanner_max_nodes_respected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for i in range(10):
                (root / f"mod_{i}.py").write_text("pass\n", encoding="utf-8")
            graph = scan_directory(root, max_nodes=5)
            self.assertLessEqual(len(graph.nodes), 5)

    def test_scanner_markdown_links(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "index.md").write_text("See [guide](./guide.md) for details.\n", encoding="utf-8")
            (root / "guide.md").write_text("# Guide\n", encoding="utf-8")
            graph = scan_directory(root)
            self.assertEqual(len(graph.nodes), 2)
            edge_types = {e.type for e in graph.edges}
            self.assertIn("links", edge_types)

    def test_scanner_c_includes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "main.c").write_text('#include "utils.h"\nint main(){}\n', encoding="utf-8")
            (root / "utils.h").write_text("void helper();\n", encoding="utf-8")
            graph = scan_directory(root)
            self.assertEqual(len(graph.nodes), 2)
            self.assertEqual(len(graph.edges), 1)
            self.assertEqual(graph.edges[0].type, "imports")

    def test_scanner_rust_mod(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "main.rs").write_text("mod utils;\nfn main(){}\n", encoding="utf-8")
            (root / "utils.rs").write_text("pub fn helper(){}\n", encoding="utf-8")
            graph = scan_directory(root)
            self.assertEqual(len(graph.nodes), 2)
            self.assertEqual(len(graph.edges), 1)

    def test_scanner_go_relative_import(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "main.go").write_text('import "./pkg"\nfunc main(){}\n', encoding="utf-8")
            pkg = root / "pkg"
            pkg.mkdir()
            (pkg / "pkg.go").write_text("package pkg\n", encoding="utf-8")
            graph = scan_directory(root)
            # main.go and pkg/pkg.go should be nodes
            self.assertGreaterEqual(len(graph.nodes), 2)

    def test_scanner_generic_mentions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.txt").write_text("See the config module for settings.\n", encoding="utf-8")
            (root / "config.py").write_text("# config\n", encoding="utf-8")
            graph = scan_directory(root, generic_mentions=True)
            edge_types = {e.type for e in graph.edges}
            self.assertIn("references", edge_types)

    def test_scanner_html_href(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "index.html").write_text('<a href="./about.html">About</a>\n', encoding="utf-8")
            (root / "about.html").write_text("<h1>About</h1>\n", encoding="utf-8")
            graph = scan_directory(root)
            self.assertEqual(len(graph.nodes), 2)
            self.assertTrue(any(e.type == "links" for e in graph.edges))

    def test_scanner_depth_symbols_python(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "app.py").write_text(
                "class Server:\n    def handle(self):\n        pass\n\ndef run():\n    pass\n",
                encoding="utf-8",
            )
            graph = scan_directory(root, depth="symbols")
            kinds = {n.kind for n in graph.nodes.values()}
            self.assertIn("class", kinds)
            self.assertIn("function", kinds)
            contains_edges = [e for e in graph.edges if e.type == "contains"]
            self.assertGreaterEqual(len(contains_edges), 2)

    def test_scanner_depth_symbols_rust(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "lib.rs").write_text(
                "pub struct Config { pub name: String }\npub fn load() -> Config { todo!() }\n",
                encoding="utf-8",
            )
            graph = scan_directory(root, depth="symbols")
            kinds = {n.kind for n in graph.nodes.values()}
            self.assertIn("struct", kinds)
            self.assertIn("function", kinds)

    def test_scanner_depth_symbols_cross_file_references(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "server.py").write_text(
                "def handle_request(config):\n    return config\n",
                encoding="utf-8",
            )
            (root / "main.py").write_text(
                "from server import handle_request\nhandle_request(None)\n",
                encoding="utf-8",
            )
            graph = scan_directory(root, depth="symbols")
            ref_edges = [e for e in graph.edges if e.type == "references"]
            self.assertGreaterEqual(len(ref_edges), 1)

    def test_scanner_depth_symbols_js(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "api.js").write_text(
                "class Router {}\nexport function createApp() { return new Router(); }\n",
                encoding="utf-8",
            )
            graph = scan_directory(root, depth="symbols")
            kinds = {n.kind for n in graph.nodes.values()}
            self.assertIn("class", kinds)
            self.assertIn("function", kinds)

    def test_extract_symbols_python(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            f = root / "mod.py"
            f.write_text("class Foo:\n    def bar(self): pass\n\ndef baz(): pass\n", encoding="utf-8")
            tuples = [(f, "mod.py", "mod_py", f.read_text(encoding="utf-8"))]
            nodes, edges = extract_symbols(tuples)
            labels = {n.label for n in nodes.values()}
            self.assertIn("Foo", labels)
            self.assertIn("baz", labels)
            contains = [e for e in edges if e.type == "contains"]
            self.assertGreaterEqual(len(contains), 2)

    def test_extract_symbols_rust(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            f = root / "lib.rs"
            f.write_text("pub struct Point { x: i32 }\npub fn distance(a: Point) -> f64 { 0.0 }\n", encoding="utf-8")
            tuples = [(f, "lib.rs", "lib_rs", f.read_text(encoding="utf-8"))]
            nodes, edges = extract_symbols(tuples)
            labels = {n.label for n in nodes.values()}
            self.assertIn("Point", labels)
            self.assertIn("distance", labels)


    # --- .gg roundtrip tests ---

    def test_save_load_gg_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            g = sample_graph()
            path = Path(tmp) / "graph.gg"
            save_gg(g, path)
            g2 = load_gg(path)
            self.assertEqual(set(n.label for n in g.nodes.values()),
                             set(n.label for n in g2.nodes.values()))
            self.assertEqual(len(g.edges), len(g2.edges))
            edge_types = {e.type for e in g2.edges}
            self.assertIn("reads", edge_types)
            self.assertIn("writes", edge_types)

    def test_save_gg_omits_weight_when_one(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            g = Graph(
                nodes={"A": Node("A", "Alpha", "file", "a.py"), "B": Node("B", "Beta", "file", "b.py")},
                edges=[Edge("A", "B", "imports", 1.0)],
            )
            path = Path(tmp) / "g.gg"
            save_gg(g, path)
            content = path.read_text(encoding="utf-8")
            self.assertNotIn("1.0", content)
            self.assertIn("imports Beta", content)

    def test_load_gg_preserves_kind(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "g.gg"
            path.write_text("gg/1\nMyService [service] server/svc.py\n", encoding="utf-8")
            g = load_gg(path)
            self.assertEqual(len(g.nodes), 1)
            node = list(g.nodes.values())[0]
            self.assertEqual(node.kind, "service")
            self.assertEqual(node.path, "server/svc.py")

    def test_load_any_routes_gg(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            g = sample_graph()
            path = Path(tmp) / "graph.gg"
            save_gg(g, path)
            g2 = load_any(path)
            self.assertEqual(len(g.nodes), len(g2.nodes))

    # --- CSV ingest tests ---

    def test_load_csv_edges_basic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "edges.csv"
            path.write_text("source,target,type,weight\nA,B,calls,0.9\nB,C,imports,1.0\n", encoding="utf-8")
            g = load_csv_edges(path)
            self.assertEqual(len(g.nodes), 3)
            self.assertEqual(len(g.edges), 2)
            self.assertEqual(g.edges[0].weight, 0.9)

    def test_load_csv_edges_no_header(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "edges.csv"
            path.write_text("Foo,Bar\nBaz,Qux\n", encoding="utf-8")
            g = load_csv_edges(path)
            self.assertEqual(len(g.nodes), 4)
            self.assertEqual(len(g.edges), 2)
            self.assertEqual(g.edges[0].type, "relates")

    def test_load_tsv_edges(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "edges.tsv"
            path.write_text("X\tY\tcalls\nY\tZ\treads\n", encoding="utf-8")
            g = load_csv_edges(path)
            self.assertEqual(len(g.nodes), 3)
            self.assertEqual(len(g.edges), 2)

    def test_load_any_routes_csv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "edges.csv"
            path.write_text("A,B\nC,D\n", encoding="utf-8")
            g = load_any(path)
            self.assertEqual(len(g.nodes), 4)

    # --- render_svo tests ---

    def test_render_svo_basic(self) -> None:
        g = sample_graph()
        nodes = set(g.nodes.keys())
        packet = render_svo(g, nodes, g.edges)
        self.assertIn("AuthService", packet)
        self.assertIn("-reads->", packet)
        self.assertIn("TokenStore", packet)

    def test_render_svo_omits_weight_when_one(self) -> None:
        g = Graph(
            nodes={"A": Node("A", "Alpha", "file", ""), "B": Node("B", "Beta", "file", "")},
            edges=[Edge("A", "B", "imports", 1.0)],
        )
        packet = render_svo(g, set(g.nodes.keys()), g.edges)
        self.assertNotIn("(1", packet)
        self.assertIn("Alpha -imports-> Beta", packet)

    def test_render_svo_includes_weight_when_not_one(self) -> None:
        g = Graph(
            nodes={"A": Node("A", "Alpha", "file", ""), "B": Node("B", "Beta", "file", "")},
            edges=[Edge("A", "B", "calls", 0.75)],
        )
        packet = render_svo(g, set(g.nodes.keys()), g.edges)
        self.assertIn("(0.75)", packet)

    def test_render_svo_empty_edges(self) -> None:
        g = sample_graph()
        packet = render_svo(g, set(g.nodes.keys()), [])
        self.assertEqual(packet, "")


if __name__ == "__main__":
    unittest.main()
