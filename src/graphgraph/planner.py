from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PacketChoice:
    hops: int
    packet: str
    reason: str


def choose_packet(query_class: str) -> PacketChoice:
    """Return the empirically measured optimal packet strategy per query class.

    Source: benchmarks/context_graph empirical-findings.md — measured at 200 nodes / 265 edges.
    direct/reverse 1-hop: sql beats lowlevel because the relation-map overhead isn't worth it
    for tiny payloads; path/blast 2-hop: gg_max (evolved lowlevel) wins on token count while
    maintaining 100% recall; summary queries benefit from inline node facts via gg_max_hybrid.
    """
    if query_class == "direct_lookup":
        return PacketChoice(1, "sql", "1-hop direct lookups: sql row overhead < relation-map cost")
    if query_class == "reverse_lookup":
        return PacketChoice(1, "sql", "1-hop reverse lookups: sql row overhead < relation-map cost")
    if query_class == "multi_hop_path":
        return PacketChoice(2, "gg_max", "path queries need 2-hop topology; gg_max is the token floor")
    if query_class == "blast_radius":
        return PacketChoice(2, "gg_max", "blast-radius needs 2-hop topology; gg_max is the token floor")
    if query_class == "subsystem_summary":
        return PacketChoice(1, "gg_max_hybrid", "summary queries need inline node facts; hybrid adds minimal tokens")
    if query_class == "negative_query":
        return PacketChoice(1, "gg_max", "negative queries need topology only; gg_max 1-hop suffices")
    return PacketChoice(2, "gg_max", "unknown query class: conservative 2-hop gg_max")
