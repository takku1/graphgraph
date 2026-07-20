"""Test command inference and affected-test recommendations."""

from __future__ import annotations

import math
import re
from functools import lru_cache
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 compatibility
    import tomli as tomllib

from ..concepts.terms import term_key
from ..graph.core import Edge, Graph
from ..planning import ContextPlan
from .facets import (
    _AFFECTED_OUTPUT_TERMS,
    reconcile_affected_output_facets,
)
from .models import RetrievalResult
from .pruning import (
    _least_valuable_context_node,
)
from .scoping import (
    _is_test_node,
    _is_test_path,
)


def _cargo_source_context(source: str) -> tuple[str, Path, Path] | None:
    """Return package, manifest directory, and source-relative path."""
    if not source:
        return None
    source_path = Path(source)
    if not source_path.exists():
        return None
    manifest = next(
        (parent / "Cargo.toml" for parent in (source_path.parent, *source_path.parents) if (parent / "Cargo.toml").is_file()),
        None,
    )
    if manifest is None:
        return None
    try:
        data = tomllib.loads(manifest.read_text(encoding="utf-8"))
        package = str(data.get("package", {}).get("name", "")).strip()
        relative = source_path.resolve().relative_to(manifest.parent.resolve())
    except (OSError, ValueError, tomllib.TOMLDecodeError):
        return None
    if not package or not relative.parts or source_path.suffix != ".rs":
        return None
    return package, manifest.parent, relative

