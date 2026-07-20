from __future__ import annotations

import json
import statistics
from dataclasses import asdict
from pathlib import Path
from typing import Callable

from graphgraph.packets import estimate_tokens
from graphgraph.services.control import (
    CONTROL_VERSION,
    GATE_ORDER,
    ControlReceipt,
    parse_control_ir,
    render_control_ir,
)

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "benchmarks" / "context_graph" / "out" / "control_receipt"


def _samples() -> tuple[ControlReceipt, ...]:
    base = {
        "anchor": "exact_fast_path",
        "hops": 1,
        "direction": "in",
        "node_budget": 12,
        "nodes": 7,
        "edges": 5,
        "packet": "gg",
        "packet_tokens": 214,
    }

    def receipt(
        operation: str,
        state: str,
        next_action: str,
        gate_values: tuple[bool | None, ...],
        **overrides: object,
    ) -> ControlReceipt:
        values = {**base, **overrides}
        return ControlReceipt(
            operation=operation,
            state=state,
            next_action=next_action,
            gates=tuple(zip(GATE_ORDER, gate_values, strict=True)),
            **values,
        )

    return (
        receipt("reverse_lookup", "answerable", "answer", (True, True, True, True, True, True)),
        receipt("subsystem_summary", "incomplete", "retry_narrow", (True, False, True, False, True, True)),
        receipt(
            "direct_lookup",
            "unanswerable",
            "abstain",
            (True, True, False, False, True, None),
            anchor="none",
            nodes=0,
            edges=0,
            packet="",
            packet_tokens=0,
        ),
        receipt("blast_radius", "answerable", "refresh", (False, True, True, True, True, True)),
        receipt("affected_tests", "incomplete", "repair", (True, True, True, False, False, True)),
        receipt("multi_hop_path", "answerable", "repair", (True, True, True, True, True, False)),
    )


def _from_flat(data: dict[str, object]) -> ControlReceipt:
    gates = data["gates"]
    assert isinstance(gates, dict)
    return ControlReceipt(
        operation=str(data["operation"]),
        state=str(data["state"]),
        next_action=str(data["next_action"]),
        anchor=str(data["anchor"]),
        hops=int(data["hops"]),
        direction=str(data["direction"]),
        node_budget=int(data["node_budget"]) if data["node_budget"] is not None else None,
        nodes=int(data["nodes"]),
        edges=int(data["edges"]),
        packet=str(data["packet"]),
        packet_tokens=int(data["packet_tokens"]),
        gates=tuple((name, gates[name]) for name in GATE_ORDER),
    )


def _flat_json(receipt: ControlReceipt) -> str:
    data = asdict(receipt)
    data["gates"] = dict(receipt.gates)
    return json.dumps(data, separators=(",", ":"), sort_keys=False)


def _parse_flat_json(value: str) -> ControlReceipt:
    return _from_flat(json.loads(value))


def _nested_json(receipt: ControlReceipt) -> str:
    return json.dumps(
        {
            "schema": {"version": receipt.version},
            "decision": {
                "operation": receipt.operation,
                "state": receipt.state,
                "next_action": receipt.next_action,
            },
            "retrieval_plan": {
                "anchor_strategy": receipt.anchor,
                "hops": receipt.hops,
                "direction": receipt.direction,
                "node_budget": receipt.node_budget,
                "packet_format": receipt.packet,
            },
            "packet_metrics": {
                "selected_nodes": receipt.nodes,
                "selected_edges": receipt.edges,
                "proxy_tokens": receipt.packet_tokens,
            },
            "decision_gates": dict(receipt.gates),
        },
        separators=(",", ":"),
    )


def _parse_nested_json(value: str) -> ControlReceipt:
    data = json.loads(value)
    decision = data["decision"]
    plan = data["retrieval_plan"]
    metrics = data["packet_metrics"]
    return ControlReceipt(
        operation=decision["operation"],
        state=decision["state"],
        next_action=decision["next_action"],
        anchor=plan["anchor_strategy"],
        hops=plan["hops"],
        direction=plan["direction"],
        node_budget=plan["node_budget"],
        nodes=metrics["selected_nodes"],
        edges=metrics["selected_edges"],
        packet=plan["packet_format"],
        packet_tokens=metrics["proxy_tokens"],
        gates=tuple((name, data["decision_gates"][name]) for name in GATE_ORDER),
    )


_OPERATION_CODES = {
    "reverse_lookup": "R",
    "subsystem_summary": "S",
    "direct_lookup": "D",
    "blast_radius": "B",
    "affected_tests": "T",
    "multi_hop_path": "M",
}
_STATE_CODES = {"answerable": "A", "incomplete": "I", "unanswerable": "U"}
_ACTION_CODES = {
    "answer": "A",
    "retry_narrow": "N",
    "abstain": "X",
    "refresh": "F",
    "repair": "R",
}
_ANCHOR_CODES = {"exact_fast_path": "E", "ranked": "R", "none": "N"}
_DIRECTION_CODES = {"in": "I", "out": "O", "both": "B"}
_PACKET_CODES = {"gg": "G", "": "N"}


