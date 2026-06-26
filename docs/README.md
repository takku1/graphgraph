# graphgraph Docs

`graphgraph` is an empirical lab and early implementation for one question:

> What is the cheapest context representation an LLM can reliably interpret?

The current answer is not a universal winner. The measured shape is:

1. store rich context as structured records,
2. retrieve a narrow graph neighborhood,
3. render the LLM-facing packet with the cheapest passing format,
4. add only scoped policy constraints,
5. validate packets mechanically before live model-answer scoring.

## Docs

- [Empirical Findings](empirical-findings.md)
- [Architecture](architecture.md)
- [LLM Connection Strategy](llm-connection-strategy.md)
- [Integration Surfaces](integration-surfaces.md)

## Benchmarks

The empirical source of truth lives under:

- `benchmarks/context_graph/`

Key generated reports:

- `benchmarks/context_graph/out/format_results.md`
- `benchmarks/context_graph/out/protocol/adaptive_policy_report.md`
- `benchmarks/context_graph/out/protocol/final_packets/final_packet_summary.md`
- `benchmarks/context_graph/out/protocol/source_routes/source_route_summary.md`
- `benchmarks/context_graph/out/protocol/constraints/constraint_context_summary.md`

## Tests

```powershell
$env:PYTHONPATH="src"
python -m unittest discover -s tests
```
