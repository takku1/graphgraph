from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised on Python 3.10.
    import tomli as tomllib

from ..graph.core import Graph
from ..io import find_graph_path, load_any, save_validated_graph, validate_graph_file
from ..packets.validation import ValidationResult
from ..scanner import remove_paths, scan_directory, update_paths
from .context import render_query_context


@dataclass(frozen=True)
class GraphBuildStatus:
    path: Path
    graph: Graph
    built: bool
    repaired: bool = False
    validation: ValidationResult | None = None


def scan_validated_graph(
    *,
    directory: Path,
    output_path: Path,
    max_nodes: int = 5000,
    depth: str = "symbols",
    frontend: str = "auto",
    docs: bool = True,
    history: bool = False,
    skip_dirs: tuple[str, ...] = (),
    include_dirs: tuple[str, ...] = (),
    generic_mentions: bool = False,
    incremental: bool = True,
) -> GraphBuildStatus:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    use_incremental = incremental
    previous_graph_path = output_path if use_incremental else None
    manifest_path = (output_path.parent / "manifest.json") if use_incremental else None

    graph = scan_directory(
        directory,
        max_nodes=max_nodes,
        generic_mentions=generic_mentions,
        skip_dirs=list(skip_dirs),
        include=list(include_dirs),
        depth=depth,
        frontend=frontend,
        docs=docs,
        history=history,
        previous_graph_path=previous_graph_path,
        manifest_path=manifest_path,
    )
    try:
        validation = save_validated_graph(graph, output_path)
        return GraphBuildStatus(output_path, graph, built=True, repaired=False, validation=validation)
    except ValueError:
        if not incremental:
            raise

    graph = scan_directory(
        directory,
        max_nodes=max_nodes,
        generic_mentions=generic_mentions,
        skip_dirs=list(skip_dirs),
        include=list(include_dirs),
        depth=depth,
        frontend=frontend,
        docs=docs,
        history=history,
        previous_graph_path=None,
        manifest_path=output_path.parent / "manifest.json",
    )
    validation = save_validated_graph(graph, output_path)
    return GraphBuildStatus(output_path, graph, built=True, repaired=True, validation=validation)


def _full_rescan_fallback(
    *,
    directory: Path,
    output_path: Path,
    max_nodes: int,
    depth: str,
    frontend: str,
    docs: bool,
    history: bool,
) -> GraphBuildStatus:
    """Repair path shared by update/remove: promote to a clean full rebuild.

    Mirrors ``scan_validated_graph``'s own incremental-then-repair fallback --
    if the targeted operation produced an invalid graph (e.g. the manifest
    was stale relative to disk), a full non-incremental scan is the safety
    net, same as it is for the ordinary incremental scan path.
    """
    graph = scan_directory(
        directory,
        max_nodes=max_nodes,
        depth=depth,
        frontend=frontend,
        docs=docs,
        history=history,
        previous_graph_path=None,
        manifest_path=output_path.parent / "manifest.json",
    )
    validation = save_validated_graph(graph, output_path)
    return GraphBuildStatus(output_path, graph, built=True, repaired=True, validation=validation)


def update_paths_validated_graph(
    *,
    directory: Path,
    output_path: Path,
    paths: list[str],
    max_nodes: int = 5000,
    depth: str = "symbols",
    frontend: str = "auto",
    docs: bool = False,
    history: bool = False,
) -> GraphBuildStatus:
    """Re-extract exactly *paths* and splice into the existing graph.

    Requires a prior ``scan_validated_graph``/``graphgraph scan`` run (needs
    an existing graph + manifest at *output_path*). Falls back to a full
    rebuild if that's missing or the result fails validation.
    """
    manifest_path = output_path.parent / "manifest.json"
    try:
        graph = update_paths(
            directory,
            paths,
            max_nodes=max_nodes,
            depth=depth,
            frontend=frontend,
            docs=docs,
            history=history,
            previous_graph_path=output_path,
            manifest_path=manifest_path,
        )
        validation = save_validated_graph(graph, output_path)
        return GraphBuildStatus(output_path, graph, built=True, repaired=False, validation=validation)
    except ValueError:
        return _full_rescan_fallback(
            directory=directory, output_path=output_path, max_nodes=max_nodes,
            depth=depth, frontend=frontend, docs=docs, history=history,
        )


def remove_paths_validated_graph(
    *,
    directory: Path,
    output_path: Path,
    paths: list[str],
    max_nodes: int = 5000,
    depth: str = "symbols",
    frontend: str = "auto",
    docs: bool = False,
    history: bool = False,
) -> GraphBuildStatus:
    """Drop *paths* (deleted/renamed-away files) from the existing graph.

    Requires a prior ``scan_validated_graph``/``graphgraph scan`` run. Falls
    back to a full rebuild if that's missing or the result fails validation.
    """
    manifest_path = output_path.parent / "manifest.json"
    try:
        graph = remove_paths(
            directory,
            paths,
            max_nodes=max_nodes,
            depth=depth,
            frontend=frontend,
            docs=docs,
            history=history,
            previous_graph_path=output_path,
            manifest_path=manifest_path,
        )
        validation = save_validated_graph(graph, output_path)
        return GraphBuildStatus(output_path, graph, built=True, repaired=False, validation=validation)
    except ValueError:
        return _full_rescan_fallback(
            directory=directory, output_path=output_path, max_nodes=max_nodes,
            depth=depth, frontend=frontend, docs=docs, history=history,
        )


