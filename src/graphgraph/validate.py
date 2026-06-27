from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    format: str
    node_count: int
    edge_count: int
    errors: tuple[str, ...] = ()


def validate_packet(packet: str) -> ValidationResult:
    text = packet.strip()
    if text.startswith("<g>"):
        return validate_lowlevel(text)
    if text.startswith("TABLE nodes:"):
        return validate_sql(text)
    if text.startswith("@nodes") or "@nodes" in text:
        return validate_semantic_arrow(text)
    if text.startswith("[r]") or "[r]" in text:
        return validate_gg_max(text)
    return ValidationResult(False, "unknown", 0, 0, ("unknown packet format",))


def validate_gg_max(packet: str) -> ValidationResult:
    errors: list[str] = []
    relations: dict[str, str] = {}
    nodes: dict[str, str] = {}
    edges = []

    if "[r]" not in packet or "[n]" not in packet or "[e]" not in packet:
        errors.append("missing [r], [n], or [e] sections")
        fmt = "gg_max_hybrid" if "summary:" in packet else "gg_max"
        return ValidationResult(False, fmt, 0, 0, tuple(errors))

    parts = packet.split("[e]", 1)
    rn_part = parts[0]
    edges_part = parts[1]

    rn_parts = rn_part.split("[n]", 1)
    relations_part = rn_parts[0].split("[r]", 1)[1]
    nodes_part = rn_parts[1]

    for line in nonempty_lines(relations_part):
        if ":" not in line:
            errors.append(f"bad relation row: {line}")
            continue
        rel_id, rel = line.split(":", 1)
        relations[rel_id.strip()] = rel.strip()

    for line in nonempty_lines(nodes_part):
        # Fact/summary continuation lines (indented) or comments — skip for node counting.
        if line.startswith(" ") or line.startswith("-") or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split(None, 1)]
        if len(parts) < 2:
            errors.append(f"bad node row: {line}")
            continue
        node_id, label = parts
        nodes[node_id] = label

    for line in nonempty_lines(edges_part):
        parts = [part.strip() for part in line.split()]
        if len(parts) == 3:
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

    # Detect hybrid: node lines carry metadata beyond just index+label ([kind] annotation or legacy summary: prefix)
    is_lex = any(not nid.isdigit() for nid in nodes)
    is_hybrid = "summary:" in packet or bool(
        re.search(r"^\S+\s+\S+\s+\[", nodes_part, re.MULTILINE)
    )
    if is_lex:
        fmt = "gg_lex_hybrid" if is_hybrid else "gg_lex"
    else:
        fmt = "gg_max_hybrid" if is_hybrid else "gg_max"
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
