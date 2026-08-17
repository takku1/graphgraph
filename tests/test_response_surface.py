from graphgraph.packets import estimate_tokens
from graphgraph.services.response_surface import (
    clamp_response_to_packet_surface,
    compact_json,
    json_envelope_for_surface,
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


def test_json_envelope_keeps_control_and_anchors_when_pretty_print_would_clamp():
    packet = "N id=foo"
    payload = {
        "packet": packet,
        "packet_format": "gg",
        "control": "anchor=exact_fast_path gates=fresh:+",
        "anchors": [{"id": "foo", "label": "foo", "kind": "function", "path": "a.py", "line": 1, "score": 1.0, "reasons": []}],
        "query_class": "reverse_lookup",
        "routing": {"confidence": 1.0, "margin": 1.0, "reasons": ["exact"], "version": "v"},
        "retrieval": {"answerability": {"status": "ok"}, "padding": "x" * 400},
        "metrics": {"packet": {"nodes": 1}},
        "workflow": {"freshness": {"repository_fresh": True}},
        "actionable": {"status": "ok"},
    }
    pretty = __import__("json").dumps(payload, indent=2)
    assert estimate_tokens(pretty) > 1.15 * estimate_tokens(packet)

    rendered = json_envelope_for_surface(payload, packet)
    data = __import__("json").loads(rendered)
    assert data["packet"] == packet
    assert data["control"].startswith("anchor=")
    assert data["anchors"][0]["id"] == "foo"
    assert data["query_class"] == "reverse_lookup"
    assert data["workflow"]["freshness"]["repository_fresh"] is True
    assert data["retrieval"]["answerability"]["status"] == "ok"
    assert data["metrics"]["packet"]["nodes"] == 1
    assert rendered == compact_json(data)
