"""Deterministic, source-grounded project orientation atlas."""

from __future__ import annotations

import json
import time
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath

from ..graph.core import Graph, Node
from ..io import find_graph_path, load_any, project_root_for_graph
from ..packets.validation import validate_graph_object
from ..retrieval.subsystems import build_subsystem_map, subsystem_for_path
from .freshness import inspect_saved_graph_freshness
from .runtime_probes import _read_package_status

ATLAS_SCHEMA = "project_atlas_v1"
DEFAULT_ATLAS_EVIDENCE_BUDGET_CHARS = 8_000

_LANGUAGE_KINDS = frozenset({
    "c", "cpp", "csharp", "go", "haskell", "header", "java", "javascript",
    "jsx", "kotlin", "lean", "lua", "php", "python", "ruby", "rust",
    "scala", "swift", "tsx", "typescript",
})
_CODE_KINDS = frozenset({
    "class", "enum", "function", "interface", "method", "struct", "trait", "type",
})
_COUPLING_EDGE_TYPES = frozenset({
    "calls", "depends_on", "extends", "implements", "imports", "imports_from",
    "references", "uses", "uses_type",
})
_TEST_PARTS = frozenset({"spec", "specs", "test", "tests"})


def _absent(directory: Path, status: str, message: str) -> dict[str, object]:
    return {
        "schema": ATLAS_SCHEMA,
        "status": status,
        "directory": str(directory),
        "message": message,
        "next_action": "build_graph" if status == "no_graph" else "specify_graph_path",
    }


def _language_inventory(graph: Graph) -> list[dict[str, object]]:
    paths: dict[str, set[str]] = defaultdict(set)
    for node in graph.nodes.values():
        if (
            node.active
            and node.path
            and node.kind in _LANGUAGE_KINDS
            and subsystem_for_path(node.path) is not None
        ):
            paths[node.kind].add(node.path.replace("\\", "/"))
    return [
        {"language": language, "files": len(language_paths)}
        for language, language_paths in sorted(
            paths.items(), key=lambda item: (-len(item[1]), item[0])
        )
    ]


def _subsystem_nodes(graph: Graph) -> dict[str, list[Node]]:
    groups: dict[str, list[Node]] = defaultdict(list)
    for node in graph.nodes.values():
        subsystem = subsystem_for_path(node.path)
        if node.active and node.kind in _CODE_KINDS and subsystem not in {None, "root"}:
            groups[subsystem].append(node)
    return groups


def _subsystem_atlas(
    graph: Graph,
    *,
    max_subsystems: int,
    representatives_per_subsystem: int,
) -> tuple[list[dict[str, object]], int, set[str]]:
    compact = build_subsystem_map(
        graph,
        max_subsystems=max_subsystems,
        representatives_per_subsystem=representatives_per_subsystem,
    )
    groups = _subsystem_nodes(graph)
    ranks = graph.pagerank() if groups else {}
    rows: list[dict[str, object]] = []
    selected_names: set[str] = set()
    for item in compact["subsystems"]:
        name = str(item["subsystem"])
        selected_names.add(name)
        nodes = groups.get(name, [])
        roots = Counter(
            str(PurePosixPath(node.path.replace("\\", "/")).parent)
            for node in nodes
            if node.path
        )
        representatives: list[dict[str, object]] = []
        used: set[str] = set()
        for label in item["api"]:
            candidates = sorted(
                (node for node in nodes if node.label == label and node.id not in used),
                key=lambda node: (-ranks.get(node.id, 0.0), node.path, node.id),
            )
            if not candidates:
                continue
            node = candidates[0]
            used.add(node.id)
            evidence: dict[str, object] = {
                "id": node.id,
                "label": node.label,
                "kind": node.kind,
                "path": node.path,
            }
            if node.line is not None:
                evidence["line"] = node.line
            representatives.append(evidence)
        rows.append({
            "name": name,
            "symbols": int(item["n"]),
            "roots": [root for root, _ in roots.most_common(3)],
            "representatives": representatives,
        })
    return rows, int(compact["omitted"]), selected_names


