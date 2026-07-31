"""Saved-graph validation, conversion, and comparison CLI commands."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..analysis.metrics import compare_graphs
from ..io import (
    find_graph_path,
    load_any,
    save_gg,
    save_validated_graph,
    validate_graph_file,
)
from ..packets.validation import validate_any


def cmd_validate(args: argparse.Namespace) -> None:
    if args.packet:
        packet = Path(args.packet).read_text(encoding="utf-8")
    elif not sys.stdin.isatty():
        packet = sys.stdin.read()
    else:
        packet = ""

    if not packet.strip():
        print(
            "FAIL no packet input: pipe a non-empty packet via stdin or pass "
            "--packet <file>."
        )
        print("Use `graphgraph validate-graph` to validate a saved graph explicitly.")
        sys.exit(1)

    result = validate_any(packet)
    status = "PASS" if result.ok else "FAIL"
    print(
        f"STRUCTURAL {status} {result.format} "
        f"nodes={result.node_count} edges={result.edge_count}"
    )
    for error in result.errors:
        print(f"- {error}")
    if not result.ok:
        sys.exit(1)


def cmd_validate_graph(args: argparse.Namespace) -> None:
    requested_path = args.graph or getattr(args, "path", None)
    graph_path = Path(requested_path) if requested_path else find_graph_path()
    result = validate_graph_file(graph_path)
    status = "PASS" if result.ok else "FAIL"
    print(
        f"STRUCTURAL {status} {result.format} nodes={result.node_count} "
        f"edges={result.edge_count} path={graph_path}"
    )
    for error in result.errors:
        print(f"- {error}")
    if not result.ok:
        sys.exit(1)


def cmd_ingest(args: argparse.Namespace) -> None:
    if args.input:
        input_path = Path(args.input)
    else:
        try:
            input_path = find_graph_path()
        except FileNotFoundError:
            raise FileNotFoundError(
                "Could not find input graph. Specify --input explicitly."
            )
    output_path = Path(args.output) if args.output else Path(".graphgraph/graph.gg")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    graph = load_any(input_path, normalize_external_refs=True)
    validation = save_validated_graph(graph, output_path)
    print(
        f"Ingested {len(graph.nodes)} nodes, {len(graph.edges)} edges from "
        f"{input_path} -> {output_path} (validation PASS {validation.format})"
    )


def cmd_export(args: argparse.Namespace) -> None:
    graph_path = Path(args.graph) if args.graph else find_graph_path()
    output_path = Path(args.output) if args.output else graph_path.with_suffix(".gg")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    graph = load_any(graph_path)
    save_gg(graph, output_path)
    print(
        f"Exported {len(graph.nodes)} nodes, {len(graph.edges)} edges -> {output_path}"
    )


def cmd_compare(args: argparse.Namespace) -> None:
    left = load_any(Path(args.left))
    right = load_any(Path(args.right))
    comparison = compare_graphs(left, right)
    data = {
        "left": comparison.left.__dict__,
        "right": comparison.right.__dict__,
        "shared_node_paths": comparison.shared_node_paths,
        "shared_edge_keys": comparison.shared_edge_keys,
        "left_only_edge_keys": comparison.left_only_edge_keys,
        "right_only_edge_keys": comparison.right_only_edge_keys,
        "shared_normalized_edges": comparison.shared_normalized_edges,
    }
    print(json.dumps(data, indent=2, ensure_ascii=False))


__all__ = [
    "cmd_compare",
    "cmd_export",
    "cmd_ingest",
    "cmd_validate",
    "cmd_validate_graph",
]
