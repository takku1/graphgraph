# GraphGraph

GraphGraph compiles heterogeneous project evidence into a bounded, verifiable context artifact for machine reasoning.

## Language

**Evidence Graph**:
The canonical typed graph of observed, derived, and explicitly uncertain project evidence.
_Avoid_: Knowledge graph, semantic graph, topology graph

**Compile Request**:
An immutable statement of the context goal, constraints, and required capabilities.
_Avoid_: Graph program, query options, request payload

**Compile Outcome**:
The context packet and its machine-checkable receipt produced for one compile request.
_Avoid_: Compilation result, response, output

**Context Compiler**:
The module that transforms a compile request and evidence graph into a compile outcome.
_Avoid_: Graph runtime, query service, orchestration layer

**Compiler Pass**:
A declared transformation from required compiler artifacts to produced compiler artifacts.
_Avoid_: Stage, step, processor, hook

**Context Packet**:
The bounded LLM-facing encoding of selected evidence.
_Avoid_: Prompt, context blob, rendered graph

**Receipt**:
The machine-checkable account of evidence, decisions, loss, confidence, freshness, validation, and cost for an operation.
_Avoid_: Metadata, diagnostics, explanation

**Anchor**:
An evidence-graph node admitted as a retrieval seed for a compile request.
_Avoid_: Start node, root, match

**Freshness**:
The relation between an evidence-graph revision and its source state.
_Avoid_: Up-to-date flag, cache validity

**Abstention**:
An explicit outcome stating that the available evidence cannot satisfy the compile request under its constraints.
_Avoid_: Empty result, failure, no matches