def _opcode_ir(receipt: ControlReceipt) -> str:
    gate_bits = "".join("1" if value is True else "0" if value is False else "x" for _name, value in receipt.gates)
    budget = "x" if receipt.node_budget is None else str(receipt.node_budget)
    return (
        f"c1 q{_OPERATION_CODES[receipt.operation]}s{_STATE_CODES[receipt.state]}"
        f"n{_ACTION_CODES[receipt.next_action]}a{_ANCHOR_CODES[receipt.anchor]}"
        f"h{receipt.hops}d{_DIRECTION_CODES[receipt.direction]}b{budget}"
        f"v{receipt.nodes}/{receipt.edges}p{_PACKET_CODES[receipt.packet]}"
        f"t{receipt.packet_tokens}g{gate_bits}"
    )


def _parse_opcode_ir(value: str) -> ControlReceipt:
    # This intentionally requires the codebooks above. It is deterministic but
    # not self-contained for a model seeing the receipt without prior schema.
    import re

    match = re.fullmatch(
        r"c1 q(?P<q>.?)s(?P<s>.?)n(?P<n>.?)a(?P<a>.?)h(?P<h>\d+)"
        r"d(?P<d>.?)b(?P<b>\d+|x)v(?P<nodes>\d+)/(?P<edges>\d+)"
        r"p(?P<p>.?)t(?P<t>\d+)g(?P<g>[01x]{6})",
        value,
    )
    if match is None:
        raise ValueError("invalid opcode control receipt")
    reverse = lambda mapping, code: next(key for key, candidate in mapping.items() if candidate == code)
    return ControlReceipt(
        operation=reverse(_OPERATION_CODES, match["q"]),
        state=reverse(_STATE_CODES, match["s"]),
        next_action=reverse(_ACTION_CODES, match["n"]),
        anchor=reverse(_ANCHOR_CODES, match["a"]),
        hops=int(match["h"]),
        direction=reverse(_DIRECTION_CODES, match["d"]),
        node_budget=None if match["b"] == "x" else int(match["b"]),
        nodes=int(match["nodes"]),
        edges=int(match["edges"]),
        packet=reverse(_PACKET_CODES, match["p"]),
        packet_tokens=int(match["t"]),
        gates=tuple(
            (name, True if bit == "1" else False if bit == "0" else None)
            for name, bit in zip(GATE_ORDER, match["g"], strict=True)
        ),
    )


def _cl100k_count(value: str) -> int | None:
    try:
        import tiktoken
    except ImportError:
        return None
    return len(tiktoken.get_encoding("cl100k_base").encode(value))


def evaluate_candidates() -> dict[str, object]:
    samples = _samples()
    candidates: tuple[
        tuple[str, Callable[[ControlReceipt], str], Callable[[str], ControlReceipt], bool],
        ...,
    ] = (
        ("nested_json", _nested_json, _parse_nested_json, True),
        ("flat_json", _flat_json, _parse_flat_json, True),
        ("semantic_ir", render_control_ir, parse_control_ir, True),
        ("opcode_ir", _opcode_ir, _parse_opcode_ir, False),
    )
    rows: list[dict[str, object]] = []
    for name, encode, decode, self_contained in candidates:
        encoded = [encode(sample) for sample in samples]
        lossless = all(decode(value) == sample for value, sample in zip(encoded, samples, strict=True))
        cl100k = [_cl100k_count(value) for value in encoded]
        rows.append({
            "candidate": name,
            "lossless": lossless,
            "self_contained": self_contained,
            "mean_proxy_tokens": round(statistics.mean(estimate_tokens(value) for value in encoded), 3),
            "mean_cl100k_tokens": (
                round(statistics.mean(value for value in cl100k if value is not None), 3)
                if all(value is not None for value in cl100k)
                else None
            ),
            "mean_characters": round(statistics.mean(len(value) for value in encoded), 3),
        })
    eligible = [
        row for row in rows
        if row["lossless"] and row["self_contained"]
    ]
    winner = min(
        eligible,
        key=lambda row: (
            row["mean_proxy_tokens"],
            row["mean_cl100k_tokens"] or row["mean_proxy_tokens"],
            row["mean_characters"],
        ),
    )
    return {
        "version": CONTROL_VERSION,
        "winner": winner["candidate"],
        "selection_rule": (
            "hard-gate exact round-trip and no external codebook; "
            "then minimize deterministic proxy tokens, tokenizer tokens, and characters"
        ),
        "sample_states": len(samples),
        "candidates": rows,
    }


def _markdown(report: dict[str, object]) -> str:
    lines = [
        "# Control Receipt Benchmark",
        "",
        f"- Winner: `{report['winner']}`",
        f"- Selection: {report['selection_rule']}",
        f"- State fixtures: {report['sample_states']}",
        "",
        "| Candidate | Lossless | Self-contained | Proxy tokens | cl100k tokens | Characters |",
        "| --- | --- | --- | ---: | ---: | ---: |",
    ]
    for row in report["candidates"]:
        lines.append(
            f"| {row['candidate']} | {row['lossless']} | {row['self_contained']} | "
            f"{row['mean_proxy_tokens']} | {row['mean_cl100k_tokens'] or 'n/a'} | "
            f"{row['mean_characters']} |"
        )
    lines.extend([
        "",
        "The opcode candidate is reported as a lower bound, not promoted: its",
        "abbreviations require an external codebook and therefore move decoding",
        "work back onto the agent/model boundary.",
    ])
    return "\n".join(lines) + "\n"


def main() -> None:
    report = evaluate_candidates()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "control_receipt.json").write_text(
        json.dumps(report, indent=2),
        encoding="utf-8",
    )
    (OUT / "control_receipt.md").write_text(_markdown(report), encoding="utf-8")
    print(_markdown(report))


if __name__ == "__main__":
    main()