def ensure_native_graph(
    *,
    directory: Path = Path("."),
    output_path: Path = Path(".graphgraph/graph.gg"),
    rebuild: bool = False,
    max_nodes: int = 5000,
    depth: str = "symbols",
    frontend: str = "auto",
    docs: bool = True,
    history: bool = False,
    skip_dirs: tuple[str, ...] = (),
    include_dirs: tuple[str, ...] = (),
    generic_mentions: bool = False,
    incremental: bool = True,
    discover_existing: bool = True,
) -> GraphBuildStatus:
    """Return an existing native graph, or scan one with production defaults."""
    if not rebuild:
        graph_path = output_path
        try:
            if not graph_path.exists() and discover_existing:
                graph_path = find_graph_path()
            validation = validate_graph_file(graph_path)
            if validation.ok:
                return GraphBuildStatus(graph_path, load_any(graph_path), built=False)
        except FileNotFoundError:
            pass

    return scan_validated_graph(
        directory=directory,
        output_path=output_path,
        max_nodes=max_nodes,
        generic_mentions=generic_mentions,
        skip_dirs=skip_dirs,
        include_dirs=include_dirs,
        depth=depth,
        frontend=frontend,
        docs=docs,
        history=history,
        incremental=incremental and not rebuild,
    )


def graph_shape(graph: Graph) -> dict[str, int]:
    source_kinds = {
        "python", "typescript", "tsx", "javascript", "jsx", "go", "rust",
        "java", "csharp", "cpp", "c", "header", "ruby", "php", "swift",
        "kotlin", "scala", "haskell", "lean", "function", "class",
        "struct", "method", "interface",
    }
    doc_kinds = {"markdown", "rst", "html", "text", "concept", "section"}
    source_nodes = sum(1 for node in graph.nodes.values() if node.kind in source_kinds)
    doc_nodes = sum(1 for node in graph.nodes.values() if node.kind in doc_kinds)
    return {
        "nodes": len(graph.nodes),
        "edges": len(graph.edges),
        "source_nodes": source_nodes,
        "doc_nodes": doc_nodes,
        "other_nodes": len(graph.nodes) - source_nodes - doc_nodes,
    }


def build_project_status(
    *,
    directory: Path = Path("."),
    graph_path: Path | None = None,
    run_probes: bool = False,
) -> dict[str, object]:
    directory = directory.resolve()
    resolved_graph_path = graph_path or find_graph_path(directory)
    validation = validate_graph_file(resolved_graph_path)
    graph = load_any(resolved_graph_path)
    shape = graph_shape(graph)
    kind_counts: dict[str, int] = {}
    for node in graph.nodes.values():
        kind_counts[node.kind] = kind_counts.get(node.kind, 0) + 1

    package = _read_package_status(directory)
    probes = _run_package_probes(directory, package) if run_probes else []
    runtime_notes = _runtime_notes(probes) if run_probes else []
    return {
        "graph": {
            "path": str(resolved_graph_path),
            "validation": {
                "ok": validation.ok,
                "format": validation.format,
                "nodes": validation.node_count,
                "edges": validation.edge_count,
                "errors": list(validation.errors[:10]),
            },
            "shape": shape,
            "top_kinds": dict(sorted(kind_counts.items(), key=lambda item: -item[1])[:10]),
        },
        "package": package,
        "runtime_probes": probes,
        "runtime_notes": runtime_notes,
    }


def _read_package_status(directory: Path) -> dict[str, object]:
    pyproject = directory / "pyproject.toml"
    src_layout = (directory / "src").is_dir()
    package: dict[str, object] = {
        "pyproject": str(pyproject) if pyproject.exists() else "",
        "name": "",
        "version": "",
        "module": "",
        "scripts": {},
        "src_layout": src_layout,
        "import_hint": "Set PYTHONPATH=src or install the package editable before direct python -m probes."
        if src_layout else "",
    }
    if not pyproject.exists():
        return package
    try:
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except Exception as exc:
        package["error"] = f"failed to parse pyproject.toml: {exc}"
        return package

    project = data.get("project") or {}
    if isinstance(project, dict):
        name = str(project.get("name") or "")
        package["name"] = name
        package["version"] = str(project.get("version") or "")
        package["module"] = name.replace("-", "_") if name else ""
        scripts = project.get("scripts") or {}
        if isinstance(scripts, dict):
            package["scripts"] = {str(k): str(v) for k, v in scripts.items()}
    return package


