from __future__ import annotations

import json
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    format: str
    node_count: int
    edge_count: int
    errors: tuple[str, ...] = ()


def _has_marker_line(text: str, marker: str) -> bool:
    """True if *marker* (e.g. "[r]") appears as its own exact line.

    render_gg_max/render_gg_lex always emit "[r]"/"[n]"/"[e]" as standalone
    lines (confirmed directly in packets/renderers.py -- each is its own
    `lines.append(...)` call). Checking for the marker as a bare substring
    anywhere in the packet (the previous approach) meant a node whose
    label/summary/fact happened to *contain* the literal text "[e]" (e.g. a
    doc-scanned string like "a packet ending in \\n[e]", captured verbatim
    as a concept label) would corrupt parsing for the entire rest of the
    packet -- confirmed with a real repro: rendering this project's own
    full graph unfiltered produced exactly such a node and broke gg
    validation for ~250 nodes downstream of it.
    """
    return re.search(rf"^\s*{re.escape(marker)}\s*$", text, re.MULTILINE) is not None


def _split_on_marker_line(text: str, marker: str) -> tuple[str, str]:
    """Split *text* at the first line that is exactly *marker*, dropping that line.

    Line-anchored counterpart to ``text.split(marker, 1)`` -- see
    ``_has_marker_line`` for why a bare substring split is unsafe.
    """
    match = re.search(rf"^\s*{re.escape(marker)}\s*$", text, re.MULTILINE)
    if match is None:
        raise ValueError(f"marker line {marker!r} not found")
    return text[: match.start()], text[match.end():]


def validate_packet(packet: str) -> ValidationResult:
    text = packet.strip()
    if text.startswith("<g>"):
        return _require_nonempty_nodes(validate_lowlevel(text))
    if text.startswith("TABLE nodes:"):
        return _require_nonempty_nodes(validate_sql(text))
    if text.startswith("[r]") or _has_marker_line(text, "[r]"):
        return _require_nonempty_nodes(validate_gg_max(text))
    if text.startswith("@nodes") or "@nodes" in text:
        return _require_nonempty_nodes(validate_semantic_arrow(text))
    if text.startswith("[d]") or _has_marker_line(text, "[d]"):
        return _require_nonempty_nodes(validate_doc_summary(_from_marker_line(text, "[d]")))
    return ValidationResult(False, "unknown", 0, 0, ("unknown packet format",))


def _require_nonempty_nodes(result: ValidationResult) -> ValidationResult:
    if result.ok and result.node_count == 0:
        return ValidationResult(
            False,
            result.format,
            result.node_count,
            result.edge_count,
            result.errors + ("empty packet: no nodes",),
        )
    return result


def _from_marker_line(text: str, marker: str) -> str:
    match = re.search(rf"^\s*{re.escape(marker)}\s*$", text, re.MULTILINE)
    return text[match.start():] if match is not None else text


def validate_graph_json(graph_json: str) -> ValidationResult:
    """Validate a saved GraphGraph JSON graph store, not a rendered packet."""
    errors: list[str] = []
    try:
        data = json.loads(graph_json)
    except json.JSONDecodeError as exc:
        return ValidationResult(False, "graph_json", 0, 0, (f"invalid JSON: {exc.msg}",))

    if not isinstance(data, dict):
        return ValidationResult(False, "graph_json", 0, 0, ("graph JSON root must be an object",))

    nodes_data = data.get("nodes")
    edges_data = data.get("edges") or data.get("links") or []
    if not isinstance(nodes_data, list):
        errors.append("missing or invalid nodes array")
        nodes_data = []
    if not isinstance(edges_data, list):
        errors.append("invalid edges array")
        edges_data = []

    node_ids: set[str] = set()
    for index, item in enumerate(nodes_data):
        if not isinstance(item, dict):
            errors.append(f"bad node row at index {index}")
            continue
        node_id = item.get("id")
        if not isinstance(node_id, str) or not node_id:
            errors.append(f"node missing id at index {index}")
            continue
        if node_id in node_ids:
            errors.append(f"duplicate node id: {node_id}")
        node_ids.add(node_id)

    edge_count = 0
    for index, item in enumerate(edges_data):
        if not isinstance(item, dict):
            errors.append(f"bad edge row at index {index}")
            continue
        source = item.get("source")
        target = item.get("target")
        if not isinstance(source, str) or not source:
            errors.append(f"edge missing source at index {index}")
        elif source not in node_ids:
            errors.append(f"edge source missing from nodes: {source}")
        if not isinstance(target, str) or not target:
            errors.append(f"edge missing target at index {index}")
        elif target not in node_ids:
            errors.append(f"edge target missing from nodes: {target}")
        if not (item.get("type") or item.get("relation")):
            errors.append(f"edge missing type/relation at index {index}")
        try:
            float(item.get("weight") if item.get("weight") is not None else 1.0)
        except (TypeError, ValueError):
            errors.append(f"bad edge weight at index {index}: {item.get('weight')}")
        edge_count += 1

    return ValidationResult(not errors, "graph_json", len(node_ids), edge_count, tuple(errors))