def _coupling_atlas(
    graph: Graph,
    selected_names: set[str],
    *,
    max_couplings: int,
) -> tuple[list[dict[str, object]], int]:
    pairs: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    evidence: dict[tuple[str, str], dict[str, object]] = {}
    for edge in graph.edges:
        if not edge.active or edge.type not in _COUPLING_EDGE_TYPES:
            continue
        source = graph.nodes.get(edge.source)
        target = graph.nodes.get(edge.target)
        if source is None or target is None:
            continue
        source_subsystem = subsystem_for_path(source.path)
        target_subsystem = subsystem_for_path(target.path)
        if (
            source_subsystem not in selected_names
            or target_subsystem not in selected_names
            or source_subsystem == target_subsystem
        ):
            continue
        key = (source_subsystem, target_subsystem)
        pairs[key][edge.type] += 1
        candidate = {
            "source": {"label": source.label, "path": source.path},
            "target": {"label": target.label, "path": target.path},
            "relation": edge.type,
        }
        if key not in evidence or str(candidate) < str(evidence[key]):
            evidence[key] = candidate

    ranked = sorted(
        pairs.items(),
        key=lambda item: (-sum(item[1].values()), item[0][0], item[0][1]),
    )
    rows = [
        {
            "from": source,
            "to": target,
            "edges": sum(types.values()),
            "relations": dict(sorted(types.items(), key=lambda item: (-item[1], item[0]))),
            "evidence": evidence[(source, target)],
        }
        for (source, target), types in ranked[:max_couplings]
    ]
    return rows, max(0, len(ranked) - max_couplings)


def _compact_chars(value: object) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")))


def _budgeted_atlas_selection(
    subsystems: list[dict[str, object]],
    couplings: list[dict[str, object]],
    *,
    base_payload: dict[str, object],
    evidence_budget_chars: int,
) -> tuple[list[dict[str, object]], list[dict[str, object]], dict[str, object]]:
    """Greedy maximum-coverage selection with coupling prerequisites.

    Subsystem utility is its exact share of indexed production symbols;
    coupling utility is its exact share of cross-subsystem typed edges. A
    coupling candidate pays for any endpoint subsystem not selected yet. This
    replaces fixed row counts with a deterministic marginal-coverage/character
    optimization under an explicit resource budget.
    """

    base_chars = _compact_chars(base_payload)
    remaining = max(0, evidence_budget_chars - base_chars)
    subsystem_by_name = {str(row["name"]): row for row in subsystems}
    subsystem_order = {str(row["name"]): index for index, row in enumerate(subsystems)}
    coupling_order = {
        (str(row["from"]), str(row["to"])): index for index, row in enumerate(couplings)
    }
    total_symbols = max(1, sum(int(row["symbols"]) for row in subsystems))
    total_edges = max(1, sum(int(row["edges"]) for row in couplings))
    subsystem_utility = {
        name: int(row["symbols"]) / total_symbols for name, row in subsystem_by_name.items()
    }
    subsystem_cost = {
        name: _compact_chars(row) + 1 for name, row in subsystem_by_name.items()
    }
    coupling_cost = {
        (str(row["from"]), str(row["to"])): _compact_chars(row) + 1
        for row in couplings
    }
    selected_subsystems: set[str] = set()
    selected_couplings: set[tuple[str, str]] = set()
    spent = 0

    while True:
        choices: list[tuple[float, float, str, object, int, tuple[str, ...]]] = []
        for name, row in subsystem_by_name.items():
            if name in selected_subsystems:
                continue
            cost = subsystem_cost[name]
            gain = subsystem_utility[name]
            choices.append((gain / cost, gain, "subsystem", name, cost, (name,)))
        for row in couplings:
            key = (str(row["from"]), str(row["to"]))
            if key in selected_couplings:
                continue
            missing = tuple(name for name in key if name not in selected_subsystems)
            if any(name not in subsystem_by_name for name in missing):
                continue
            cost = coupling_cost[key] + sum(subsystem_cost[name] for name in missing)
            gain = int(row["edges"]) / total_edges + sum(
                subsystem_utility[name] for name in missing
            )
            choices.append((gain / cost, gain, "coupling", key, cost, missing))
        if not choices:
            break
        choices.sort(key=lambda item: (-item[0], -item[1], item[2], str(item[3])))
        chosen = next((choice for choice in choices if choice[4] <= remaining - spent), None)
        if chosen is None:
            break
        _, _, kind, identity, cost, missing = chosen
        selected_subsystems.update(missing)
        if kind == "subsystem":
            selected_subsystems.add(str(identity))
        else:
            if not isinstance(identity, tuple):  # Defensive: choices above emit tuple keys.
                raise RuntimeError("invalid coupling selection identity")
            selected_couplings.add(identity)
        spent += cost

    subsystem_rows = sorted(
        (subsystem_by_name[name] for name in selected_subsystems),
        key=lambda row: subsystem_order[str(row["name"])],
    )
    coupling_rows = sorted(
        (
            row for row in couplings
            if (str(row["from"]), str(row["to"])) in selected_couplings
        ),
        key=lambda row: coupling_order[(str(row["from"]), str(row["to"]))],
    )
    evidence_chars = _compact_chars({
        **base_payload,
        "subsystems": subsystem_rows,
        "couplings": coupling_rows,
    })
    return subsystem_rows, coupling_rows, {
        "algorithm": "prerequisite_marginal_coverage_per_character_v1",
        "budget_chars": evidence_budget_chars,
        "base_chars": base_chars,
        "evidence_chars": evidence_chars,
        "binding": "base_payload" if base_chars > evidence_budget_chars else (
            "evidence_budget" if len(subsystem_rows) < len(subsystems) or len(coupling_rows) < len(couplings) else "none"
        ),
    }


