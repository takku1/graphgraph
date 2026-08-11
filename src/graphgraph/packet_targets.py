"""Cold-start-safe packet-target catalog shared by every compiler surface."""

from __future__ import annotations

from typing import Callable, NamedTuple


class FunctionRef(NamedTuple):
    """Lazy reference that keeps target declarations cold-start safe."""

    module: str
    name: str

    def resolve(self) -> Callable:
        module = __import__(self.module, fromlist=(self.name,))
        return getattr(module, self.name)


class TokenCostModel(NamedTuple):
    intercept: float
    node_cost: float
    edge_cost: float
    calibrated: bool = True
    provenance: str = "token_surface_refit_2026_08_05"

    @property
    def coefficients(self) -> tuple[float, float, float]:
        return self.intercept, self.node_cost, self.edge_cost


class IdentityModel(NamedTuple):
    """Endpoint identity carried by an encoded edge relation."""

    projection: str = "node_id"
    requires_injective_projection: bool = False

    def admissible(self, graph, nodes) -> bool:
        if not self.requires_injective_projection:
            return True
        if self.projection != "label":
            raise ValueError(f"unsupported identity projection: {self.projection}")
        values = [graph.nodes[node_id].label for node_id in nodes if node_id in graph.nodes]
        return len(values) == len(set(values))


class SelectionPolicy(NamedTuple):
    """Alternative targets eligible for exact rendered-cost minimization."""

    alternatives: tuple[str, ...] = ()
    criterion: str = "exact_proxy_tokens"


class TargetSpec(NamedTuple):
    """Complete declaration of one compiler packet target."""

    name: str
    schema_tokens: int
    relative_tokens: str
    description: str
    capabilities: tuple[str, ...]
    encoder: FunctionRef
    validator: FunctionRef
    cost: TokenCostModel
    headers: tuple[str, ...] = ()
    line_prefixes: tuple[str, ...] = ()
    fallback_markers: tuple[str, ...] = ()
    encoder_options: tuple[tuple[str, bool], ...] = ()
    priority_aware: bool = False
    identity: IdentityModel = IdentityModel()
    selection: SelectionPolicy = SelectionPolicy()

    def encode(self, graph, nodes, edges, *, priority: tuple[str, ...] = ()) -> str:
        options = dict(self.encoder_options)
        if self.priority_aware and priority:
            options["priority"] = priority
        return self.encoder.resolve()(graph, nodes, edges, **options)

    def validate(self, packet: str):
        result = self.validator.resolve()(self.validation_payload(packet))
        if result.ok and result.node_count == 0:
            return type(result)(
                False,
                result.format,
                result.node_count,
                result.edge_count,
                result.errors + ("empty packet: no nodes",),
            )
        return result

    def validation_payload(self, packet: str) -> str:
        text = packet.strip()
        for prefix in self.line_prefixes:
            for line in text.splitlines():
                if line.startswith(prefix):
                    return text[text.index(line) :]
        for marker in (*self.headers, *self.fallback_markers):
            lines = text.splitlines()
            for index, line in enumerate(lines):
                if line.strip() == marker:
                    return "\n".join([marker, *lines[index + 1 :]])
        return text

    def as_public_dict(self) -> dict[str, object]:
        return {
            "format": self.name,
            "schema_tokens": self.schema_tokens,
            "relative_tokens": self.relative_tokens,
            "description": self.description,
            "capabilities": list(self.capabilities),
            "priority_aware": self.priority_aware,
            "identity": self.identity._asdict(),
            "selection": self.selection._asdict(),
            "cost_model": self.cost._asdict(),
        }


_RENDERERS = "graphgraph.packets.renderers"
_VALIDATORS = "graphgraph.packets.validation"
_GG_COST = TokenCostModel(6.6316, 11.9975, 5.1632)


def _target(
    name: str,
    schema_tokens: int,
    relative_tokens: str,
    description: str,
    *,
    encoder: str,
    validator: str,
    cost: TokenCostModel | None = None,
    capabilities: tuple[str, ...] = ("topology", "stable_identity"),
    headers: tuple[str, ...] = (),
    line_prefixes: tuple[str, ...] = (),
    fallback_markers: tuple[str, ...] = (),
    encoder_options: tuple[tuple[str, bool], ...] = (),
    priority_aware: bool = False,
    identity: IdentityModel = IdentityModel(),
    selection: SelectionPolicy = SelectionPolicy(),
) -> TargetSpec:
    return TargetSpec(
        name,
        schema_tokens,
        relative_tokens,
        description,
        capabilities,
        FunctionRef(_RENDERERS, encoder),
        FunctionRef(_VALIDATORS, validator),
        cost or TokenCostModel(*_GG_COST.coefficients, calibrated=False, provenance="gg_proxy"),
        headers,
        line_prefixes,
        fallback_markers,
        encoder_options,
        priority_aware,
        identity,
        selection,
    )


