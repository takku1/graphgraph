import sys
from pathlib import Path

sys.path.insert(0, str(Path("src").resolve()))
from graphgraph.io import load_any
from graphgraph.ontology import provenance_confidence, traversal_strength

graph = load_any(Path("benchmarks/context_graph/out/real_projects/graphs/herbie.json"))
node_id = "www_doc_html"
outgoing = graph.outgoing().get(node_id, [])
incoming = graph.incoming().get(node_id, [])

print(f"Outgoing edges from {node_id} ({len(outgoing)}):")
for edge in outgoing[:15]:
    mult = traversal_strength(edge.type)
    conf = edge.confidence * provenance_confidence(edge.provenance)
    print(f"  {edge.target} ({edge.type}): weight={edge.weight}, mult={mult}, conf={conf}")

print(f"\nIncoming edges to {node_id} ({len(incoming)}):")
for edge in incoming[:15]:
    mult = traversal_strength(edge.type)
    conf = edge.confidence * provenance_confidence(edge.provenance)
    print(f"  {edge.source} ({edge.type}): weight={edge.weight}, mult={mult}, conf={conf}")
