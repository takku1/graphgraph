from __future__ import annotations

from pathlib import Path

import subprocess
from ..core import Edge, Graph, Node
from .doc import DocumentInput, extract_document_context
from .files import DOC_SUFFIXES, EXT_KIND, PARSEABLE_SUFFIXES, collect_files, node_id
from .frontends import SourceFile, select_extractor
from .imports import add_file_edges


def _get_git_metadata(root: Path) -> tuple[set[str], dict[str, int]]:
    dirty_files = set()
    churn_counts = {}
    try:
        res_status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False
        )
        if res_status.returncode == 0:
            for line in res_status.stdout.splitlines():
                if len(line) > 3:
                    path_part = line[3:].strip()
                    if " -> " in path_part:
                        path_part = path_part.split(" -> ")[-1].strip()
                    rel_path = Path(path_part).as_posix()
                    dirty_files.add(rel_path)

        res_log = subprocess.run(
            ["git", "log", "-n", "100", "--name-only", "--format="],
            cwd=root,
            capture_output=True,
            text=True,
            check=False
        )
        if res_log.returncode == 0:
            for line in res_log.stdout.splitlines():
                line = line.strip()
                if line:
                    rel_path = Path(line).as_posix()
                    churn_counts[rel_path] = churn_counts.get(rel_path, 0) + 1
    except Exception:
        pass
    return dirty_files, churn_counts


# ── main entry point ─────────────────────────────────────────────────────────

