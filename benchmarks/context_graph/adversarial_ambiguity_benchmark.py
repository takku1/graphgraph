"""Adversarial ambiguity benchmark (roadmap P0 #3).

Constructs synthetic graphs that deliberately stress anchor disambiguation --
duplicate symbols, generated vs hand-written sources, re-exports, overloaded
methods, and mixed documentation/code anchors -- and checks whether retrieval
resolves each query to the correct node. Every case has one unambiguous
"expected" answer given the query wording; a failure means the ranking is
resolving on graph shape rather than query intent.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from graphgraph.graph.core import Edge, Graph, Node  # noqa: E402
from graphgraph.retrieval.search import search_nodes  # noqa: E402

OUT = ROOT / "benchmarks" / "context_graph" / "out" / "real_projects"
REPORT_MD = OUT / "adversarial_ambiguity.md"


@dataclass
class Case:
    name: str
    graph: Graph
    query: str
    expected: str
    doc_intensity: float = 0.0
    note: str = ""


def _g(nodes: list[Node], edges: list[Edge] | None = None) -> Graph:
    return Graph(nodes={n.id: n for n in nodes}, edges=edges or [])


def duplicate_symbol_path_hint() -> Case:
    # Two functions named "parse" in different packages; the query names the
    # package. Correct resolution uses the path term, not degree/order.
    g = _g([
        Node("json_parse", "parse", "function", "src/json/parse.py"),
        Node("xml_parse", "parse", "function", "src/xml/parse.py"),
    ])
    return Case("duplicate_symbol_path_hint", g, "json parse", "json_parse")


def generated_vs_handwritten() -> Case:
    # Adversarial: identical label/summary in a hand-written model and a
    # generated protobuf stub, with the generated stub MORE connected (higher
    # degree/PPR). Only a generated-source signal -- not lexical score or
    # connectivity -- can prefer the source of truth here.
    nodes = [
        Node("models_user", "User", "class", "src/models/user.py", summary="user record"),
        Node("gen_user_pb2", "User", "class", "build/generated/user_pb2.py", summary="user record"),
    ]
    edges = []
    for i in range(6):
        nodes.append(Node(f"caller_{i}", f"caller_{i}", "function", f"src/callers/c{i}.py"))
        edges.append(Edge(f"caller_{i}", "gen_user_pb2", "imports_from"))
    return Case("generated_vs_handwritten", _g(nodes, edges), "User", "models_user",
                note="identical text; generated stub more connected")


def reexport_prefers_definition() -> Case:
    # A function defined in a module and re-exported through a package __init__.
    # "where is X defined" should land on the definition, not the facade file.
    g = _g([
        Node("budgets_compute", "compute_budget", "function", "src/planning/budgets.py"),
        Node("planning_init", "__init__.py", "python", "src/planning/__init__.py",
             summary="from .budgets import compute_budget", facts=("compute_budget",)),
    ], [
        Edge("planning_init", "budgets_compute", "imports_from"),
    ])
    return Case("reexport_prefers_definition", g, "compute_budget", "budgets_compute")


def overloaded_method_context() -> Case:
    # "save" exists on two repositories; the query names the entity, which
    # should select the matching class's method.
    g = _g([
        Node("user_repo_save", "save", "method", "src/repo/user_repository.py",
             parent="UserRepository", summary="persist a user record"),
        Node("order_repo_save", "save", "method", "src/repo/order_repository.py",
             parent="OrderRepository", summary="persist an order record"),
    ])
    return Case("overloaded_method_context", g, "save user", "user_repo_save")


def mixed_doc_code_structural() -> Case:
    # Same term matches a doc section and a code symbol. A structural query
    # should anchor on code; a doc query should anchor on the section.
    nodes = [
        Node("auth_fn", "authenticate", "function", "src/auth/login.py",
             summary="verify credentials and issue a session"),
        Node("auth_doc", "Authentication", "section", "docs/auth.md",
             facts=("how authentication works in the system",)),
    ]
    return _g(nodes), nodes  # type: ignore[return-value]


def many_file_collision_with_scope() -> Case:
    # The same symbol name defined in eight files; only the query's path term
    # ("database") should decide which one wins. Tests that path relevance, not
    # arbitrary order or degree, breaks a large collision.
    nodes = []
    for pkg in ("http", "cache", "auth", "queue", "render", "parser", "config", "database"):
        nodes.append(Node(f"{pkg}_handler", "handler", "function", f"src/{pkg}/handler.py",
                          summary=f"{pkg} request handler"))
    return Case("many_file_collision_with_scope", _g(nodes), "database handler", "database_handler")


def cyclic_reexport_chain() -> Case:
    # Definition re-exported through a two-hop package facade that also cycles
    # back. Resolving the symbol must land on the real definition (a function),
    # not a facade __init__ file, and must not be confused by the cycle.
    nodes = [
        Node("core_connect", "connect", "function", "src/db/core.py",
             summary="open a database connection"),
        Node("db_init", "__init__.py", "python", "src/db/__init__.py",
             summary="from .core import connect", facts=("connect",)),
        Node("pkg_init", "__init__.py", "python", "src/__init__.py",
             summary="from .db import connect", facts=("connect",)),
    ]
    edges = [
        Edge("db_init", "core_connect", "imports_from"),
        Edge("pkg_init", "db_init", "imports_from"),
        Edge("db_init", "pkg_init", "imports_from"),  # cycle
    ]
    return Case("cyclic_reexport_chain", _g(nodes, edges), "connect", "core_connect")


def overload_by_signature() -> Case:
    # Two same-named methods separated only by what their bodies mention; the
    # query names a parameter that disambiguates them.
    nodes = [
        Node("connect_retries", "connect", "method", "src/client/a.py", parent="ClientA",
             summary="connect", facts=("retries the connection with backoff",)),
        Node("connect_timeout", "connect", "method", "src/client/b.py", parent="ClientB",
             summary="connect", facts=("applies a socket timeout to the connection",)),
    ]
    return Case("overload_by_signature", _g(nodes), "connect with retries backoff", "connect_retries")


def build_cases() -> list[Case]:
    code_nodes = mixed_doc_code_structural()[1]
    code_graph = _g(code_nodes)
    return [
        duplicate_symbol_path_hint(),
        generated_vs_handwritten(),
        reexport_prefers_definition(),
        overloaded_method_context(),
        Case("mixed_doc_code__structural", code_graph, "authenticate", "auth_fn",
             doc_intensity=0.0, note="structural intent -> code anchor"),
        Case("mixed_doc_code__doc", code_graph, "authentication", "auth_doc",
             doc_intensity=1.0, note="doc intent -> section anchor"),
        many_file_collision_with_scope(),
        cyclic_reexport_chain(),
        overload_by_signature(),
    ]


def run() -> tuple[int, int, list[str]]:
    lines = ["# Adversarial Ambiguity Benchmark", ""]
    lines.append("| Case | Query | Expected | Top-1 | Pass |")
    lines.append("| --- | --- | --- | --- | --- |")
    passed = 0
    cases = build_cases()
    for case in cases:
        matches = search_nodes(
            case.graph, case.query, limit=5, doc_intensity=case.doc_intensity, personalize=True
        )
        top = matches[0].node.id if matches else "(none)"
        ok = top == case.expected
        passed += ok
        lines.append(f"| {case.name} | `{case.query}` | {case.expected} | {top} | {'yes' if ok else 'NO'} |")
    lines.append("")
    lines.append(f"**{passed}/{len(cases)} adversarial cases resolved correctly.**")
    return passed, len(cases), lines


def main() -> None:
    passed, total, lines = run()
    report = "\n".join(lines)
    print(report)
    OUT.mkdir(parents=True, exist_ok=True)
    REPORT_MD.write_text(report + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