TARGET_SPECS: tuple[TargetSpec, ...] = (
    _target("lowlevel", 20, "1.03x", "XML-tagged adjacency; a readable structural fallback.", encoder="render_lowlevel", validator="validate_lowlevel", cost=TokenCostModel(31.7781, 3.3877, 9.2161), headers=("<g>",)),
    _target("sql", 10, "~0.7x", "Table-row layout for models that prefer relational structure.", encoder="render_sql", validator="validate_sql", cost=TokenCostModel(17.9379, 15.2861, 10.1090), line_prefixes=("TABLE nodes:",)),
    _target("hybrid", 5, "~2.3x", "Readable Markdown node and edge lists with higher token overhead.", encoder="render_hybrid", validator="validate_hybrid", capabilities=("topology", "facts", "stable_identity"), headers=("# Context Packet",)),
    _target("semantic_arrow", 15, "1.49x", "SVO arrows; preferred for zero-edge structural results.", encoder="render_semantic_arrow", validator="validate_semantic_arrow", cost=TokenCostModel(7.2784, 3.3447, 11.2080), headers=("@nodes",)),
    _target("gg", 20, "1.00x", "Measured token floor for non-empty structural graph packets.", encoder="render_gg", validator="validate_gg_max", cost=_GG_COST, headers=("#gg",), fallback_markers=("[r]",), priority_aware=True, selection=SelectionPolicy(("svo",))),
    _target("gg_hybrid", 20, "~1.6x", "Integer-id gg plus inline grounded node facts.", encoder="render_gg", validator="validate_gg_max", cost=TokenCostModel(8.1675, 14.3447, 5.0622), capabilities=("topology", "facts", "stable_identity"), headers=("#gg_hybrid",), encoder_options=(("facts", True),), priority_aware=True),
    _target("gg_lex", 20, "~1.0x", "Compact gg topology with stable lexical node identifiers.", encoder="render_gg", validator="validate_gg_max", headers=("#gg_lex",), encoder_options=(("lexical", True),), priority_aware=True),
    _target("gg_lex_hybrid", 20, "~1.6x", "Lexical-id gg plus inline grounded node facts.", encoder="render_gg", validator="validate_gg_max", capabilities=("topology", "facts", "stable_identity"), headers=("#gg_lex_hybrid",), encoder_options=(("lexical", True), ("facts", True)), priority_aware=True),
    _target("svo", 0, "~1.1x", "Self-describing subject-verb-object triples.", encoder="render_svo", validator="validate_svo", capabilities=("topology", "label_identity"), headers=("#svo",), identity=IdentityModel("label", True)),
    _target("doc_summary", 2, "~0.6x", "Grounded document sections and notes without topology.", encoder="render_doc_summary", validator="validate_doc_summary", capabilities=("grounded_documents", "facts"), headers=("[d]",)),
)

TARGET_NAMES: tuple[str, ...] = tuple(spec.name for spec in TARGET_SPECS)
TARGET_TABLE: tuple[dict[str, object], ...] = tuple(spec.as_public_dict() for spec in TARGET_SPECS)
_TARGET_BY_NAME = {spec.name: spec for spec in TARGET_SPECS}


def target_spec(name: str) -> TargetSpec:
    try:
        return _TARGET_BY_NAME[name]
    except KeyError:
        raise ValueError(f"unknown packet target: {name}") from None


def detect_target(packet: str) -> TargetSpec | None:
    lines = tuple(line.strip() for line in packet.strip().splitlines() if line.strip())
    for spec in TARGET_SPECS:
        if any(header in lines for header in spec.headers):
            return spec
        if any(any(line.startswith(prefix) for line in lines) for prefix in spec.line_prefixes):
            return spec
    for spec in TARGET_SPECS:
        if any(marker in lines for marker in spec.fallback_markers):
            return spec
    return None


def packet_format_schema(*, default: str | None = None) -> dict[str, object]:
    schema: dict[str, object] = {
        "type": "string",
        "enum": list(TARGET_NAMES),
        "description": "Packet format override. Supported formats: " + ", ".join(TARGET_NAMES) + ".",
    }
    if default is not None:
        schema["default"] = default
    return schema


def packet_format_markdown_table() -> str:
    rows = ["| Packet | Relative tokens | Use |", "| --- | ---: | --- |"]
    rows.extend(
        f"| `{spec.name}` | {spec.relative_tokens} | {spec.description} |"
        for spec in TARGET_SPECS
    )
    return "\n".join(rows)


__all__ = [
    "TARGET_NAMES",
    "TARGET_SPECS",
    "TARGET_TABLE",
    "FunctionRef",
    "IdentityModel",
    "SelectionPolicy",
    "TargetSpec",
    "TokenCostModel",
    "detect_target",
    "packet_format_markdown_table",
    "packet_format_schema",
    "target_spec",
]