def _entry_points(package: dict[str, object], graph: Graph) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    scripts = package.get("scripts") or {}
    manifest = str(package.get("pyproject") or package.get("package_json") or "")
    if isinstance(scripts, dict):
        for name, target in sorted(scripts.items()):
            rows.append({
                "name": str(name),
                "target": str(target),
                "kind": "manifest_script",
                "evidence": manifest,
            })
    javascript = package.get("javascript") or {}
    if isinstance(javascript, dict) and javascript.get("main"):
        rows.append({
            "name": "main",
            "target": str(javascript["main"]),
            "kind": "package_main",
            "evidence": str(package.get("package_json") or "package.json"),
        })
    known_targets = {str(row["target"]).replace("\\", "/") for row in rows}
    for node in sorted(graph.nodes.values(), key=lambda item: (item.path, item.id)):
        path = node.path.replace("\\", "/")
        if not node.active or path in known_targets:
            continue
        if path.endswith("/src/main.rs") or path == "src/main.rs":
            rows.append({"name": PurePosixPath(path).parent.parent.name or "main", "target": path,
                         "kind": "rust_binary", "evidence": path})
            known_targets.add(path)
        elif path.endswith(".go") and node.kind == "function" and node.label == "main":
            # Go has no fixed binary-entry path (unlike Rust's src/main.rs), so
            # the reliable signal is the symbol itself: a package-level `main`
            # function is exactly what `go build`/`go run` requires.
            rows.append({
                "name": PurePosixPath(path).parent.name or "main", "target": path,
                "kind": "go_binary", "evidence": path,
            })
            known_targets.add(path)
    return rows


def _test_surfaces(package: dict[str, object], graph: Graph) -> dict[str, object]:
    test_files: set[str] = set()
    roots: Counter[str] = Counter()
    for node in graph.nodes.values():
        path = node.path.replace("\\", "/")
        if not node.active or not path:
            continue
        parts = PurePosixPath(path).parts
        filename = parts[-1].casefold()
        test_index = next((i for i, part in enumerate(parts[:-1]) if part.casefold() in _TEST_PARTS), None)
        is_test = test_index is not None or filename.startswith("test_") or filename.endswith(
            ("_test.py", ".test.js", ".test.ts", "_test.go")
        )
        if not is_test:
            continue
        test_files.add(path)
        if test_index is not None:
            roots["/".join(parts[: test_index + 1])] += 1
        else:
            roots[str(PurePosixPath(path).parent)] += 1

    commands: list[dict[str, str]] = []
    scripts = package.get("scripts") or {}
    if isinstance(scripts, dict) and "test" in scripts:
        commands.append({"command": "npm test", "basis": "package.json scripts.test", "confidence": "exact"})
    ecosystems = set(str(item) for item in package.get("ecosystems", []))
    if "rust" in ecosystems:
        rust = package.get("rust") or {}
        workspace = isinstance(rust, dict) and rust.get("kind") == "workspace"
        commands.append({
            "command": "cargo test --workspace" if workspace else "cargo test",
            "basis": "Cargo.toml workspace" if workspace else "Cargo.toml package",
            "confidence": "manifest_default",
        })
    if "python" in ecosystems and test_files:
        commands.append({
            "command": "python -m pytest",
            "basis": "Python package with indexed test files",
            "confidence": "candidate",
        })
    if "go" in ecosystems:
        commands.append({
            "command": "go test ./...",
            "basis": "go.mod module",
            "confidence": "manifest_default",
        })
    return {
        "files": len(test_files),
        "roots": [{"path": path, "files": count} for path, count in roots.most_common(10)],
        "commands": commands,
    }