def validate_graph_object(graph: object, *, format_name: str = "graph") -> ValidationResult:
    """Validate a loaded Graph-like object regardless of on-disk encoding."""
    errors: list[str] = []
    nodes = getattr(graph, "nodes", None)
    edges = getattr(graph, "edges", None)
    if not isinstance(nodes, dict):
        return ValidationResult(False, format_name, 0, 0, ("graph nodes must be a dict",))
    if not isinstance(edges, list):
        return ValidationResult(False, format_name, len(nodes), 0, ("graph edges must be a list",))

    for node_id, node in nodes.items():
        if not isinstance(node_id, str) or not node_id:
            errors.append(f"bad node id: {node_id!r}")
        if getattr(node, "id", node_id) != node_id:
            errors.append(f"node key/id mismatch: {node_id}")

    for index, edge in enumerate(edges):
        source = getattr(edge, "source", "")
        target = getattr(edge, "target", "")
        edge_type = getattr(edge, "type", "")
        if source not in nodes:
            errors.append(f"edge source missing from nodes at index {index}: {source}")
        if target not in nodes:
            errors.append(f"edge target missing from nodes at index {index}: {target}")
        if not edge_type:
            errors.append(f"edge missing type at index {index}")
        try:
            float(getattr(edge, "weight", 1.0))
        except (TypeError, ValueError):
            errors.append(f"bad edge weight at index {index}: {getattr(edge, 'weight', None)}")
    return ValidationResult(not errors, format_name, len(nodes), len(edges), tuple(errors))


def looks_like_graph_json(text: str) -> bool:
    stripped = text.lstrip()
    if not stripped.startswith("{"):
        return False
    try:
        data = json.loads(stripped)
    except json.JSONDecodeError:
        return False
    return isinstance(data, dict) and isinstance(data.get("nodes"), list)


def validate_any(text: str) -> ValidationResult:
    if looks_like_graph_json(text):
        return validate_graph_json(text)
    return validate_packet(text)


