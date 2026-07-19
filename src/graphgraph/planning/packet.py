from __future__ import annotations

from .budgets import is_doc_query
from .types import PacketChoice, SubgraphStats

# Empirically measured optimal (hops, packet) per query class. gg is the token
# floor for any non-empty structural graph; the exceptions are documented inline.
#   negative_query: hops=1 not 0, so the packet can prove connectivity rather
#     than reading every node as isolated (confirmed on a real repo).
_PACKET_BY_CLASS: dict[str, PacketChoice] = {
    "direct_lookup": PacketChoice(1, "gg", "1-hop direct lookups: gg is the measured token floor"),
    "reverse_lookup": PacketChoice(1, "gg", "1-hop reverse lookups: gg is the measured token floor"),
    "affected_tests": PacketChoice(2, "gg", "affected tests use 2-hop incoming execution/validation evidence"),
    "multi_hop_path": PacketChoice(2, "gg", "path queries need 2-hop topology; gg is the measured token floor"),
    "blast_radius": PacketChoice(2, "gg", "blast-radius needs 2-hop topology; gg is the measured token floor"),
    "subsystem_summary": PacketChoice(1, "gg", "subsystem summaries: gg is the measured token floor"),
    "spreading_activation": PacketChoice(2, "gg", "spreading activation leverages 2-step energy propagation; gg is the measured token floor"),
    "recent_changes": PacketChoice(1, "gg", "recent-changes queries need 1-hop commit/fixes evidence; gg is the measured token floor"),
    "negative_query": PacketChoice(1, "semantic_arrow", "negative queries need 1-hop evidence to actually prove connectivity, not just anchor existence"),
}
_DOC_PACKET = PacketChoice(1, "doc_summary", "documentation summaries need grounded snippets more than topology")
_DEFAULT_PACKET = PacketChoice(2, "gg_hybrid", "unknown query class: conservative 2-hop gg_hybrid")

# Structural classes keep their packet even when the query uses documentation
# vocabulary; the doc redirect applies only to the remaining classes.
_STRUCTURAL_FIRST = frozenset(
    {"direct_lookup", "reverse_lookup", "affected_tests", "multi_hop_path", "blast_radius"}
)


def choose_packet(query_class: str, query: str = "") -> PacketChoice:
    """Return the empirically measured optimal packet strategy per query class."""
    if query_class not in _STRUCTURAL_FIRST and is_doc_query(query_class, query):
        return _DOC_PACKET
    return _PACKET_BY_CLASS.get(query_class, _DEFAULT_PACKET)


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
