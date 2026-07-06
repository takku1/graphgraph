from __future__ import annotations

import subprocess
from pathlib import Path

from ..core import Edge, Graph, Node
from ..terms import term_key
from .doc import DocumentInput, extract_document_context
from .files import DOC_SUFFIXES, EXT_KIND, PARSEABLE_SUFFIXES, collect_files, node_id
from .frontends import SourceFile, select_extractor
from .imports import add_file_edges


def _get_git_metadata(root: Path) -> tuple[set[str], dict[str, int]]:
    dirty_files: set[str] = set()
    churn_counts: dict[str, int] = {}
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
    max_nodes: int = 2000,
    generic_mentions: bool = False,
    skip_dirs: list[str] | None = None,
    depth: str = "files",
    frontend: str = "auto",
    docs: bool = False,
    previous_graph_path: Path | None = None,
    manifest_path: Path | None = None,
    include: list[str] | None = None,
) -> Graph:
    """Scan *root* and build a Graph of file-level (and optionally symbol-level) nodes.

    Handles: Python, JS/TS, Go, Rust, Java, C#, C/C++, Ruby,
             Markdown links, RST includes, HTML hrefs.
    """
    root = root.resolve()
    extra_skip = frozenset(skip_dirs) if skip_dirs else frozenset()
    include_set = frozenset(include) if include else frozenset()

    # Gather git metadata early so staged files get scan priority.
    dirty_git, churn_git = _get_git_metadata(root)

    files = collect_files(root, max_nodes, extra_skip, git_staged=dirty_git, include=include_set)

    file_map: dict[str, str] = {}   # rel_posix -> node_id
    for f in files:
        rel = f.relative_to(root).as_posix()
        nid = node_id(f, root)
        file_map[rel] = nid

    nodes: dict[str, Node] = {}
    edges: list[Edge] = []
    seen: set[tuple[str, str]] = set()

    # Load manifest and previous graph if available and paths are provided
    from ..io import load_any
    from ..manifest import Manifest, compute_file_hash

    manifest = None
    previous_graph = None
    if manifest_path:
        manifest = Manifest.load(manifest_path)
    if previous_graph_path:
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
    dirty_rels = {rel for _f, rel, _fhash in dirty_files}

    # Helper to determine owning file path of any node ID (for edge mapping)
    def find_file_for_node(node_id: str) -> str | None:
        if node_id in nodes:
            return nodes[node_id].path
        # fallback: check file_map
        for rel, nid in file_map.items():
            if nid == node_id:
                return rel
        return None

    skipped_edges: list[tuple[str, str, str, Edge | None]] = []
    context_symbol_nodes: dict[str, Node] = {}

    # Load skipped nodes. Do not restore nodes owned by files that will be
    # rescanned below; those symbols must come from the current source text.
    for f, rel, fhash in skipped_files:
        info = manifest.get_file_info(rel)
        for nid in info.get("nodes", []):
            if nid in previous_graph.nodes:
                previous_node = previous_graph.nodes[nid]
                if previous_node.path not in dirty_rels:
                    nodes[nid] = previous_node
                    if _context_symbol_node(previous_node):
                        context_symbol_nodes[nid] = previous_node
        for src, tgt, etype in info.get("edges", []):
            matching_edge = None
            for pe in previous_graph.edges:
                if pe.source == src and pe.target == tgt and pe.type == etype:
                    matching_edge = pe
                    break
            skipped_edges.append((src, tgt, etype, matching_edge))

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

    # Module hierarchy: add directory nodes and contains edges for every file
    # node, regardless of language-specific kind.
    import re
    for _rel, file_nid in file_map.items():
        file_node = nodes.get(file_nid)
        if not file_node:
            continue
        rel_path = Path(file_node.path)
        parent = rel_path.parent
        if parent == Path('.'):
            continue
        dir_rel = parent.as_posix()
        dir_id = f"dir_{re.sub(r'[^A-Za-z0-9_]', '_', dir_rel)}"
        if dir_id not in nodes:
            dir_node = Node(
                id=dir_id,
                label=parent.name,
                kind="package",
                path=dir_rel,
                facts=(),
            )
            nodes[dir_id] = dir_node
        edges.append(Edge(
            source=dir_id,
            target=file_nid,
            type="contains",
            weight=1.0,
            confidence=0.9,
            provenance="hierarchy",
            source_location="",
        ))

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
            extraction = select_extractor(frontend).extract_symbols(
                source_files,
                max_total_symbols=max_syms,
                context_nodes=context_symbol_nodes,
            )
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
            symbol_map: dict[str, str] = {}
            for nid, node in nodes.items():
                if node.kind in {"file", "concept", "section"}:
                    continue
                for alias in _symbol_aliases(node):
                    symbol_map.setdefault(alias, nid)
            doc_nodes, doc_edges = extract_document_context(doc_inputs, file_map, symbol_map=symbol_map)
            nodes.update(doc_nodes)
            existing = {(e.source, e.target, e.type) for e in edges}
            for e in doc_edges:
                key = (e.source, e.target, e.type)
                if key not in existing:
                    existing.add(key)
                    edges.append(e)

    existing_edges = {(e.source, e.target, e.type) for e in edges}
    for src, tgt, etype, matching_edge in skipped_edges:
        if src not in nodes or tgt not in nodes:
            continue
        key = (src, tgt, etype)
        if key in existing_edges:
            continue
        existing_edges.add(key)
        seen.add((src, tgt))
        if matching_edge:
            edges.append(matching_edge)
        else:
            edges.append(Edge(source=src, target=tgt, type=etype))

    # Update manifest for the scanned (dirty) files
    if manifest:
        # Clean up deleted files from manifest
        keys_to_delete = [k for k in manifest.files if k not in active_rels]
        for k in keys_to_delete:
            del manifest.files[k]

        for f, rel, fhash in dirty_files:
            file_edges = [(e.source, e.target, e.type) for e in edges if find_file_for_node(e.source) == rel]
            endpoint_nodes = {nid for edge in file_edges for nid in edge[:2] if nid in nodes}
            file_nodes = sorted({
                nid
                for nid, node in nodes.items()
                if find_file_for_node(nid) == rel or nid in endpoint_nodes
            })
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
    # Adjust confidence for edges using node centrality (degree) and visibility modifiers
    deg = graph.degree()
    
    # Calculate max degree per node kind
    max_deg_by_kind = {}
    for nid, node in graph.nodes.items():
        k = node.kind
        d = deg.get(nid, 0)
        if k not in max_deg_by_kind or d > max_deg_by_kind[k]:
            max_deg_by_kind[k] = d

    adjusted_edges = []
    for e in graph.edges:
        tgt_node = graph.nodes.get(e.target)
        if tgt_node and tgt_node.kind not in {"file", "package", "concept", "section", "unknown"}:
            confidence_adj = 0.0
            
            # 1. Centrality Boost (for explains/references/calls edges)
            if e.type in {"explains", "references", "calls"}:
                kind = tgt_node.kind
                max_kind_deg = max_deg_by_kind.get(kind, 1) or 1
                node_deg = deg.get(e.target, 0)
                # Boost up to +20% based on normalized degree centrality within the same kind
                confidence_adj += 0.2 * (node_deg / max_kind_deg)
                
            # 2. Visibility penalty
            if "modifier:private" in tgt_node.facts or "modifier:local" in tgt_node.facts:
                confidence_adj -= 0.15
            elif "modifier:protected" in tgt_node.facts:
                confidence_adj -= 0.05
                
            new_conf = min(1.0, max(0.0, e.confidence + confidence_adj))
            adjusted_edges.append(
                Edge(
                    source=e.source,
                    target=e.target,
                    type=e.type,
                    weight=e.weight,
                    confidence=new_conf,
                    provenance=e.provenance,
                    evidence=e.evidence,
                    source_location=e.source_location,
                    valid_from=e.valid_from,
                    valid_to=e.valid_to,
                    active=e.active,
                )
            )
        else:
            adjusted_edges.append(e)
    graph = Graph(nodes=graph.nodes, edges=adjusted_edges, metadata=graph.metadata)
    return graph


def _symbol_aliases(node: Node) -> tuple[str, ...]:
    aliases: list[str] = []
    for raw in (node.label, Path(node.path).stem if node.path else ""):
        if not raw:
            continue
        for candidate in (raw, term_key(raw)):
            if candidate and candidate not in aliases:
                aliases.append(candidate)
    return tuple(aliases)


def _context_symbol_node(node: Node) -> bool:
    return node.kind not in {"file", "python", "package", "concept", "section", "unknown"} and bool(node.path)