def _coverage(graph: Graph, validation: object, freshness: dict[str, object]) -> dict[str, object]:
    files_truncated = graph.metadata.get("files_truncated") == "true"
    symbols_truncated = graph.metadata.get("symbols_truncated") == "true"
    docs_truncated = int(graph.metadata.get("docs_truncated_count", "0") or 0)
    limitations: list[str] = []
    if files_truncated:
        limitations.append("file collection was truncated")
    if symbols_truncated:
        limitations.append("symbol extraction was truncated")
    if docs_truncated:
        limitations.append(f"{docs_truncated} document(s) were truncated")
    if freshness.get("fresh") is False:
        limitations.append("saved graph is stale relative to the worktree")
    return {
        "validation": {
            "ok": bool(getattr(validation, "ok", False)),
            "format": str(getattr(validation, "format", "unknown")),
        },
        "freshness": freshness,
        "scan": {
            "depth": graph.metadata.get("scan_depth", "unknown"),
            "frontend": graph.metadata.get("frontend", "unknown"),
            "files_truncated": files_truncated,
            "files_scanned": int(graph.metadata.get("files_scanned", "0") or 0),
            "files_total_matched": int(graph.metadata.get("files_total_matched", "0") or 0),
            "symbols_truncated": symbols_truncated,
            "symbols_cap": int(graph.metadata.get("symbols_cap", "0") or 0),
            "docs_truncated": docs_truncated,
        },
        "exclusions": {
            "ignore_rule_files": [item for item in graph.metadata.get("ignore_rule_files", "").split(",") if item],
            "ignored_directories": [item for item in graph.metadata.get("ignore_pruned_dirs", "").split(",") if item],
            "default_pruned_directories": [item for item in graph.metadata.get("default_pruned_dirs", "").split(",") if item],
            "ignored_directory_count": int(graph.metadata.get("ignore_pruned_dir_count", "0") or 0),
            "default_pruned_directory_count": int(graph.metadata.get("default_pruned_dir_count", "0") or 0),
        },
        "limitations": limitations,
    }


