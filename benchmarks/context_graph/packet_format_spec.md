# Packet Format Spec

This file defines the candidate LLM-facing packets used by the benchmark.

The important principle: **storage format and prompt format are separate**.
Binary CSR, bitmap indexes, and SQLite tables are good machine formats. A normal
LLM API still needs text tokens, so we decode the retrieved subgraph into one of
these packets.

## GG-LL: Low-Level Graph Packet

Goal: smallest readable topology packet.

```text
<g>
<r>
1:calls
2:reads
</r>
<n>
N00001:AuthService
N00002:TokenStore
</n>
<a>
N00001,N00002,1,0.94
</a>
</g>
```

Semantics:

- `<r>` maps relation IDs to relation labels.
- `<n>` maps node IDs to node labels.
- `<a>` contains adjacency rows: `source,target,relation_id,weight`.
- Weight is a confidence/strength score.

This is the current prompt-token floor. It is not binary. It is compact text.

## GG-CSR: CSR-Like Prompt Packet

Goal: test whether sparse-array notation beats adjacency rows at larger sizes.

```text
N=N00001:AuthService,N00002:TokenStore
R=1:calls
CSR ptr=0,1,1
col=N00002
rel=1
w=0.94
```

CSR is likely better as a machine storage/query format than as a direct LLM
format. It may require more instruction overhead for models to decode.

## SQL Rows

Goal: explicit semantic anchors while staying compact.

```text
TABLE nodes: id,label,kind,path | N00001,AuthService,service,services/AuthService.md
TABLE edges: source,target,type,weight | N00001,N00002,calls,0.94
```

This is the first fallback if GG-LL causes model reasoning errors.

## Hybrid Packet

Goal: topology plus short source evidence.

```text
Relevant relationships:
- AuthService (N00001) calls TokenStore (N00002); weight=0.94
Grounding snippets:
- AuthService: owns login token issue.
```

This costs more tokens but should be better for factual answers and citations.

## Caching Note

The schema explanation should be placed in a stable system/developer prefix when
using provider prompt caching. The benchmark therefore reports:

- **uncached prompt tokens**: schema + question + packet
- **cached prompt tokens**: question + packet only

## Round-Trip Requirement

Before using a packet in live model tests, the deterministic parser must be able
to reconstruct the intended node and edge evidence from the packet. Run:

```powershell
python benchmarks\context_graph\packet_roundtrip_validator.py
```

This catches packet formats that are compact but ambiguous or lossy.
