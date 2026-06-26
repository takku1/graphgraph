# graphgraph

`graphgraph` is an empirical benchmark suite plus early Python package for
finding the cheapest graph/RAG context packet an LLM can still interpret.

The project currently proves deterministic pieces:

- compact graph packets are much cheaper than JSON/GraphML,
- source routes can compile into a shared node/edge IR,
- noisy prose loses edge recall unless the parser covers the phrasing,
- scoped policy constraints beat global prompt dumps,
- final packets should be chosen per query class.

Live model-answer accuracy is the next proof step.

## Run Benchmarks

```powershell
python benchmarks\context_graph\run_all.py
```

## Run Tests

```powershell
$env:PYTHONPATH="src"
python -m unittest discover -s tests
```

## Use The Package

```powershell
python -m graphgraph plan --query-class blast_radius
```

Validate a packet:

```powershell
$env:PYTHONPATH="src"
Get-Content packet.txt | python -m graphgraph validate
```

From a source checkout without installing:

```powershell
$env:PYTHONPATH="src"
python -m graphgraph plan --query-class blast_radius
```

Run the MCP stdio server:

```powershell
$env:PYTHONPATH="src"
python -m graphgraph.mcp_server
```

## Integration with Graphify

To seamlessly use `graphgraph` with `graphify` indexing outputs:

1. **One-line pipeline**:
   ```powershell
   graphify update . && graphgraph final --graph graphify-out/graph.json --query-class direct_lookup --starts "YourNode"
   ```
2. **Ingest and normalize third-party graphs**:
   Use the ingestion utility to align `graphify` output to the standard codebase graph schema:
   ```powershell
   graphgraph ingest --input graphify-out/graph.json --output graphify-out/normalized-graph.json
   ```

The unified graph contract is defined in [graph.schema.json](file:///C:/Users/dcarn/aiprojects/graphgraph/src/graphgraph/schema/graph.schema.json).

## Docs

- [Empirical Findings](file:///C:/Users/dcarn/aiprojects/graphgraph/docs/empirical-findings.md)
- [Architecture](file:///C:/Users/dcarn/aiprojects/graphgraph/docs/architecture.md)
- [LLM Connection Strategy](file:///C:/Users/dcarn/aiprojects/graphgraph/docs/llm-connection-strategy.md)
- [Schema Alignment](file:///C:/Users/dcarn/aiprojects/graphgraph/docs/schema-alignment.md)
- [Integration Surfaces](file:///C:/Users/dcarn/aiprojects/graphgraph/docs/integration-surfaces.md)