def _cargo_test_target(source: str) -> tuple[str, str, str] | None:
    """Return (package, integration target, optional module filter)."""
    context = _cargo_source_context(source)
    if context is None:
        return None
    package, manifest_dir, relative = context
    if relative.parts[0] != "tests":
        return None
    source_path = manifest_dir / relative
    try:
        data = tomllib.loads((manifest_dir / "Cargo.toml").read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return None

    # Explicit [[test]] targets are authoritative. A consolidated harness may
    # include module files beneath the harness directory, so map descendants
    # back to that declared target and use the module stem as a Cargo filter.
    for target in data.get("test", ()):
        target_name = str(target.get("name", "")).strip()
        target_path = str(target.get("path", "")).strip()
        if not target_name or not target_path:
            continue
        harness = (manifest_dir / target_path).resolve()
        if source_path.resolve() == harness:
            return package, target_name, ""
        if harness.name in {"main.rs", "lib.rs"} and harness.parent in source_path.resolve().parents:
            return package, target_name, source_path.stem

    tests_root = manifest_dir / "tests"
    nested = relative.parts[1:]
    if len(nested) == 1:
        return package, source_path.stem, ""
    # Cargo auto-discovers tests/<target>/main.rs as one integration binary.
    for parent in (source_path.parent, *source_path.parents):
        if parent == tests_root or tests_root not in parent.parents:
            break
        if (parent / "main.rs").is_file():
            target_name = parent.relative_to(tests_root).parts[0]
            return package, target_name, "" if source_path.name == "main.rs" else source_path.stem
    return None

def _cargo_inline_rust_test_target(source: str) -> tuple[str, str, str] | None:
    """Return package, module filter, and Cargo target for an inline Rust test."""
    context = _cargo_source_context(source)
    if context is None:
        return None
    package, manifest_dir, relative = context
    if relative.parts[0] != "src":
        return None
    if (manifest_dir / "src" / "lib.rs").is_file():
        target = "--lib"
    else:
        return None
    module_parts = list(relative.parts[1:])
    filename = module_parts.pop() if module_parts else ""
    stem = Path(filename).stem
    if stem not in {"lib", "main", "mod"}:
        module_parts.append(stem)
    module_filter = "::".join((*module_parts, "tests"))
    return package, module_filter, target

def _cargo_inline_rust_module_command(source: str) -> str:
    target = _cargo_inline_rust_test_target(source)
    if target is None:
        return ""
    package, module_filter, cargo_target = target
    suffix = f" {module_filter}" if module_filter else ""
    return f"cargo test -p {package}{suffix} {cargo_target}"

@lru_cache(maxsize=2048)
def _rust_test_module_calls_symbol(source: str, label: str) -> bool:
    """Verify a missing graph edge against the bounded inline test module."""
    path = Path(source)
    if path.suffix.casefold() != ".rs" or not path.is_file() or not label:
        return False
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    marker = re.search(r"#\s*\[\s*cfg\s*\(\s*test\s*\)\s*\]", text)
    if marker is None:
        return False
    test_module = text[marker.end():]
    return bool(re.search(rf"\b{re.escape(label)}\s*\(", test_module))

def _test_command(
    path: str,
    source: str = "",
    *,
    inline_test: bool = False,
    test_label: str = "",
) -> str:
    normalized = path.replace("\\", "/")
    parts = normalized.split("/")
    if inline_test and normalized.endswith(".rs"):
        cargo_target = _cargo_inline_rust_test_target(source)
        if cargo_target is not None:
            package, module_filter, target = cargo_target
            # The graph already carries the exact test function label. Cargo
            # accepts it as a filter regardless of whether the containing
            # module is named `tests`, `normalize_tests`, or something else.
            # Retain the module fallback only for legacy nodes without labels.
            test_filter = test_label.strip() or module_filter
            return f"cargo test -p {package} {test_filter} {target}"
    if len(parts) >= 4 and parts[0] == "crates" and "tests" in parts and normalized.endswith(".rs"):
        cargo_target = _cargo_test_target(source)
        if cargo_target is not None:
            package, target, module_filter = cargo_target
            suffix = f" {module_filter}" if module_filter else ""
            return f"cargo test -p {package} --test {target}{suffix}"
        test_name = normalized.rsplit("/", 1)[-1][:-3]
        return f"cargo test -p {parts[1]} --test {test_name}"
    if len(parts) >= 2 and parts[0] == "crates" and normalized.endswith(".rs"):
        return f"cargo test -p {parts[1]}"
    if normalized.endswith(".py"):
        return f"python -m pytest {normalized}"
    if normalized.endswith((".ts", ".tsx", ".js", ".jsx")):
        return f"npm test -- {normalized}"
    return ""

def changed_path_test_recommendations(
    graph: Graph,
    paths: tuple[str, ...],
) -> dict[str, object]:
    """Derive deterministic regression commands from explicit changed test paths."""
    normalized_paths = tuple(
        dict.fromkeys(path.replace("\\", "/").strip("/") for path in paths)
    )
    candidates: list[dict[str, object]] = []
    commands: list[str] = []
    provenance: list[dict[str, object]] = []
    for path in normalized_paths:
        path_nodes = [
            node
            for node in graph.nodes.values()
            if node.active and node.path.replace("\\", "/").strip("/") == path
        ]
        test_nodes = [node for node in path_nodes if _is_test_node(node)]
        command_tests: dict[str, list[dict[str, object]]] = {}
        for node in test_nodes:
            command = _test_command(
                path,
                node.source,
                inline_test=not _is_test_path(path),
            )
            if not command:
                continue
            candidate = {
                "id": node.id,
                "label": node.label,
                "path": path,
                "role": "changed_path_regression",
            }
            candidates.append(candidate)
            command_tests.setdefault(command, []).append(candidate)
        if not command_tests and _is_test_path(path):
            source = next(
                (node.source for node in path_nodes if node.source),
                "",
            )
            command = _test_command(path, source)
            if command:
                file_candidate = {
                    "id": next((node.id for node in path_nodes), ""),
                    "label": Path(path).name,
                    "path": path,
                    "role": "changed_path_regression",
                }
                candidates.append(file_candidate)
                command_tests[command] = [file_candidate]
        for command, tests in command_tests.items():
            if command not in commands:
                commands.append(command)
                provenance.append({
                    "command": command,
                    "role": "changed_path_regression",
                    "tests": tests,
                })
    return {
        "candidates": candidates,
        "commands": commands,
        "command_provenance": provenance,
    }

def affected_test_recommendations(
    graph: Graph,
    starts: tuple[str, ...],
    selected_nodes: set[str],
    *,
    cover_all_direct_tests: bool = False,
) -> dict[str, object]:
    incoming: dict[str, list[Edge]] = {}
    for edge in graph.edges:
        if edge.active and edge.type in {"calls", "references", "tests"}:
            incoming.setdefault(edge.target, []).append(edge)
    distances = {start: 0 for start in starts}
    covered_starts: dict[str, set[str]] = {start: {start} for start in starts}
    evidence_by_node: dict[str, list[Edge]] = {}
    paths_by_node: dict[str, dict[str, tuple[tuple[str, ...], tuple[Edge, ...]]]] = {}
    # Track each requested anchor independently. A merged frontier makes
    # coverage order-dependent when one anchor is itself upstream of another:
    # whichever set element is visited first can miss the later-propagated
    # anchor. The product is bounded by <=12 starts and two hops.
    for start in starts:
        owned_edges = [
            edge
            for edge in graph.edges
            if edge.active
            and edge.type == "contains"
            and edge.source == start
            and edge.target in graph.nodes
        ]
        owned_targets = {
            node_id
            for node_id, node in graph.nodes.items()
            if node.active and node.parent == start
        } | {edge.target for edge in owned_edges}
        frontier = {start, *owned_targets}
        seen = set(frontier)
        root_paths: dict[str, tuple[tuple[str, ...], tuple[Edge, ...]]] = {
            start: ((start,), ())
        }
        for target in owned_targets:
            containment = next(
                (edge for edge in owned_edges if edge.target == target),
                None,
            )
            root_paths[target] = (
                (target, start),
                (containment,) if containment is not None else (),
            )
        for distance in (1, 2):
            next_frontier: set[str] = set()
            for target in frontier:
                for edge in incoming.get(target, ()):
                    covered_starts.setdefault(edge.source, set()).add(start)
                    if edge not in evidence_by_node.setdefault(edge.source, []):
                        evidence_by_node[edge.source].append(edge)
                    distances[edge.source] = min(distance, distances.get(edge.source, distance))
                    target_nodes, target_edges = root_paths[target]
                    candidate_path = ((edge.source, *target_nodes), (edge, *target_edges))
                    prior_path = root_paths.get(edge.source)
                    if prior_path is None or len(candidate_path[1]) < len(prior_path[1]):
                        root_paths[edge.source] = candidate_path
                        paths_by_node.setdefault(edge.source, {})[start] = candidate_path
                    if edge.source not in seen:
                        seen.add(edge.source)
                        next_frontier.add(edge.source)
            frontier = next_frontier
    direct: list[dict[str, object]] = []
    transitive: list[dict[str, object]] = []
    for node_id, distance in sorted(distances.items(), key=lambda item: (item[1], item[0])):
        node = graph.nodes.get(node_id)
        if node is None or not _is_test_node(node):
            continue
        evidence_edges = evidence_by_node.get(node_id, ())
        effective_distance = distance
        if distance == 0:
            # A compound affected-test query can name both an implementation
            # symbol and an exact test. The test then becomes a traversal root,
            # but it is still direct test evidence when a calls/references/tests
            # edge connects it to another selected root. Do not let the root
            # designation erase evidence that is present in the packet.
            if node_id not in selected_nodes or not evidence_edges:
                continue
            effective_distance = 1
        item = {
            "id": node.id,
            "label": node.label,
            "path": node.path,
            "distance": effective_distance,
            "in_packet": node_id in selected_nodes,
            "evidence": [
                {
                    "type": edge.type,
                    "confidence": edge.confidence,
                    "provenance": edge.provenance,
                }
                for edge in evidence_edges[:3]
            ],
            "covers": [
                {"id": start, "label": graph.nodes[start].label}
                for start in sorted(covered_starts.get(node_id, ()))
                if start in graph.nodes
            ],
            "root_paths": [
                {
                    "root": {"id": start, "label": graph.nodes[start].label},
                    "nodes": [
                        {"id": path_node, "label": graph.nodes[path_node].label}
                        for path_node in path_nodes
                        if path_node in graph.nodes
                    ],
                    "edges": [
                        {
                            "source": edge.source,
                            "target": edge.target,
                            "type": edge.type,
                            "confidence": edge.confidence,
                            "provenance": edge.provenance,
                        }
                        for edge in path_edges
                    ],
                }
                for start, (path_nodes, path_edges) in sorted(paths_by_node.get(node_id, {}).items())
                if start in graph.nodes
            ],
        }
        (direct if effective_distance == 1 else transitive).append(item)
    def recommendation_rank(item: dict[str, object]) -> tuple[object, ...]:
        evidence = item.get("evidence", [])
        max_confidence = max(
            (float(edge.get("confidence", 0.0)) for edge in evidence if isinstance(edge, dict)),
            default=0.0,
        )
        return (
            -len(item.get("covers", [])),
            -max_confidence,
            str(item.get("path", "")),
            str(item.get("label", "")),
        )

    direct.sort(key=recommendation_rank)
    transitive.sort(key=recommendation_rank)
    omitted_direct = max(0, len(direct) - 12)
    omitted_transitive = max(0, len(transitive) - 12)
    direct = direct[:12]
    transitive = transitive[:12]

    def commands_for(items: list[dict[str, object]]) -> list[str]:
        return list(dict.fromkeys(
            command
            for item in items
            if (
                command := _test_command(
                    str(item["path"]),
                    graph.nodes[str(item["id"])].source,
                    inline_test=not _is_test_path(str(item["path"])),
                    test_label=str(item.get("label", "")),
                )
            )
        ))

    direct_commands = commands_for(direct)
    transitive_commands = commands_for(transitive)
    all_items = [*direct, *transitive]
    candidate_command_provenance = [
        {
            "command": command,
            "tests": [
                {
                    "id": item["id"],
                    "label": item["label"],
                    "covers": item["covers"],
                    "root_paths": item["root_paths"],
                }
                for item in all_items
                if _test_command(
                    str(item["path"]),
                    graph.nodes[str(item["id"])].source,
                    inline_test=not _is_test_path(str(item["path"])),
                    test_label=str(item.get("label", "")),
                ) == command
            ],
        }
        for command in dict.fromkeys((*direct_commands, *transitive_commands))
    ]
    aggregate_inline_commands: dict[str, list[dict[str, object]]] = {}
    for item in all_items:
        item_id = str(item["id"])
        node = graph.nodes[item_id]
        path = str(item["path"])
        if _is_test_path(path) or not path.replace("\\", "/").endswith(".rs"):
            continue
        command = _cargo_inline_rust_module_command(node.source)
        if command:
            aggregate_inline_commands.setdefault(command, []).append(item)
    existing_commands = {
        str(entry["command"])
        for entry in candidate_command_provenance
    }
    for command, items in aggregate_inline_commands.items():
        unique_items = list({
            str(item["id"]): item
            for item in items
        }.values())
        if len(unique_items) < 2 or command in existing_commands:
            continue
        candidate_command_provenance.append({
            "command": command,
            "selection_scope": "inline_test_module",
            "tests": [
                {
                    "id": item["id"],
                    "label": item["label"],
                    "covers": item["covers"],
                    "root_paths": item["root_paths"],
                }
                for item in unique_items
            ],
        })
        existing_commands.add(command)
    root_ids = set(starts)
    uncovered = set(root_ids)
    command_budget = max(1, math.ceil(math.log2(len(root_ids) + 1)))
    selected_command_provenance: list[dict[str, object]] = []
    remaining = list(candidate_command_provenance)

    def command_covered_roots(entry: dict[str, object]) -> set[str]:
        return {
            str(root.get("id", ""))
            for test in entry.get("tests", [])
            for root in test.get("covers", [])
        } | {
            str(path.get("root", {}).get("id", ""))
            for test in entry.get("tests", [])
            for path in test.get("root_paths", [])
        }

    def command_rank(
        pair: tuple[int, dict[str, object]],
    ) -> tuple[int, int, int]:
        index, entry = pair
        covered = command_covered_roots(entry) & uncovered
        test_count = len(entry.get("tests", []))
        # A narrow command wins when it covers the whole remaining contract.
        # Otherwise, prefer the broader test scope after root coverage so one
        # valid test cannot hide additional direct cases.
        scope_rank = (
            -test_count
            if cover_all_direct_tests and len(covered) == len(uncovered)
            else test_count
            if len(covered) == len(uncovered)
            else -test_count
        )
        return -len(covered), scope_rank, index

    while remaining and uncovered and len(selected_command_provenance) < command_budget:
        ranked = sorted(
            enumerate(remaining),
            key=command_rank,
        )
        index, winner = ranked[0]
        covered = command_covered_roots(winner) & uncovered
        if not covered:
            break
        selected_command_provenance.append(winner)
        uncovered -= covered
        remaining.pop(index)
    if not selected_command_provenance and candidate_command_provenance:
        selected_command_provenance.append(candidate_command_provenance[0])
        uncovered -= command_covered_roots(candidate_command_provenance[0])
    structurally_uncovered = set(uncovered)
    execution_scope_covered: set[str] = set()
    for entry in selected_command_provenance:
        if entry.get("selection_scope") != "inline_test_module":
            continue
        sources = {
            graph.nodes[test_id].source
            for test in entry.get("tests", [])
            if (test_id := str(test.get("id", ""))) in graph.nodes
            and graph.nodes[test_id].source
        }
        for root in structurally_uncovered:
            root_node = graph.nodes.get(root)
            if root_node is not None and any(
                _rust_test_module_calls_symbol(source, root_node.label)
                for source in sources
            ):
                execution_scope_covered.add(root)
    uncovered -= execution_scope_covered
    selected_commands = [
        str(entry["command"])
        for entry in selected_command_provenance
    ]
    direct_ids = {str(item["id"]) for item in direct}
    transitive_ids = {str(item["id"]) for item in transitive}
    selected_test_ids = {
        str(test.get("id", ""))
        for entry in selected_command_provenance
        for test in entry.get("tests", [])
        if test.get("id")
    }
    uncovered_direct_tests = direct_ids - selected_test_ids

    def selected_commands_covering(test_ids: set[str]) -> list[str]:
        return [
            str(entry["command"])
            for entry in selected_command_provenance
            if any(
                str(test.get("id", "")) in test_ids
                for test in entry.get("tests", [])
            )
        ]

    return {
        "direct": direct,
        "transitive": transitive,
        "commands": selected_commands,
        "commands_by_role": {
            "direct_behavior_or_contract": selected_commands_covering(direct_ids),
            "transitive_regression": selected_commands_covering(transitive_ids),
        },
        "command_provenance": selected_command_provenance,
        "command_selection": {
            "algorithm": (
                "greedy_root_cover_v3_all_direct_tests"
                if cover_all_direct_tests
                else "greedy_root_cover_v3_narrow"
            ),
            "candidate_count": len(candidate_command_provenance),
            "selected_count": len(selected_commands),
            "root_count": len(root_ids),
            "covered_roots": sorted(root_ids - uncovered),
            "uncovered_roots": sorted(uncovered),
            "structurally_uncovered_roots": sorted(structurally_uncovered),
            "execution_scope_covered_roots": sorted(execution_scope_covered),
            "covered_direct_tests": sorted(direct_ids & selected_test_ids),
            "uncovered_direct_tests": sorted(uncovered_direct_tests),
        },
        "omitted_direct": omitted_direct,
        "omitted_transitive": omitted_transitive,
    }

def reconcile_semantic_retrieval_receipt(
    graph: Graph,
    result: RetrievalResult,
    *,
    route: object,
    automatic_route: bool,
) -> tuple[str, ...]:
    """Type-check and calibrate the agent-facing retrieval receipt."""
    metadata = result.metadata
    answerability = dict(metadata.get("answerability", {}))
    status = str(answerability.get("status", "unknown"))
    abstained = bool(answerability.get("abstained", False))
    original_reason = str(answerability.get("reason", "")).strip()
    repaired_facets = reconcile_affected_output_facets(metadata)
    reasons = [original_reason]

    facet_coverage = metadata.get("facet_coverage", {})
    structural_coverage = metadata.get("structural_facet_coverage", {})
    unfulfilled = [
        *(
            str(item)
            for item in (
                facet_coverage.get("unfulfilled", ())
                if isinstance(facet_coverage, dict)
                else ()
            )
        ),
        *(
            str(item)
            for item in (
                structural_coverage.get("unfulfilled", ())
                if isinstance(structural_coverage, dict)
                else ()
            )
        ),
    ]
    if (
        repaired_facets
        and not unfulfilled
        and status == "incomplete"
        and original_reason == "unfulfilled query facets"
    ):
        status = "answerable"
        abstained = False
        reasons = []
    if unfulfilled:
        if status != "unanswerable":
            status = "incomplete"
        abstained = True
        reasons.append("unfulfilled requested facets: " + ", ".join(dict.fromkeys(unfulfilled)))

    query_class = str(getattr(route, "query_class", ""))
    route_confidence = float(getattr(route, "confidence", 1.0))
    if automatic_route and route_confidence < 0.25:
        status = "incomplete"
        abstained = True
        reasons.append(f"automatic routing confidence is low ({route_confidence:.3f})")
        metadata["routing_recovery"] = {
            "strategy": "calibrated_abstention",
            "confidence": route_confidence,
            "suggestions": [
                "add an exact symbol or path",
                f"retry with an explicit query_class instead of {query_class or 'auto'}",
                "split compound requests into one bounded facet per query",
            ],
        }

    affected = metadata.get("affected_tests")
    if query_class == "affected_tests" and isinstance(affected, dict):
        recommendations = [
            *affected.get("direct", ()),
            *affected.get("transitive", ()),
        ]
        commands = [str(item) for item in affected.get("commands", ())]
        affected["evidence_status"] = (
            "attributed"
            if recommendations
            else ("candidate_only" if commands else "no_evidence")
        )
        if not recommendations:
            status = "incomplete"
            abstained = True
            reasons.append("no affected-test evidence was found")
        omitted_direct = int(affected.get("omitted_direct", 0) or 0)
        omitted_transitive = int(affected.get("omitted_transitive", 0) or 0)
        if omitted_direct or omitted_transitive:
            status = "incomplete"
            abstained = True
            reasons.append(
                "affected-test recommendation cap omitted "
                f"{omitted_direct} direct and {omitted_transitive} transitive candidate(s)"
            )

    quality = metadata.get("quality", {})
    document_warning = str(quality.get("document_warning", "")) if isinstance(quality, dict) else ""
    if document_warning:
        if status != "unanswerable":
            status = "incomplete"
        abstained = True
        reasons.append(document_warning)

    answerability = {
        "status": status,
        "abstained": abstained,
        "reason": "; ".join(dict.fromkeys(reason for reason in reasons if reason)),
    }
    metadata["answerability"] = answerability

    errors: list[str] = []
    if status == "answerable" and unfulfilled:
        errors.append("answerable receipt has unfulfilled facets")
    if status in {"incomplete", "unanswerable"} and not abstained:
        errors.append(f"{status} receipt must set abstained=true")
    if document_warning and status == "answerable":
        errors.append("document warning cannot coexist with answerable status")

    if query_class == "affected_tests" and isinstance(affected, dict):
        recommended_ids = {
            str(item.get("id"))
            for role in ("direct", "transitive")
            for item in affected.get(role, ())
            if isinstance(item, dict) and item.get("id")
        }
        packet_direct_tests = {
            edge.source
            for edge in graph.edges
            if edge.active
            and edge.type in {"calls", "references", "tests"}
            and edge.source in result.nodes
            and edge.target in result.starts
            and edge.source in graph.nodes
            and _is_test_node(graph.nodes[edge.source])
        }
        missing = sorted(packet_direct_tests - recommended_ids)
        if missing:
            errors.append(
                "packet contains direct test evidence omitted from affected_tests: "
                + ", ".join(missing)
            )
        commands = [str(item) for item in affected.get("commands", ())]
        if commands and not recommended_ids:
            errors.append(
                "affected-test commands were emitted without attributed direct or "
                "transitive test evidence"
            )
        provenance_commands = {
            str(item.get("command"))
            for item in affected.get("command_provenance", ())
            if isinstance(item, dict) and item.get("command")
        }
        missing_provenance = sorted(set(commands) - provenance_commands)
        if missing_provenance:
            errors.append(
                "affected-test commands lack provenance: " + ", ".join(missing_provenance)
            )
        remaining_output_facets: list[str] = []
        for raw_label in (
            facet_coverage.get("unfulfilled", ())
            if isinstance(facet_coverage, dict)
            else ()
        ):
            label = str(raw_label)
            terms = set(term_key(label).split())
            if not terms or terms - _AFFECTED_OUTPUT_TERMS:
                continue
            selection = affected.get("command_selection", {})
            requires_all_direct = bool(
                {"all", "direct", "test"} <= terms
                or {"all", "direct", "tests"} <= terms
            )
            command_contract_met = bool(commands) and (
                not requires_all_direct
                or not isinstance(selection, dict)
                or not selection.get("uncovered_direct_tests", ())
            )
            contradicted = (
                (
                    bool(terms & {"cargo", "command", "commands", "runnable", "run", "runs"})
                    and command_contract_met
                )
                or ("direct" in terms and bool(affected.get("direct")))
                or ("transitive" in terms and bool(affected.get("transitive")))
                or (
                    bool(terms & {"affected", "behavioral", "test", "tests"})
                    and bool(recommended_ids)
                )
            )
            if contradicted:
                remaining_output_facets.append(label)
        if remaining_output_facets:
            errors.append(
                "affected-test evidence contradicts unfulfilled output facets: "
                + ", ".join(remaining_output_facets)
            )

    metadata["semantic_validation"] = {
        "ok": not errors,
        "status": "semantic_pass" if not errors else "semantic_fail",
        "scope": "packet_receipt_consistency",
        "evidence_status": (
            affected.get("evidence_status")
            if query_class == "affected_tests" and isinstance(affected, dict)
            else "not_applicable"
        ),
        "errors": errors,
    }
    return tuple(errors)

# Compatibility name for callers that adopted the first public spelling.
reconcile_retrieval_receipt = reconcile_semantic_retrieval_receipt

def reserve_affected_test_evidence(
    graph: Graph,
    nodes: set[str],
    edges: list[Edge],
    starts: tuple[str, ...],
    plan: ContextPlan,
    *,
    direct_limit: int = 8,
) -> tuple[set[str], list[Edge]]:
    """Keep strongest direct test assertions in the rendered packet."""
    recommendations = affected_test_recommendations(graph, starts, nodes)
    direct_ids = [
        str(item["id"])
        for item in recommendations["direct"][:direct_limit]
        if str(item["id"]) in graph.nodes
    ]
    if not direct_ids:
        return nodes, edges

    secondary_ids = {
        str(item["id"])
        for item in recommendations["transitive"][:6]
        if str(item["id"]) in graph.nodes
    }
    retained_tests = set(direct_ids) | secondary_ids | set(starts)
    out_nodes = {
        node_id
        for node_id in nodes
        if not _is_test_node(graph.nodes[node_id]) or node_id in retained_tests
    }
    protected = set(starts) | set(direct_ids)
    for node_id in direct_ids:
        if node_id in out_nodes:
            continue
        if plan.node_budget is not None and len(out_nodes) >= plan.node_budget:
            removable = _least_valuable_context_node(graph, out_nodes, protected=protected)
            if removable is None:
                continue
            out_nodes.remove(removable)
        out_nodes.add(node_id)

    edge_by_key = {
        (edge.source, edge.target, edge.type): edge
        for edge in edges
        if edge.source in out_nodes and edge.target in out_nodes
    }
    direct_set = set(direct_ids)
    for edge in graph.edges:
        if not edge.active or edge.source not in direct_set:
            continue
        if edge.target not in out_nodes or edge.type not in {"calls", "references", "tests"}:
            continue
        edge_by_key.setdefault((edge.source, edge.target, edge.type), edge)
    return out_nodes, list(edge_by_key.values())
