import sys
from pathlib import Path
sys.path.insert(0, str(Path("src").resolve()))
from graphgraph.io import load_any
from graphgraph.retrieval.context import retrieve_context
from graphgraph.planning import choose_packet, choose_packet_for_subgraph, plan_context

graph = load_any(Path("benchmarks/context_graph/out/locus/locus-native.json"))
query = "symbolic expression visitor condition visitor"
query_class = "subsystem_summary"

choice = choose_packet(query_class, query)
plan = plan_context(query_class, query, max_nodes=40, hops=choice.hops)
print("Plan node_budget:", plan.node_budget)
print("Plan:", plan)
