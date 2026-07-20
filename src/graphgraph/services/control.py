from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

CONTROL_VERSION = "ggc1"
GATE_ORDER = ("fresh", "route", "anchor", "evidence", "semantic", "packet")
_GATE_SYMBOLS = {True: "+", False: "-", None: "?"}
_SYMBOL_GATES = {symbol: value for value, symbol in _GATE_SYMBOLS.items()}
_FIELD_ORDER = (
    "op",
    "state",
    "next",
    "anchor",
    "h",
    "dir",
    "budget",
    "actual",
    "packet",
    "tokens",
    "gates",
)


@dataclass(frozen=True)
class ControlReceipt:
    """Lowest-form, self-contained execution receipt for an LLM boundary."""

    operation: str
    state: str
    next_action: str
    anchor: str
    hops: int
    direction: str
    node_budget: int | None
    nodes: int
    edges: int
    packet: str
    packet_tokens: int
    gates: tuple[tuple[str, bool | None], ...]
    version: str = CONTROL_VERSION


def choose_next_action(state: str, gates: Mapping[str, bool | None]) -> str:
    """Compile ordered gate outcomes into one agent action."""
    if gates.get("fresh") is False:
        return "refresh"
    if gates.get("packet") is False or gates.get("semantic") is False:
        return "repair"
    if gates.get("route") is False:
        return "retry_narrow"
    if gates.get("anchor") is False or state == "unanswerable":
        return "abstain"
    if gates.get("evidence") is False or state == "incomplete":
        return "retry_narrow"
    return "answer"


def render_control_ir(receipt: ControlReceipt) -> str:
    """Render fixed-order semantic microcode without an external codebook."""
    gates = ",".join(
        f"{name}:{_GATE_SYMBOLS[value]}"
        for name, value in receipt.gates
    )
    budget = "auto" if receipt.node_budget is None else str(receipt.node_budget)
    packet = receipt.packet or "none"
    return (
        f"{receipt.version} op={receipt.operation} state={receipt.state} "
        f"next={receipt.next_action} anchor={receipt.anchor} h={receipt.hops} "
        f"dir={receipt.direction} budget={budget} actual={receipt.nodes}/{receipt.edges} "
        f"packet={packet} tokens={receipt.packet_tokens} gates={gates}"
    )


def parse_control_ir(value: str) -> ControlReceipt:
    """Parse and validate the fixed GraphGraph control instruction."""
    parts = value.strip().split()
    if not parts or parts[0] != CONTROL_VERSION:
        raise ValueError(f"unsupported control receipt version: {parts[0] if parts else '<empty>'}")
    fields: dict[str, str] = {}
    for part in parts[1:]:
        if "=" not in part:
            raise ValueError(f"invalid control field: {part}")
        key, raw = part.split("=", 1)
        if key in fields:
            raise ValueError(f"duplicate control field: {key}")
        fields[key] = raw
    if tuple(fields) != _FIELD_ORDER:
        raise ValueError(
            f"control fields must be fixed-order {_FIELD_ORDER}, got {tuple(fields)}"
        )
    try:
        nodes, edges = (int(item) for item in fields["actual"].split("/", 1))
        gates = tuple(
            (name, _SYMBOL_GATES[symbol])
            for item in fields["gates"].split(",")
            for name, symbol in (item.split(":", 1),)
        )
    except (KeyError, ValueError) as exc:
        raise ValueError(f"invalid control receipt values: {exc}") from exc
    if tuple(name for name, _value in gates) != GATE_ORDER:
        raise ValueError(
            f"control gates must be fixed-order {GATE_ORDER}, "
            f"got {tuple(name for name, _value in gates)}"
        )
    return ControlReceipt(
        operation=fields["op"],
        state=fields["state"],
        next_action=fields["next"],
        anchor=fields["anchor"],
        hops=int(fields["h"]),
        direction=fields["dir"],
        node_budget=None if fields["budget"] == "auto" else int(fields["budget"]),
        nodes=nodes,
        edges=edges,
        packet="" if fields["packet"] == "none" else fields["packet"],
        packet_tokens=int(fields["tokens"]),
        gates=gates,
    )
