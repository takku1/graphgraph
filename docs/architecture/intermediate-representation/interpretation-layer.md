# Interpretation Layer

GraphGraph now separates generic document concepts from typed interpretation
concepts. Generic `concept` nodes remain useful for orientation, but they are
not enough for algorithmic and mathematical retrieval. Interpretation concepts
are registry-backed nodes with stable IDs, typed `kind` values, and facts that
describe their role in the context engine.

## Layers

The intended stack is:

1. **Source layer**: files, symbols, imports, AST-style containment, and docs.
2. **Interpretation layer**: known algorithms, math concepts, runtime concepts,
   and model-facing structures such as PageRank, tree knapsack DP, regularized
   utility budgeting, MCTS, and geodesic attention bias tensors.
3. **IR/execution layer**: call graph, control flow, data flow, type relations,
   and future CPG-style extraction.
4. **Packet layer**: `gg`, `semantic_arrow`, `lowlevel`, `doc_summary`, and
   other model-facing serializations.
5. **Runtime/hardware layer**: token layout, KV-cache stability, attention bias,
   and tensor-shaped graph representations.

## Graph Representation

Interpretation concepts use dedicated node kinds such as:

- `algorithm`
- `math_concept`
- `runtime_concept`

Documents connect to them with:

- `formalizes`: a section grounds a known algorithm, formula, runtime, or
  model-interpretation concept.

Source nodes connect to them with:

- `implements_algorithm`: a source file or symbol implements a known algorithmic
  or mathematical concept.

This keeps the graph honest: a concept is not treated as weight-bearing just
because a document mentioned it. It becomes weight-bearing when code links to it,
tests exercise it, or benchmarks show retrieval benefit.

## Regression Gates

Changes to this layer should pass:

- unit tests for deterministic concept detection and graph edges;
- full `python -m pytest`;
- live graph validation via `graphgraph status --probe`;
- local real-project smoke/eval benchmarks;
- a regenerated `.graphgraph/graph.gg`.

The target is better algorithmic retrieval and packet interpretation, not a
larger concept cloud.
