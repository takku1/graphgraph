# Context Compression and Packet Boundaries

This note records the architectural boundary between graph serialization,
retrieval policy, and runtime model execution. It only keeps claims that are
currently supported by code or benchmark output.

## Boundary

GraphGraph is responsible for:

- extracting nodes and edges into a shared graph IR,
- selecting a retrieval frontier,
- rendering a packet format,
- validating the packet mechanically before it is sent to a model.

GraphGraph is not responsible for:

- model quantization,
- prompt-cache implementation details,
- provider-specific reasoning internals.

Those layers can compound in production, but they should be measured
separately.

## Verified Claims

Current benchmarks support the following statements:

- `gg_max` is the current token floor for non-empty structural packets in the
  real-project packet-balance run.
- `semantic_arrow` is the cheaper winner only when the retrieved subgraph has
  zero edges.
- `gg_max_hybrid` is valid once the packet validator respects the packet
  header before scanning for `@nodes` inside grounded facts.
- the frontier policy is currently stronger after lowering `section_of`
  relative to `references`, which prevents structural sections from saturating
  the budget before code targets are reached.

See:

- [Architecture](./architecture.md)
- [Empirical Findings](./empirical-findings.md)
- [Real-project packet balance](../benchmarks/context_graph/out/real_projects/real_project_packet_balance.md)
- [Frontier policy benchmark](../benchmarks/context_graph/out/real_projects/frontier_policy_report.md)

## Practical Implication

The current production rule is:

1. prefer the cheapest packet that still preserves required evidence,
2. keep structural edges explicit,
3. add prose only when the graph packet is not enough on its own,
4. require validation before a packet is trusted as assistant context,
5. measure external model accuracy separately from token cost when the user
   explicitly asks for provider-backed benchmarking.

This is a conservative rule. It is not a universal theorem about LLMs or graph
representations.

## Open Questions

- whether lexicalized node handles beat numeric IDs once external model scoring
  is explicitly run,
- whether a sparse/dense dynamic context mode should be query-class specific,
- whether `gg_max_hybrid` should be promoted for doc-heavy prompts once
  external answer quality is measured,
- whether any packet format should change default behavior before live scoring
  exists.

The answer to all of the above is currently "not proven".
