from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from ..concepts import link_source_interpretation_concepts
from ..concepts.terms import term_key
from ..graph.core import Edge, Graph, Node
from .doc import DocumentInput, extract_document_context
from .files import DOC_SUFFIXES, EXT_KIND, PARSEABLE_SUFFIXES, collect_files, node_id
from .frontends import SourceFile, select_extractor
from .history import extract_commit_history
from .imports import add_file_edges

logger = logging.getLogger(__name__)


def _get_git_metadata(root: Path) -> tuple[set[str], dict[str, int]]:
    dirty_files: set[str] = set()
    churn_counts: dict[str, int] = {}
    try:
        # `-z` disables git's core.quotepath escaping (which otherwise wraps
        # any path containing a space or non-ASCII byte in double quotes with
        # C-style/octal escapes, e.g. "caf\303\251.py" for "café.py") and
        # NUL-terminates each field instead. Parsing the quoted/escaped text
        # form directly (the previous approach) left the literal quote
        # characters and escape sequences in the path, so such files never
        # matched their real on-disk relative path and were silently dropped.
        res_status = subprocess.run(
            ["git", "status", "--porcelain", "-z"],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False
        )
        if res_status.returncode == 0:
            tokens = res_status.stdout.split("\0")
            i = 0
            while i < len(tokens):
                entry = tokens[i]
                i += 1
                if len(entry) > 3:
                    status_code = entry[:2]
                    rel_path = Path(entry[3:]).as_posix()
                    dirty_files.add(rel_path)
                    if "R" in status_code or "C" in status_code:
                        # Renamed/copied entries are followed by an extra
                        # NUL-terminated token holding the original path.
                        i += 1

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
        logger.debug("git metadata lookup failed; scan priority/churn signals disabled", exc_info=True)
    return dirty_files, churn_counts


def _load_manifest_and_graph(manifest_path: Path | None, previous_graph_path: Path | None):
    from ..io import load_any
    from ..manifest import Manifest

    manifest = Manifest.load(manifest_path) if manifest_path else None
    previous_graph = None
    if previous_graph_path and previous_graph_path.exists():
        try:
            previous_graph = load_any(previous_graph_path)
        except Exception:
            previous_graph = None
    return manifest, previous_graph


# ── main entry point ─────────────────────────────────────────────────────────

