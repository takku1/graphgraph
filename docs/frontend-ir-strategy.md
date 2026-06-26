# Frontend And IR Strategy

`graphgraph` should not pretend that one shallow parser can precisely understand
all programming languages. Precision needs per-language frontends. The important
architecture choice is where language-specific logic ends.

## Direction

Use layered extraction:

1. **Regex baseline**: dependency-free, fast, useful for bootstrap scans.
2. **Tree-sitter frontend**: per-language CST parsing with high-confidence
   definitions, imports, calls, and structural edges.
3. **CPG-style IR layer**: optional deeper semantic graph for control flow,
   data flow, type relations, and security/static-analysis queries.
4. **Unified graphgraph IR**: all frontends normalize into the same `Node`,
   `Edge`, metadata, provenance, confidence, temporal, and ontology fields.

The backend must stay stable even if extraction improves.

## Why Not Only Regex

Regex extraction is useful and fast, but it cannot fully understand:

- Rust generics and trait bounds,
- Python decorators and dynamic imports,
- TypeScript type/value namespace differences,
- Go interfaces and method sets,
- control flow and data flow.

Regex edges should therefore carry lower provenance confidence, e.g.
`regex_ast` or `regex_reference`.

## Why Not Only Tree-sitter

Tree-sitter gives accurate syntax, not a full semantic model. It does not by
itself give complete type resolution, interprocedural data flow, or build-system
aware dependency resolution. Those belong in a CPG-style semantic layer.

## IR Contract

Frontends should emit:

- node identity, kind, source location, parent/scope,
- edge type from the relation ontology,
- direction and weight,
- provenance such as `regex_ast`, `tree_sitter`, `cpg`, `semantic_llm`,
- confidence,
- temporal validity where applicable,
- source anchors for grounding.

Retrieval should prefer high-confidence structural edges but keep weak edges as
latent recall hints.

## Practical Next Step

The extractor boundary now exists:

- `Extractor` protocol
- `RegexExtractor`
- `TreeSitterExtractor`
- `select_extractor()`

`scan --depth symbols` uses the selector. It chooses Tree-sitter when installed
with supported grammars and falls back to regex otherwise.

You can force a frontend:

```powershell
python -m graphgraph scan --depth symbols --frontend tree_sitter
python -m graphgraph scan --depth symbols --frontend regex
```

Recommended policy:

- use `tree_sitter` for precision scans,
- use `regex` as zero-dependency fallback and broad recall baseline,
- use `auto` for normal agent workflows.

Install optional Tree-sitter support:

```powershell
pip install -e ".[tree-sitter]"
```

Tree-sitter extraction currently targets definitions, `contains`, `calls`, and
Rust `implements` relationships. File-level imports still use graphgraph's
deterministic resolver.

Verified optional frontend behavior:

- Python: function/class definitions, `contains`, direct function `calls`.
- Rust: function/struct/enum/trait definitions, `contains`, direct function
  `calls`, `impl Trait for Type` as `implements`.

Unsupported or intentionally deferred:

- full type resolution,
- interprocedural data flow,
- control-flow graph extraction,
- build-system-aware module resolution.

Those belong in the planned CPG-style layer, not in the first Tree-sitter pass.
