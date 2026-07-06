import sys
from pathlib import Path

sys.path.insert(0, str(Path("src").resolve()))
from graphgraph.doccode import doc_code_bias
from graphgraph.io import load_any
from graphgraph.planning.budgets import doc_intensity_score
from graphgraph.retrieval.context import select_anchor_matches
from graphgraph.retrieval.search import search_nodes

graph = load_any(Path("benchmarks/context_graph/out/locus/locus-native.json"))
query = "locus README installation usage"
query_class = "subsystem_summary"
anchor_limit = 6

base_score = doc_intensity_score(query_class, query)
bias = doc_code_bias(graph)
final_score = base_score * (0.75 + bias * 0.5)

matches = search_nodes(graph, query, limit=50, doc_intensity=final_score, personalize=True)
selected = select_anchor_matches(matches, anchor_limit, query_class, doc_intent=True)

print("Selected matches with personalize=True after fix:")
for m in selected:
    print(f"  {m.node.id}: score={m.score:.4f}, label={m.node.label}, kind={m.node.kind}")