def validate_gg_max(packet: str) -> ValidationResult:
    errors: list[str] = []
    relations: dict[str, str] = {}
    nodes: dict[str, str] = {}
    edges = []

    if not (_has_marker_line(packet, "[r]") and _has_marker_line(packet, "[n]") and _has_marker_line(packet, "[e]")):
        errors.append("missing [r], [n], or [e] sections")
        fmt = "gg_hybrid" if "summary:" in packet else "gg"
        return ValidationResult(False, fmt, 0, 0, tuple(errors))

    rn_part, edges_part = _split_on_marker_line(packet, "[e]")
    _, relations_and_nodes = _split_on_marker_line(rn_part, "[r]")
    relations_part, nodes_part = _split_on_marker_line(relations_and_nodes, "[n]")

    for line in nonempty_lines(relations_part):
        if ":" not in line:
            errors.append(f"bad relation row: {line}")
            continue
        rel_id, rel = line.split(":", 1)
        relations[rel_id.strip()] = rel.strip()

    for raw_line in nodes_part.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        # Fact/summary continuation lines (indented) or comments — skip for node counting.
        if raw_line.startswith(" ") or raw_line.startswith("\t") or line.startswith("-") or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split(None, 1)]
        if len(parts) < 2:
            errors.append(f"bad node row: {line}")
            continue
        node_id, label = parts
        nodes[node_id] = label

    current_rel_id = ""
    for line in nonempty_lines(edges_part):
        if line.endswith(":") and len(line.split()) == 1:
            current_rel_id = line[:-1].strip()
            if current_rel_id not in relations and not current_rel_id.isalpha():
                errors.append(f"edge relation missing from relation map: {current_rel_id}")
            continue
        parts = [part.strip() for part in line.split()]
        if len(parts) == 2 and current_rel_id:
            source, target = parts
            rel_id = current_rel_id
            weight = "1.0"
        elif len(parts) == 3 and current_rel_id:
            source, target, weight = parts
            rel_id = current_rel_id
        elif len(parts) == 3:
            source, target, rel_id = parts
            weight = "1.0"
        elif len(parts) == 4:
            source, target, rel_id, weight = parts
        else:
            errors.append(f"bad edge row: {line}")
            continue
        if source not in nodes:
            errors.append(f"edge source missing from nodes: {source}")
        if target not in nodes:
            errors.append(f"edge target missing from nodes: {target}")
        if rel_id not in relations and not rel_id.isalpha():
            errors.append(f"edge relation missing from relation map: {rel_id}")
        try:
            float(weight)
        except ValueError:
            errors.append(f"bad edge weight: {weight}")
        edges.append((source, target, rel_id, weight))

    # Detect hybrid: node lines carry metadata beyond just index+label ([kind] annotation,
    # indented fact/summary continuation lines, or legacy summary: prefix).
    #
    # The [kind] bracket can appear anywhere on the line, not just right after a
    # single-token label -- labels are free text (e.g. doc-section titles like
    # "Getting Started") and can contain spaces, so anchoring the regex to
    # "^\S+\s+\S+\s+\[" (idx, exactly one token, then bracket) silently failed to
    # match whenever a hybrid node's label had more than one word, misclassifying
    # a real gg_hybrid/gg_lex_hybrid packet as plain gg/gg_lex.
    explicit_format = next(
        (line.strip()[1:] for line in packet.splitlines() if line.strip() in {
            "#gg", "#gg_hybrid", "#gg_lex", "#gg_lex_hybrid",
        }),
        "",
    )
    is_lex = explicit_format.startswith("gg_lex") if explicit_format else any(not nid.isdigit() for nid in nodes)
    is_hybrid = explicit_format.endswith("_hybrid") if explicit_format else (
        "summary:" in packet
        or bool(re.search(r"\[[A-Za-z_][\w-]*\]", nodes_part))
        or bool(re.search(r"^[ \t]+\S", nodes_part, re.MULTILINE))
    )
    if is_lex:
        fmt = "gg_lex_hybrid" if is_hybrid else "gg_lex"
    else:
        fmt = "gg_hybrid" if is_hybrid else "gg"
    return ValidationResult(not errors, fmt, len(nodes), len(edges), tuple(errors))


def validate_semantic_arrow(packet: str) -> ValidationResult:
    errors: list[str] = []
    nodes: dict[str, str] = {}
    edges = []

    if "@nodes" not in packet or "@edges" not in packet:
        errors.append("missing @nodes or @edges sections")
        return ValidationResult(False, "semantic_arrow", 0, 0, tuple(errors))

    parts = packet.split("@edges", 1)
    nodes_part = parts[0].split("@nodes", 1)[1]
    edges_part = parts[1]

    for line in nonempty_lines(nodes_part):
        if ":" not in line:
            errors.append(f"bad node row: {line}")
            continue
        node_id, label = line.split(":", 1)
        nodes[node_id.strip()] = label.strip()

    for line in nonempty_lines(edges_part):
        match = re.match(r"^(\S+)\s+-(\S+)->\s+(\S+)\s+\((.+)\)$", line)
        if not match:
            match = re.match(r"^(\S+)\s+-(\S+)->\s+(\S+)$", line)
            if not match:
                errors.append(f"bad edge row: {line}")
                continue
            source, rel_type, target = match.groups()
            weight = "1.0"
        else:
            source, rel_type, target, weight = match.groups()

        source = source.strip()
        target = target.strip()
        rel_type = rel_type.strip()
        weight = weight.strip()

        if source not in nodes:
            errors.append(f"edge source missing from nodes: {source}")
        if target not in nodes:
            errors.append(f"edge target missing from nodes: {target}")
        try:
            float(weight)
        except ValueError:
            errors.append(f"bad edge weight: {weight}")
        edges.append((source, target, rel_type, weight))

    return ValidationResult(not errors, "semantic_arrow", len(nodes), len(edges), tuple(errors))