def build_project_atlas(
    *,
    directory: Path = Path("."),
    graph_path: Path | None = None,
    max_subsystems: int | None = None,
    representatives_per_subsystem: int = 1,
    max_couplings: int | None = None,
    evidence_budget_chars: int = DEFAULT_ATLAS_EVIDENCE_BUDGET_CHARS,
) -> dict[str, object]:
    """Build a compact project system card and dependency atlas from saved evidence."""

    started = time.perf_counter()
    directory = directory.resolve()
    if (
        (max_subsystems is not None and max_subsystems < 1)
        or representatives_per_subsystem < 1
        or (max_couplings is not None and max_couplings < 0)
        or evidence_budget_chars < 1
    ):
        raise ValueError(
            "atlas limits require max_subsystems>=1, representatives>=1, "
            "max_couplings>=0, evidence_budget_chars>=1"
        )
    if graph_path is not None:
        resolved_graph_path = graph_path.resolve()
        if not resolved_graph_path.exists():
            return _absent(directory, "no_graph", f"No graph at {resolved_graph_path}. Build one first.")
    else:
        try:
            resolved_graph_path = find_graph_path(directory)
        except FileNotFoundError:
            return _absent(directory, "no_graph", "No native GraphGraph file found. Build one first.")
        except RuntimeError as exc:
            return _absent(directory, "ambiguous_graph", str(exc))

    load_started = time.perf_counter()
    graph = load_any(resolved_graph_path)
    load_ms = (time.perf_counter() - load_started) * 1000.0
    validate_started = time.perf_counter()
    validation = validate_graph_object(graph, format_name=f"graph{resolved_graph_path.suffix or '_file'}")
    validate_ms = (time.perf_counter() - validate_started) * 1000.0
    metadata_started = time.perf_counter()
    package = _read_package_status(directory)
    try:
        freshness = inspect_saved_graph_freshness(
            directory=project_root_for_graph(resolved_graph_path),
            output_path=resolved_graph_path,
        )
    except Exception:  # noqa: BLE001 - orientation must survive unavailable Git state.
        freshness = {"fresh": None}
    metadata_ms = (time.perf_counter() - metadata_started) * 1000.0

    atlas_started = time.perf_counter()
    all_subsystems, _, all_names = _subsystem_atlas(
        graph,
        max_subsystems=max(1, len(graph.nodes)),
        representatives_per_subsystem=representatives_per_subsystem,
    )
    all_couplings, _ = _coupling_atlas(
        graph,
        all_names,
        max_couplings=max(1, len(graph.edges)),
    )
    candidate_subsystems = all_subsystems[:max_subsystems] if max_subsystems is not None else all_subsystems
    candidate_names = {str(row["name"]) for row in candidate_subsystems}
    candidate_couplings = [
        row for row in all_couplings
        if str(row["from"]) in candidate_names and str(row["to"]) in candidate_names
    ]
    if max_couplings is not None:
        candidate_couplings = candidate_couplings[:max_couplings]
    languages = _language_inventory(graph)
    entry_points = _entry_points(package, graph)
    tests = _test_surfaces(package, graph)
    coverage = _coverage(graph, validation, freshness)
    project = {
        "root": str(directory),
        "name": str(package.get("name") or directory.name),
        "version": str(package.get("version") or ""),
        "ecosystems": list(package.get("ecosystems") or []),
        "graph": str(resolved_graph_path),
    }
    base_payload = {
        "schema": ATLAS_SCHEMA,
        "status": "ready",
        "project": project,
        "languages": languages,
        "entry_points": entry_points,
        "subsystems": [],
        "couplings": [],
        "tests": tests,
        "coverage": coverage,
    }
    subsystems, couplings, selection_receipt = _budgeted_atlas_selection(
        candidate_subsystems,
        candidate_couplings,
        base_payload=base_payload,
        evidence_budget_chars=evidence_budget_chars,
    )
    atlas_ms = (time.perf_counter() - atlas_started) * 1000.0
    total_ms = (time.perf_counter() - started) * 1000.0
    return {
        "schema": ATLAS_SCHEMA,
        "status": "ready",
        "project": project,
        "languages": languages,
        "entry_points": entry_points,
        "subsystems": subsystems,
        "couplings": couplings,
        "tests": tests,
        "coverage": coverage,
        "receipt": {
            "method": "manifest+source_path+pagerank+typed_edges+budgeted_coverage",
            "nodes_considered": len(graph.nodes),
            "edges_considered": len(graph.edges),
            "candidate_subsystems": len(candidate_subsystems),
            "candidate_couplings": len(candidate_couplings),
            "omitted_subsystems": len(all_subsystems) - len(subsystems),
            "omitted_couplings": len(all_couplings) - len(couplings),
            "representatives_per_subsystem": representatives_per_subsystem,
            "selection": selection_receipt,
            "timings_ms": {
                "load": round(load_ms, 3),
                "validate": round(validate_ms, 3),
                "metadata": round(metadata_ms, 3),
                "atlas": round(atlas_ms, 3),
                "total": round(total_ms, 3),
            },
        },
    }


__all__ = [
    "ATLAS_SCHEMA",
    "DEFAULT_ATLAS_EVIDENCE_BUDGET_CHARS",
    "build_project_atlas",
]
