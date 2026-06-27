from __future__ import annotations

from .budgets import is_doc_query
from .types import PacketChoice, SubgraphStats


def choose_packet(query_class: str, query: str = "") -> PacketChoice:
    """Return the empirically measured optimal packet strategy per query class."""
    if query_class == "direct_lookup":
        return PacketChoice(1, "gg_max", "1-hop direct lookups: gg_max is the measured token floor")
    if query_class == "reverse_lookup":
        return PacketChoice(1, "gg_max", "1-hop reverse lookups: gg_max is the measured token floor")
    if query_class == "multi_hop_path":
        return PacketChoice(2, "gg_max", "path queries need 2-hop topology; gg_max is the token floor")
    if query_class == "blast_radius":
        return PacketChoice(2, "gg_max", "blast-radius needs 2-hop topology; gg_max is the token floor")
    if is_doc_query(query_class, query):
        return PacketChoice(1, "doc_summary", "documentation summaries need grounded snippets more than topology")
    if query_class == "subsystem_summary":
        return PacketChoice(1, "gg_max", "subsystem summaries: gg_max is the current structural token floor")
    if query_class == "spreading_activation":
        return PacketChoice(2, "gg_max", "spreading activation leverages 2-step energy propagation; gg_max is the floor")
    if query_class == "negative_query":
        return PacketChoice(0, "semantic_arrow", "negative queries need anchor evidence without pulling unrelated edges")
    return PacketChoice(2, "gg_max", "unknown query class: conservative 2-hop gg_max")


def refine_packet_for_subgraph(choice: PacketChoice, edge_count: int) -> PacketChoice:
    from .stats import estimate_packet_tokens

    stats = SubgraphStats(
        nodes=0,
        edges=edge_count,
        density=0.0,
        factful_node_ratio=0.0,
        relation_entropy=0.0,
        weak_edge_ratio=0.0,
        estimated_tokens_by_packet=estimate_packet_tokens(0, edge_count),
    )
    return choose_packet_for_subgraph(choice, stats)


def choose_packet_for_subgraph(choice: PacketChoice, stats: SubgraphStats, query_class: str = "") -> PacketChoice:
    """Apply measured post-retrieval packet refinements.

    Real-project sweeps show semantic_arrow only beats gg_max when the retrieved
    subgraph has zero edges. For any non-empty structural graph, gg_max remains
    the token floor. The helper keeps docs/explicit formats unchanged.
    """
    if choice.packet in {"doc_summary", "semantic_arrow"}:
        return choice
    if stats.edges == 0 and choice.packet == "gg_max":
        semantic_tokens = stats.estimated_tokens_by_packet.get("semantic_arrow", 0)
        gg_tokens = stats.estimated_tokens_by_packet.get("gg_max", 0)
        if semantic_tokens <= gg_tokens:
            return PacketChoice(choice.hops, "semantic_arrow", "zero-edge packets avoid gg_max relation-map overhead")
    if query_class == "subsystem_summary" and choice.packet == "gg_max" and stats.edges > 0:
        gg_tokens = stats.estimated_tokens_by_packet.get("gg_max", 0)
        hybrid_tokens = stats.estimated_tokens_by_packet.get("gg_max_hybrid", 0)
        bounded_premium = hybrid_tokens <= max(gg_tokens + 48, int(gg_tokens * 1.15))
        if stats.factful_node_ratio >= 0.5 and stats.weak_edge_ratio < 0.75 and bounded_premium:
            return PacketChoice(choice.hops, "gg_max_hybrid", "fact-rich subsystem summary keeps bounded inline evidence")
    return choice
