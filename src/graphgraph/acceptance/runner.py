"""Black-box probe driver.

``run_probe`` drives GraphGraph's public native retrieval, parses the compact
packet, and records everything an acceptance receipt needs. ``run_case`` scores
a probe against a task's sealed ground truth via its gate function.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Optional

from graphgraph.services.native import render_native_context

from .gates import default_gates
from .model import CaseResult, PacketEdge, PacketNode, ProbeResult, Task
from .tokens import count_tokens


def _parse_packet(packet: str) -> tuple[dict[str, str], list[PacketNode], list[PacketEdge]]:
    """Parse the ``#gg`` compact packet into relations, nodes, and edges."""
    relations: dict[str, str] = {}
    nodes: list[PacketNode] = []
    edges: list[PacketEdge] = []
    section: Optional[str] = None
    current_rel = ""
    for raw in packet.splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped in ("[r]", "[n]", "[e]"):
            section = stripped
            continue
        if section == "[r]":
            if ":" in stripped:
                rid, name = stripped.split(":", 1)
                relations[rid.strip()] = name.strip()
        elif section == "[n]":
            head, _, rest = stripped.partition(" ")
            label = rest.split(" @", 1)[0].strip()
            path = ""
            if " @" in rest:
                path = rest.split(" @", 1)[1].split(" ", 1)[0]
            nodes.append(PacketNode(local_id=head, label=label, path=path))
        elif section == "[e]":
            if stripped.endswith(":") and stripped[:-1].strip().isdigit():
                current_rel = stripped[:-1].strip()
                continue
            bits = stripped.split()
            if len(bits) >= 2 and bits[0].isdigit() and bits[1].isdigit():
                edges.append(
                    PacketEdge(
                        relation=relations.get(current_rel, current_rel),
                        src=bits[0],
                        dst=bits[1],
                    )
                )
    return relations, nodes, edges


def graph_identity(graph_path: Path) -> dict:
    """Reproducible graph identity. The .gg manifest carries no hash, so we hash
    the graph bytes; this is the stable identity a receipt can be replayed against."""
    identity: dict = {"graph": str(graph_path)}
    try:
        raw = graph_path.read_bytes()
    except OSError:
        return identity
    identity["hash"] = hashlib.sha256(raw).hexdigest()[:16]
    identity["bytes"] = len(raw)
    manifest = graph_path.parent / (graph_path.name + ".manifest.json")
    if manifest.exists():
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
            identity["manifest_version"] = data.get("version")
            files = data.get("files")
            if isinstance(files, (list, dict)):
                identity["files"] = len(files)
        except Exception:
            pass
    return identity


def run_probe(task: Task, repo: Path, graph_path: Optional[Path] = None) -> ProbeResult:
    graph_path = graph_path or (repo / ".graphgraph" / "graph.gg")
    rendered, _status = render_native_context(
        query=task.query,
        query_class=task.query_class,
        directory=repo,
        graph_path=graph_path,
        json_output=True,
        json_details=True,
        show_anchors=True,
        max_nodes=task.max_nodes,
        scopes=task.scopes,
        packet="gg",
    )
    payload = json.loads(rendered)

    packet = str(payload.get("packet", ""))
    relations, nodes, edges = _parse_packet(packet)
    retrieval = payload.get("retrieval", {}) or {}
    quality = retrieval.get("quality", {}) or {}
    answerability = retrieval.get("answerability", {}) or {}
    workflow = payload.get("workflow", {}) or {}
    cache = workflow.get("cache", {}) or {}
    query_ms = float(workflow.get("query_milliseconds", 0.0) or 0.0)

    control_raw = str(payload.get("control", ""))
    query_class = payload.get("query_class", task.query_class)
    next_action = ""
    for field_pair in control_raw.split():
        if field_pair.startswith("next="):
            next_action = field_pair.split("=", 1)[1]
        elif field_pair.startswith("op="):
            query_class = field_pair.split("=", 1)[1]

    return ProbeResult(
        task_id=task.id,
        query=task.query,
        query_class=str(query_class),
        state=str(answerability.get("status", "")),
        next_action=next_action,
        control_raw=control_raw,
        packet=packet,
        nodes=int(quality.get("nodes", len(nodes))),
        edges=int(quality.get("edges", len(edges))),
        tokens=count_tokens(packet),
        packet_nodes=nodes,
        packet_edges=edges,
        relations=relations,
        facet_coverage=retrieval.get("facet_coverage", {}) or {},
        structural_facet_coverage=retrieval.get("structural_facet_coverage", {}) or {},
        answerability=answerability,
        anchors=list(payload.get("anchors", []) or []),
        plain_nodes=len(nodes),
        plain_edges=len(edges),
        graph_identity=graph_identity(graph_path),
        query_ms=query_ms,
        cache_state=str(cache.get("state", "")),
        raw=payload,
    )


def run_case(task: Task, repo: Path, graph_path: Optional[Path] = None) -> CaseResult:
    if task.status == "pending":
        return CaseResult(task=task, probe=None, gates=[])
    if task.case_fn is not None:
        try:
            return task.case_fn(task, repo, graph_path)
        except Exception as exc:  # noqa: BLE001
            return CaseResult(task=task, probe=None, gates=[], error=f"{type(exc).__name__}: {exc}")
    try:
        probe = run_probe(task, repo, graph_path)
    except Exception as exc:  # noqa: BLE001 - surface as a scored failure, never crash the board
        return CaseResult(task=task, probe=None, gates=[], error=f"{type(exc).__name__}: {exc}")
    gate_fn = task.gate_fn or default_gates
    gates = gate_fn(probe, task)
    return CaseResult(task=task, probe=probe, gates=gates)