def validate_doc_summary(packet: str) -> ValidationResult:
    errors: list[str] = []
    lines = packet.splitlines()
    if not lines or lines[0].strip() != "[d]":
        errors.append("missing [d] header")
        return ValidationResult(False, "doc_summary", 0, 0, tuple(errors))

    node_count = 0
    for raw_line in lines[1:]:
        line = raw_line.strip()
        if not line:
            continue
        if raw_line.startswith(" ") or raw_line.startswith("\t"):
            continue
        node_count += 1

    if node_count == 0:
        errors.append("no document rows")
    return ValidationResult(not errors, "doc_summary", node_count, 0, tuple(errors))


def validate_lowlevel(packet: str) -> ValidationResult:
    errors: list[str] = []
    relations: dict[str, str] = {}
    nodes: dict[str, str] = {}
    edges = []

    relation_block = block(packet, "<r>", "</r>")
    node_block = block(packet, "<n>", "</n>")
    edge_block = block(packet, "<a>", "</a>")
    if relation_block is None:
        errors.append("missing <r> relation block")
    if node_block is None:
        errors.append("missing <n> node block")
    if edge_block is None:
        errors.append("missing <a> adjacency block")
    if errors:
        return ValidationResult(False, "lowlevel", 0, 0, tuple(errors))

    assert relation_block is not None
    assert node_block is not None
    assert edge_block is not None
    for line in nonempty_lines(relation_block):
        if ":" not in line:
            errors.append(f"bad relation row: {line}")
            continue
        rel_id, rel = line.split(":", 1)
        relations[rel_id] = rel
    for line in nonempty_lines(node_block):
        if ":" not in line:
            errors.append(f"bad node row: {line}")
            continue
        node_id, label = line.split(":", 1)
        nodes[node_id] = label
    for line in nonempty_lines(edge_block):
        parts = [part.strip() for part in line.split(",")]
        if len(parts) != 4:
            errors.append(f"bad edge row: {line}")
            continue
        source, target, rel_id, weight = parts
        if source not in nodes:
            errors.append(f"edge source missing from nodes: {source}")
        if target not in nodes:
            errors.append(f"edge target missing from nodes: {target}")
        if rel_id not in relations and not rel_id.isalpha():
            errors.append(f"edge relation missing from relation map: {rel_id}")
        try:
            float(weight)
        except ValueError:
            errors.append(f"bad edge weight: {weight}")
        edges.append((source, target, rel_id, weight))
    return ValidationResult(not errors, "lowlevel", len(nodes), len(edges), tuple(errors))


def validate_sql(packet: str) -> ValidationResult:
    errors: list[str] = []
    lines = packet.splitlines()
    node_line = next((line for line in lines if line.startswith("TABLE nodes:")), "")
    edge_line = next((line for line in lines if line.startswith("TABLE edges:")), "")
    if not node_line:
        errors.append("missing TABLE nodes row")
    if not edge_line:
        errors.append("missing TABLE edges row")
    if errors:
        return ValidationResult(False, "sql", 0, 0, tuple(errors))

    nodes = parse_table_rows(node_line)
    node_ids = set()
    for row in nodes:
        parts = [part.strip() for part in row.split(",")]
        if len(parts) < 4:
            errors.append(f"bad node row: {row}")
            continue
        node_ids.add(parts[0])

    edge_rows = parse_table_rows(edge_line)
    for row in edge_rows:
        parts = [part.strip() for part in row.split(",")]
        if len(parts) < 4:
            errors.append(f"bad edge row: {row}")
            continue
        source, target, _rel, weight = parts[:4]
        if source not in node_ids:
            errors.append(f"edge source missing from nodes: {source}")
        if target not in node_ids:
            errors.append(f"edge target missing from nodes: {target}")
        try:
            float(weight)
        except ValueError:
            errors.append(f"bad edge weight: {weight}")
    return ValidationResult(not errors, "sql", len(node_ids), len(edge_rows), tuple(errors))


def block(text: str, start: str, end: str) -> str | None:
    if start not in text or end not in text:
        return None
    return text.split(start, 1)[1].split(end, 1)[0]


def nonempty_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def parse_table_rows(line: str) -> list[str]:
    if "|" not in line:
        return []
    return [part.strip() for part in line.split("|")[1:] if part.strip()]
