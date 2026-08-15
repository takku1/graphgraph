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
) -> str:
    """Return ``response`` if it fits the packet budget; otherwise the packet.

    Wrapper text (ROUTE/PLAN/ANCHORS, pretty JSON) is advisory. The evidence
    packet is the product. Exceeding 1.15× is a surface defect, not a reason
    to ship a fatter answer.
    """
    if within_response_surface(response, packet, ratio=ratio):
        return response
    return packet
