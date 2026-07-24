"""Canonical public packet-format contracts.

Render dispatch lives in :mod:`graphgraph.packets.renderers`; this module owns
the transport-facing names and descriptions shared by CLI, MCP, HTTP, and docs.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class PacketFormatSpec:
    name: str
    schema_tokens: int
    relative_tokens: str
    description: str

    def as_public_dict(self) -> dict[str, object]:
        row = asdict(self)
        row["format"] = row.pop("name")
        return row


PACKET_FORMATS: tuple[PacketFormatSpec, ...] = (
    PacketFormatSpec("lowlevel", 20, "1.03x", "XML-tagged adjacency; a readable structural fallback."),
    PacketFormatSpec("sql", 10, "1.38x+", "Table-row layout for models that prefer relational structure."),
    PacketFormatSpec("hybrid", 5, "~2.3x", "Readable Markdown node and edge lists with higher token overhead."),
    PacketFormatSpec("semantic_arrow", 15, "1.49x", "SVO arrows; preferred for zero-edge structural results."),
    PacketFormatSpec("gg", 20, "1.00x", "Measured token floor for non-empty structural graph packets."),
    PacketFormatSpec("gg_hybrid", 20, "~1.6x", "Integer-id gg plus inline grounded node facts."),
    PacketFormatSpec("gg_lex", 20, "~1.0x", "Compact gg topology with stable lexical node identifiers."),
    PacketFormatSpec("gg_lex_hybrid", 20, "~1.6x", "Lexical-id gg plus inline grounded node facts."),
    PacketFormatSpec("svo", 0, "~1.1x", "Self-describing subject-verb-object triples."),
    PacketFormatSpec("doc_summary", 2, "~0.6x", "Grounded document sections and notes without topology."),
)

PACKET_FORMAT_NAMES: tuple[str, ...] = tuple(spec.name for spec in PACKET_FORMATS)
PACKET_FORMAT_TABLE: tuple[dict[str, object], ...] = tuple(
    spec.as_public_dict() for spec in PACKET_FORMATS
)


def packet_format_schema(*, default: str | None = None) -> dict[str, object]:
    schema: dict[str, object] = {
        "type": "string",
        "enum": list(PACKET_FORMAT_NAMES),
        "description": "Packet format override. Supported formats: " + ", ".join(PACKET_FORMAT_NAMES) + ".",
    }
    if default is not None:
        schema["default"] = default
    return schema


def packet_format_markdown_table() -> str:
    rows = [
        "| Packet | Relative tokens | Use |",
        "| --- | ---: | --- |",
    ]
    rows.extend(
        f"| `{spec.name}` | {spec.relative_tokens} | {spec.description} |"
        for spec in PACKET_FORMATS
    )
    return "\n".join(rows)
