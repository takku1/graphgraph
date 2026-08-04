# Runtime Context Graph

`graphgraph` should not be only a static index. A useful AI context graph also
needs controlled evolution: new traces, expired facts, merged entities, policy
nodes, and feedback from agent runs.

The rule is: mutate the graph through typed operations, not arbitrary database
queries.

## Operation Layer

Native operation primitives currently include:

- `AddNode`
- `AddEdge`
- `ExpireEdge`
- `MergeEntity`
- `AddDecisionTrace`

These are intentionally small. They are the start of an auditable operation log
that can later support rollback, temporal snapshots, and replay.

Operation logs are JSONL via `append_operation()` and `read_operations()`. The
recommended default location is `.graphgraph/ops.jsonl`.

## Decision Traces

Decision traces are graph nodes with edges to the context they used:

- `decision_trace -> used_input -> source node`
- `decision_trace -> applied_policy -> policy node`

This records how an agent reached a conclusion without stuffing all chain of
thought into the graph. Store operational facts: inputs, policies, approvers,
timestamps, outcomes, and source anchors.

## Policy Nodes

Policies should exist both as selectable constraints and as graph nodes. This
allows traversal questions such as:

- which files does this policy constrain?
- which decision traces applied this policy?
- which subsystem has conflicting policies?

The prompt renderer can still emit compact policy packets. The graph store keeps
the richer governance structure.

Retrieval now surfaces matching policy nodes as `constrained_by` context when a
policy scope matches an included node path.

## Scope Boundaries

`Graph.expand()` and `query_context` support scope/path-prefix constraints. Use
this to prevent cross-domain leakage:

```powershell
python -m graphgraph query "auth blast radius" --scope server/auth
```

MCP `query_context` accepts `scopes`.

Decision traces linked by `used_input` or `applied_policy` are surfaced when
they cite context already retrieved.

## Better/Faster/Cleaner Direction

Near-term improvements:

1. Add `ApplyOperation`/`RollbackOperation` once operation IDs exist.
2. Add include-expired context mode for audit queries.
3. Add confidence thresholds per query class.
4. Expand relation ontology metadata from traversal weights into full typed
   retrieval policies.

## Temporal Views

Use point-in-time query views with:

```powershell
$env:PYTHONPATH='src'
python -m graphgraph query "auth policy" --as-of 2026-06-01T00:00:00Z
```

MCP `query_context` accepts the same `as_of` argument.

Do not put all metadata into prompt packets. Use metadata for retrieval,
ranking, trust, and audit; render it only when it changes the model's answer.