def scan_directory(
    root: Path,
    max_nodes: int = 2000,
    generic_mentions: bool = False,
    skip_dirs: list[str] | None = None,
    depth: str = "files",
    frontend: str = "auto",
    docs: bool = False,
    history: bool = False,
    max_history_commits: int = 300,
    previous_graph_path: Path | None = None,
    manifest_path: Path | None = None,
    include: list[str] | None = None,
) -> Graph:
    """Scan *root* and build a Graph of file-level (and optionally symbol-level) nodes.

    Handles: Python, JS/TS, Go, Rust, Java, C#, C/C++, Ruby,
             Markdown links, RST includes, HTML hrefs.

    This is the full-discovery path: it walks the whole tree and hashes every
    file to figure out what changed. For an agent loop that already knows
    exactly which files it just edited, ``update_paths``/``remove_paths``
    below skip that discovery entirely and are much cheaper on large repos.
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

    manifest, previous_graph = _load_manifest_and_graph(manifest_path, previous_graph_path)
    from ..manifest import compute_file_hash

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

    return _build_graph_from_split(
        root=root,
        file_map=file_map,
        dirty_files=dirty_files,
        skipped_files=skipped_files,
        active_rels=active_rels,
        dirty_git=dirty_git,
        churn_git=churn_git,
        manifest=manifest,
        previous_graph=previous_graph,
        manifest_path=manifest_path,
        max_nodes=max_nodes,
        generic_mentions=generic_mentions,
        depth=depth,
        frontend=frontend,
        docs=docs,
        history=history,
        max_history_commits=max_history_commits,
    )


def _normalize_rels(root: Path, paths: list[str] | list[Path]) -> set[str]:
    rels: set[str] = set()
    for p in paths:
        p = Path(p)
        p = p if p.is_absolute() else (root / p)
        try:
            rel = p.resolve().relative_to(root).as_posix()
        except ValueError:
            # Not under root; fall back to treating it as already-relative.
            rel = Path(p).as_posix()
        rels.add(rel)
    return rels


def update_paths(
    root: Path,
    paths: list[str],
    max_nodes: int = 2000,
    generic_mentions: bool = False,
    depth: str = "symbols",
    frontend: str = "auto",
    docs: bool = False,
    history: bool = False,
    max_history_commits: int = 300,
    previous_graph_path: Path | None = None,
    manifest_path: Path | None = None,
) -> Graph:
    """Re-extract exactly *paths* and splice the result into the existing graph.

    Unlike ``scan_directory``, this never walks the directory tree or hashes
    any file the caller didn't name -- every other previously-tracked file is
    trusted as unchanged and restored verbatim from the manifest + previous
    graph. This is the primitive an edit/test/measure loop should call after
    touching a known set of files: cost is proportional to ``len(paths)``,
    not to repo size.

    Requires an existing manifest and graph (run ``scan_directory`` once
    first). A path that no longer exists on disk is treated as a removal.
    """
    root = root.resolve()
    if not manifest_path or not previous_graph_path:
        raise ValueError("update_paths requires manifest_path and previous_graph_path from a prior scan")
    manifest, previous_graph = _load_manifest_and_graph(manifest_path, previous_graph_path)
    if manifest is None or previous_graph is None:
        raise ValueError(
            f"no existing graph/manifest at {previous_graph_path} -- run scan_directory once before update_paths"
        )

    target_rels = _normalize_rels(root, paths)
    existing_target_rels = {rel for rel in target_rels if (root / rel).exists()}
    removed_target_rels = target_rels - existing_target_rels

    known_rels = (set(manifest.files.keys()) | existing_target_rels) - removed_target_rels
    active_rels = known_rels

    from ..manifest import compute_file_hash

    dirty_files: list[tuple[Path, str, str]] = []
    for rel in existing_target_rels:
        f = root / rel
        dirty_files.append((f, rel, compute_file_hash(f)))

    skipped_files: list[tuple[Path, str, str]] = []
    for rel in active_rels - existing_target_rels:
        info = manifest.get_file_info(rel)
        file_hash = info.get("hash", "") if info else ""
        skipped_files.append((root / rel, rel, file_hash))

    file_map = {rel: node_id(root / rel, root) for rel in active_rels}
    dirty_git, churn_git = _get_git_metadata(root)

    return _build_graph_from_split(
        root=root,
        file_map=file_map,
        dirty_files=dirty_files,
        skipped_files=skipped_files,
        active_rels=active_rels,
        dirty_git=dirty_git,
        churn_git=churn_git,
        manifest=manifest,
        previous_graph=previous_graph,
        manifest_path=manifest_path,
        max_nodes=max_nodes,
        generic_mentions=generic_mentions,
        depth=depth,
        frontend=frontend,
        docs=docs,
        history=history,
        max_history_commits=max_history_commits,
        scope_concepts_to_dirty=True,
    )


def remove_paths(
    root: Path,
    paths: list[str],
    max_nodes: int = 2000,
    generic_mentions: bool = False,
    depth: str = "symbols",
    frontend: str = "auto",
    docs: bool = False,
    history: bool = False,
    max_history_commits: int = 300,
    previous_graph_path: Path | None = None,
    manifest_path: Path | None = None,
) -> Graph:
    """Drop *paths* (deleted/renamed-away files) from the graph, no re-extraction.

    Every node/edge owned by *paths* is dropped; everything else is restored
    verbatim from the manifest + previous graph. No directory walk, no
    hashing, no symbol extraction -- this is pure removal.
    """
    root = root.resolve()
    if not manifest_path or not previous_graph_path:
        raise ValueError("remove_paths requires manifest_path and previous_graph_path from a prior scan")
    manifest, previous_graph = _load_manifest_and_graph(manifest_path, previous_graph_path)
    if manifest is None or previous_graph is None:
        raise ValueError(
            f"no existing graph/manifest at {previous_graph_path} -- run scan_directory once before remove_paths"
        )

    target_rels = _normalize_rels(root, paths)
    active_rels = set(manifest.files.keys()) - target_rels

    skipped_files: list[tuple[Path, str, str]] = []
    for rel in active_rels:
        info = manifest.get_file_info(rel)
        file_hash = info.get("hash", "") if info else ""
        skipped_files.append((root / rel, rel, file_hash))

    file_map = {rel: node_id(root / rel, root) for rel in active_rels}

    return _build_graph_from_split(
        root=root,
        file_map=file_map,
        dirty_files=[],
        skipped_files=skipped_files,
        active_rels=active_rels,
        dirty_git=set(),
        churn_git={},
        manifest=manifest,
        previous_graph=previous_graph,
        manifest_path=manifest_path,
        max_nodes=max_nodes,
        generic_mentions=generic_mentions,
        depth=depth,
        frontend=frontend,
        docs=docs,
        history=history,
        max_history_commits=max_history_commits,
        scope_concepts_to_dirty=True,
    )


def _build_graph_from_split(
    *,
    root: Path,
    file_map: dict[str, str],
    dirty_files: list[tuple[Path, str, str]],
    skipped_files: list[tuple[Path, str, str]],
    active_rels: set[str],
    dirty_git: set[str],
    churn_git: dict[str, int],
    manifest,
    previous_graph,
    manifest_path: Path | None,
    max_nodes: int,
    generic_mentions: bool,
    depth: str,
    frontend: str,
    docs: bool,
    history: bool,
    max_history_commits: int,
    scope_concepts_to_dirty: bool = False,
) -> Graph:
    """Shared body: given a dirty/skip split (however it was determined),
    build the resulting Graph. Used by both the full-discovery
    ``scan_directory`` and the targeted ``update_paths``/``remove_paths``.
    """
    nodes: dict[str, Node] = {}
    edges: list[Edge] = []
    seen: set[tuple[str, str]] = set()

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

    # Index previous edges once by (source, target, type) so restoring skipped
    # files' edges is O(1) per lookup instead of a linear scan over the whole
    # previous graph. On a large repo with mostly-unchanged files, that linear
    # scan was effectively O(edges^2) -- e.g. ~87k edges made a no-op rescan
    # of locus take over 80s here even though nothing had changed.
    previous_edge_index: dict[tuple[str, str, str], Edge] = {}
    if previous_graph is not None:
        for pe in previous_graph.edges:
            previous_edge_index.setdefault((pe.source, pe.target, pe.type), pe)

    # Load skipped nodes. Do not restore nodes owned by files that will be
    # rescanned below; those symbols must come from the current source text.
    for f, rel, fhash in skipped_files:
        info = manifest.get_file_info(rel)
        if info is None:
            continue
        for nid in info.get("nodes", []):
            if nid in previous_graph.nodes:
                previous_node = previous_graph.nodes[nid]
                if previous_node.path not in dirty_rels:
                    nodes[nid] = previous_node
                    if _context_symbol_node(previous_node):
                        context_symbol_nodes[nid] = previous_node
        for src, tgt, etype in info.get("edges", []):
            matching_edge = previous_edge_index.get((src, tgt, etype))
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
            facts=tuple(facts),
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
        "history": str(bool(history)).lower(),
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

    if history:
        history_nodes, history_edges = extract_commit_history(root, file_map, max_commits=max_history_commits)
        if history_nodes or history_edges:
            nodes.update(history_nodes)
            existing = {(e.source, e.target, e.type) for e in edges}
            for e in history_edges:
                key = (e.source, e.target, e.type)
                if key not in existing:
                    existing.add(key)
                    edges.append(e)

    # Interpretation-concept linking is a pure function of a node's own
    # fields (label/kind/path/facts) -- deterministic and independent of
    # other files. For the full-discovery scan it's cheap enough (relative
    # to everything else) to just run over every node. For targeted
    # update/remove on a large graph, only the dirty side needs it: a
    # skipped node's concept edges were already captured in its owning
    # file's manifest entry the last time it was dirty (via the
    # endpoint_nodes side-channel below) and get restored through
    # skipped_edges/nodes exactly like any other edge type.
    concept_source_nodes = (
        tuple(n for n in nodes.values() if n.path in dirty_rels)
        if scope_concepts_to_dirty
        else tuple(nodes.values())
    )
    interpretation_nodes: dict[str, Node] = {}
    interpretation_edges: list[Edge] = []
    for node in concept_source_nodes:
        if node.kind in {"concept", "section", "markdown", "rst", "html", "text", "unknown", "commit"}:
            continue
        found_nodes, found_edges = link_source_interpretation_concepts(node, source_location=node.path)
        interpretation_nodes.update(found_nodes)
        interpretation_edges.extend(found_edges)
    if interpretation_nodes or interpretation_edges:
        nodes.update(interpretation_nodes)
        existing = {(e.source, e.target, e.type) for e in edges}
        for e in interpretation_edges:
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
        if manifest_path is not None:
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
