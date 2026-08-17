"""OW-AC-06: machine response must stay within 1.15× the evidence packet."""

from __future__ import annotations

import json
from typing import Any

from ..packets import estimate_tokens

DEFAULT_RESPONSE_PACKET_RATIO = 1.15

# JSON envelope keys a machine client may dispatch on. Pretty-print waste and
# advisory provenance may be dropped; these may not.
REQUIRED_JSON_ENVELOPE_KEYS = (
    "packet",
    "packet_format",
    "control",
    "anchors",
    "query_class",
    "routing",
    "retrieval",
    "workflow",
    "actionable",
    "source_snippets",
    "metrics",
)
ADVISORY_JSON_ENVELOPE_KEYS = ("message",)


def within_response_surface(
    response: str,
    packet: str,
    *,
    ratio: float = DEFAULT_RESPONSE_PACKET_RATIO,
) -> bool:
    packet_tokens = estimate_tokens(packet)
    if packet_tokens <= 0:
        return estimate_tokens(response) <= 0
    return estimate_tokens(response) <= ratio * packet_tokens


def clamp_response_to_packet_surface(
    response: str,
    packet: str,
    *,
    ratio: float = DEFAULT_RESPONSE_PACKET_RATIO,
    fallback: str | None = None,
) -> str:
    """Return ``response`` if it fits the packet budget; otherwise a fallback.

    Wrapper text (ROUTE/PLAN/ANCHORS, pretty JSON) is advisory. The evidence
    packet is the product. Exceeding 1.15x is a surface defect, not a reason
    to ship a fatter answer.

    ``fallback`` defaults to the bare ``packet``. Callers whose ``response``
    must stay valid JSON (e.g. ``json_output`` mode) pass a JSON-shaped
    fallback instead -- the bare packet is not JSON for every packet format
    (``svo``/``gg`` open with a ``#`` marker line), and swapping it in would
    break a caller that unconditionally parses the result as JSON.
    """
    if within_response_surface(response, packet, ratio=ratio):
        return response
    return packet if fallback is None else fallback


def compact_json(value: object) -> str:
    """Serialize a machine JSON envelope without presentation whitespace."""

    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def json_envelope_for_surface(
    payload: dict[str, Any],
    packet: str,
    *,
    ratio: float = DEFAULT_RESPONSE_PACKET_RATIO,
) -> str:
    """Compact JSON that keeps routing keys even when the 1.15× gate fires.

    Indentation is not evidence. Advisory fields may be dropped to meet the
    packet ratio. ``control``, ``anchors``, ``query_class``, and ``workflow``
    stay: a fallback that is valid JSON but missing those keys is a surface
    defect (OW-D-04).
    """

    candidate = dict(payload)
    dumped = compact_json(candidate)
    if within_response_surface(dumped, packet, ratio=ratio):
        return dumped

    dropped: list[str] = []
    for key in ADVISORY_JSON_ENVELOPE_KEYS:
        if key not in candidate:
            continue
        candidate.pop(key)
        dropped.append(key)
        dumped = compact_json(candidate)
        if within_response_surface(dumped, packet, ratio=ratio):
            break
    if dropped:
        workflow = candidate.setdefault("workflow", {})
        if isinstance(workflow, dict):
            workflow["surface"] = {"clamped": True, "dropped": dropped}
        dumped = compact_json(candidate)
    return dumped