def _run_package_probes(directory: Path, package: dict[str, object]) -> list[dict[str, object]]:
    module = str(package.get("module") or "")
    if not module:
        return []

    probes: list[dict[str, object]] = []
    commands = (
        ("module_help", [sys.executable, "-m", module, "--help"]),
        ("import", [sys.executable, "-c", f"import {module}; print({module}.__file__)"]),
    )
    raw_env = os.environ.copy()
    raw_env.pop("PYTHONPATH", None)
    for name, args in commands:
        probes.append(_run_probe(name=f"raw_{name}", args=args, directory=directory, env=raw_env, env_label="raw"))

    if package.get("src_layout"):
        src_env = os.environ.copy()
        src_path = str(directory / "src")
        existing = src_env.get("PYTHONPATH")
        src_env["PYTHONPATH"] = src_path if not existing else src_path + os.pathsep + existing
        for name, args in commands:
            probes.append(_run_probe(name=f"src_{name}", args=args, directory=directory, env=src_env, env_label="PYTHONPATH=src"))

    scripts = package.get("scripts") or {}
    if isinstance(scripts, dict):
        env = os.environ.copy()
        if package.get("src_layout"):
            env["PYTHONPATH"] = str(directory / "src")
        for script_name, target in sorted(scripts.items()):
            module_name = str(target).split(":", 1)[0].strip()
            if not module_name:
                continue
            probes.append(
                _run_probe(
                    name=f"script_target_import:{script_name}",
                    args=[sys.executable, "-c", f"import {module_name}; print({module_name}.__file__)"],
                    directory=directory,
                    env=env,
                    env_label="PYTHONPATH=src" if package.get("src_layout") else "raw",
                )
            )
    return probes


def _run_probe(
    *,
    name: str,
    args: list[str],
    directory: Path,
    env: dict[str, str],
    env_label: str,
) -> dict[str, object]:
    try:
        proc = subprocess.run(
            args,
            cwd=directory,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=15,
            check=False,
        )
        output = (proc.stdout or "").strip().splitlines()
        return {
            "name": name,
            "env": env_label,
            "command": " ".join(args),
            "ok": proc.returncode == 0,
            "returncode": proc.returncode,
            "output": output[:5],
        }
    except Exception as exc:
        return {"name": name, "env": env_label, "command": " ".join(args), "ok": False, "error": str(exc)}


def _runtime_notes(probes: list[dict[str, object]]) -> list[str]:
    by_name = {str(probe.get("name")): probe for probe in probes}
    notes: list[str] = []
    raw_import = by_name.get("raw_import")
    src_import = by_name.get("src_import")
    if raw_import and src_import and not raw_import.get("ok") and src_import.get("ok"):
        notes.append("Package imports only when PYTHONPATH includes src; install editable or export PYTHONPATH=src.")
    raw_module = by_name.get("raw_module_help")
    src_module = by_name.get("src_module_help")
    if raw_module and src_module and not raw_module.get("ok") and src_module.get("ok"):
        notes.append("python -m module works only with src on PYTHONPATH.")
    for probe in probes:
        name = str(probe.get("name") or "")
        if name.startswith("script_target_import:") and not probe.get("ok"):
            notes.append(f"Console script target import failed: {name.split(':', 1)[1]}.")
    return notes


def render_native_context(
    *,
    query: str,
    query_class: str = "subsystem_summary",
    directory: Path = Path("."),
    graph_path: Path | None = None,
    rebuild: bool = False,
    max_nodes: int | None = None,
    scan_max_nodes: int = 5000,
    packet: str | None = None,
    anchor_limit: int | None = None,
    scopes: tuple[str, ...] = (),
    skip_dirs: tuple[str, ...] = (),
    include_dirs: tuple[str, ...] = (),
    depth: str = "symbols",
    frontend: str = "auto",
    docs: bool = True,
    history: bool = False,
    generic_mentions: bool = False,
    incremental: bool = True,
    show_anchors: bool = False,
) -> tuple[str, GraphBuildStatus]:
    output_path = graph_path or Path(".graphgraph/graph.gg")
    status = ensure_native_graph(
        directory=directory,
        output_path=output_path,
        rebuild=rebuild,
        max_nodes=scan_max_nodes,
        skip_dirs=skip_dirs,
        include_dirs=include_dirs,
        depth=depth,
        frontend=frontend,
        docs=docs,
        history=history,
        generic_mentions=generic_mentions,
        incremental=incremental,
        discover_existing=graph_path is None,
    )
    packet_text = render_query_context(
        query=query,
        query_class=query_class,
        graph_path=status.path,
        packet=packet,
        anchor_limit=anchor_limit,
        max_nodes=max_nodes,
        scopes=scopes,
        show_anchors=show_anchors,
        cache_namespace="cli_context",
    )
    return packet_text, status