def scan_directory(
    root: Path,
    max_nodes: int = 500,
    generic_mentions: bool = False,
    skip_dirs: list[str] | None = None,
    depth: str = "files",
    frontend: str = "auto",
    docs: bool = False,
    previous_graph_path: Path | None = None,
    manifest_path: Path | None = None,
) -> Graph:
    """Scan *root* and build a Graph of file-level (and optionally symbol-level) nodes.

    Handles: Python, JS/TS, Go, Rust, Java, C#, C/C++, Ruby,
             Markdown links, RST includes, HTML hrefs.
    """
    root = root.resolve()
    extra_skip = frozenset(skip_dirs) if skip_dirs else frozenset()
    files = collect_files(root, max_nodes, extra_skip)

    file_map: dict[str, str] = {}   # rel_posix -> node_id
    for f in files:
        rel = f.relative_to(root).as_posix()
        nid = node_id(f, root)
        file_map[rel] = nid

    nodes: dict[str, Node] = {}
    edges: list[Edge] = []
    seen: set[tuple[str, str]] = set()

    # Load manifest and previous graph if available and paths are provided
    from ..manifest import Manifest, compute_file_hash
    from ..io import load_any

    manifest = None
    previous_graph = None
    if manifest_path and previous_graph_path:
        manifest = Manifest.load(manifest_path)
        if previous_graph_path.exists():
            try:
                previous_graph = load_any(previous_graph_path)
            except Exception:
                previous_graph = None

    skipped_files: list[tuple[Path, str, str]] = []
    dirty_files: list[tuple[Path, str, str]] = []

    if manifest and previous_graph:
        for f in files:
            rel = f.relative_to(root).as_posix()
            info = manifest.get_file_info(rel)
            current_hash = compute_file_hash(f)
            if (info and info.get("hash") == current_hash and
                info.get("depth") == depth and
                info.get("frontend") == frontend and
                info.get("docs") == docs):
                skipped_files.append((f, rel, current_hash))
            else:
                dirty_files.append((f, rel, current_hash))
    else:
        for f in files:
            rel = f.relative_to(root).as_posix()
            current_hash = compute_file_hash(f)
            dirty_files.append((f, rel, current_hash))

    active_rels = {f.relative_to(root).as_posix() for f in files}

    # Helper to determine owning file path of any node ID (for edge mapping)
    def find_file_for_node(node_id: str) -> str | None:
        if node_id in nodes:
            return nodes[node_id].path
        # fallback: check file_map
        for rel, nid in file_map.items():
            if nid == node_id:
                return rel
        return None

    # Load skipped nodes and edges
    for f, rel, fhash in skipped_files:
        info = manifest.get_file_info(rel)
        for nid in info.get("nodes", []):
            if nid in previous_graph.nodes:
                nodes[nid] = previous_graph.nodes[nid]
        for src, tgt, etype in info.get("edges", []):
            matching_edge = None
            for pe in previous_graph.edges:
                if pe.source == src and pe.target == tgt and pe.type == etype:
                    matching_edge = pe
                    break
            if matching_edge:
                edges.append(matching_edge)
                seen.add((src, tgt))
            else:
                edges.append(Edge(source=src, target=tgt, type=etype))
                seen.add((src, tgt))

    dirty_git, churn_git = _get_git_metadata(root)

    # Create file nodes for dirty files
    for f, rel, fhash in dirty_files:
        nid = file_map[rel]
        facts = []
        if "/" not in rel and "\\" not in rel:
            facts.append(f"project:{root.name.lower()}")
        if rel in dirty_git:
            facts.append("git:dirty")
            facts.append("git:modified")
        churn = churn_git.get(rel, 0)
        if churn > 0:
            facts.append(f"git:churn-{churn}")
            if churn >= 5:
                facts.append("git:high-churn")
                facts.append("git:frequent")

        nodes[nid] = Node(
            id=nid,
            label=f.name,
            kind=EXT_KIND.get(f.suffix.lower(), "file"),
            path=rel,
            facts=facts,
        )

    add_file_edges(
        dirty_files=dirty_files,
        root=root,
        file_map=file_map,
        edges=edges,
        seen=seen,
        generic_mentions=generic_mentions,
    )

    metadata = {
        "scan_depth": depth,
        "frontend": "files",
        "docs": str(bool(docs)).lower(),
        "git_dirty": ",".join(dirty_git),
        "git_high_churn": ",".join(rel for rel, churn in churn_git.items() if churn >= 5),
    }

    if depth == "symbols" and dirty_files:
        source_files: list[SourceFile] = []
        for f, rel, fhash in dirty_files:
            suffix = f.suffix.lower()
            if suffix not in PARSEABLE_SUFFIXES:
                continue
            file_nid = file_map[rel]
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            source_files.append(SourceFile(f, rel, file_nid, text))

        if source_files:
            max_syms = max(500, max_nodes * 5)
            extraction = select_extractor(frontend).extract_symbols(source_files, max_total_symbols=max_syms)
            metadata["frontend"] = extraction.frontend
            nodes.update(extraction.nodes)
            existing = {(e.source, e.target, e.type) for e in edges}
            for e in extraction.edges:
                key = (e.source, e.target, e.type)
                if key not in existing:
                    existing.add(key)
                    edges.append(e)

    if docs and dirty_files:
        doc_inputs: list[DocumentInput] = []
        for f, rel, fhash in dirty_files:
            if f.suffix.lower() not in DOC_SUFFIXES:
                continue
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            doc_inputs.append(DocumentInput(f, rel, file_map[rel], text))
        if doc_inputs:
            symbol_map = {node.label: nid for nid, node in nodes.items() if node.kind not in {"file", "concept", "section"}}
            doc_nodes, doc_edges = extract_document_context(doc_inputs, file_map, symbol_map=symbol_map)
            nodes.update(doc_nodes)
            existing = {(e.source, e.target, e.type) for e in edges}
            for e in doc_edges:
                key = (e.source, e.target, e.type)
                if key not in existing:
                    existing.add(key)
                    edges.append(e)

    # Update manifest for the scanned (dirty) files
    if manifest:
        # Clean up deleted files from manifest
        keys_to_delete = [k for k in manifest.files if k not in active_rels]
        for k in keys_to_delete:
            del manifest.files[k]

        for f, rel, fhash in dirty_files:
            file_nodes = [nid for nid, node in nodes.items() if find_file_for_node(nid) == rel]
            file_edges = [(e.source, e.target, e.type) for e in edges if find_file_for_node(e.source) == rel]
            manifest.update_file(
                rel_path=rel,
                file_hash=fhash,
                depth=depth,
                frontend=frontend,
                docs=docs,
                nodes=file_nodes,
                edges=file_edges,
            )
        manifest.save(manifest_path)

    graph = Graph(nodes=nodes, edges=edges, metadata=metadata)
    return graph
