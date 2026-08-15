from graphgraph.packets import estimate_tokens
from graphgraph.services.response_surface import (
    clamp_response_to_packet_surface,
    within_response_surface,
)


def test_wrapper_within_ratio_is_kept():
    packet = "\n".join(
        f"N id=node_{i} kind=function path=src/module_{i}.py"
        for i in range(40)
    )
    response = f"ROUTE: lookup\n\n{packet}"
    assert within_response_surface(response, packet)
    assert clamp_response_to_packet_surface(response, packet) == response


def test_wrapper_over_ratio_falls_back_to_packet():
    packet = "N id=foo"
    response = ("ANCHOR " * 80) + packet
    assert estimate_tokens(response) > 1.15 * estimate_tokens(packet)
    assert not within_response_surface(response, packet)
    assert clamp_response_to_packet_surface(response, packet) == packet
