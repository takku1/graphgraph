"""OW-AC-06: machine response must stay within 1.15× the evidence packet."""

from __future__ import annotations

from ..packets import estimate_tokens

DEFAULT_RESPONSE_PACKET_RATIO = 1.15


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
