from __future__ import annotations

from .budgets import is_doc_query
from .types import PacketChoice, SubgraphStats


def choose_packet(query_class: str, query: str = "") -> PacketChoice:
    """Return the empirically measured optimal packet strategy per query class."""
    if query_class == "direct_lookup":
        return PacketChoice(1, "gg", "1-hop direct lookups: gg is the measured token floor")
    if query_class == "reverse_lookup":
        return PacketChoice(1, "gg", "1-hop reverse lookups: gg is the measured token floor")
    if query_class == "affected_tests":
        return PacketChoice(2, "gg", "affected tests use 2-hop incoming execution/validation evidence")
    if query_class == "multi_hop_path":
        return PacketChoice(2, "gg", "path queries need 2-hop topology; gg is the measured token floor")
    if query_class == "blast_radius":
        return PacketChoice(2, "gg", "blast-radius needs 2-hop topology; gg is the measured token floor")
    if is_doc_query(query_class, query):
        return PacketChoice(1, "doc_summary", "documentation summaries need grounded snippets more than topology")
    if query_class == "subsystem_summary":
        return PacketChoice(1, "gg", "subsystem summaries: gg is the measured token floor")
    if query_class == "spreading_activation":
        return PacketChoice(2, "gg", "spreading activation leverages 2-step energy propagation; gg is the measured token floor")
    if query_class == "recent_changes":
        return PacketChoice(1, "gg", "recent-changes queries need 1-hop commit/fixes evidence; gg is the measured token floor")
    if query_class == "negative_query":
        # hops=1, not 0: at hops=0 the packet can never show connectivity
        # evidence for *any* node regardless of the graph, so a query like
        # "is X isolated/unused" always reads as isolated even when X has
        # real callers -- confirmed on a real repo (an actively-called Rust
        # struct read as fully isolated). 1 hop is enough to prove real
        # usage exists while staying far short of a full expansion.
        return PacketChoice(1, "semantic_arrow", "negative queries need 1-hop evidence to actually prove connectivity, not just anchor existence")
    return PacketChoice(2, "gg_hybrid", "unknown query class: conservative 2-hop gg_hybrid")


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

    Real-project sweeps show semantic_arrow only beats gg/gg_hybrid when the retrieved
    subgraph has zero edges. For any non-empty structural graph, gg remains
    the token floor. The helper keeps docs/explicit formats unchanged.
    """
    if choice.packet in {"doc_summary", "semantic_arrow"}:
        return choice
    if stats.edges == 0 and choice.packet in {"gg", "gg_hybrid"}:
        semantic_tokens = stats.estimated_tokens_by_packet.get("semantic_arrow", 0)
        gg_tokens = stats.estimated_tokens_by_packet.get(choice.packet, 0)
        if semantic_tokens <= gg_tokens:
            return PacketChoice(choice.hops, "semantic_arrow", "zero-edge packets avoid gg relation-map overhead")
    return choice
