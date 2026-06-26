# Relation Ontology

Typed edges are the difference between a context graph and a noisy shape.

`graphgraph` keeps relation semantics in `src/graphgraph/ontology.py`. Each
relation has:

- `family`
- `direction`
- `strength`
- `traversable`
- `weak`
- optional inverse/description fields

Traversal uses relation strength as a multiplier alongside edge `weight` and
edge `confidence`. Retrieval uses the `weak` flag to cap noisy evidence such as
identifier mentions.

Inspect the ontology:

```powershell
$env:PYTHONPATH='src'
python -m graphgraph ontology
python -m graphgraph ontology --family execution
```

MCP clients can call `describe_ontology`.

## Design Rule

Do not treat all relations equally:

- `calls`, `imports`, `implements`, `reads`, and `writes` are strong structural
  signals.
- `contains` is hierarchical and useful, but it can dominate packets if not
  budgeted.
- `references`, `links`, `similar_to`, and unknown imported relations are weak
  retrieval hints.
- `contradicts` and `supports` are logic/evidence relations and should affect
  answer confidence more than neighborhood expansion.

Future work should move from simple strengths to query-class-specific traversal
policies.
