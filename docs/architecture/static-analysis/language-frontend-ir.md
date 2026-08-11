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

Every frontend now receives an immutable, versioned `SourceIR`. Tree-sitter
compiles that revision into a bounded content-addressed `SyntaxIR`; optional
CPG evidence consumes the same resident tree instead of reparsing unchanged
bytes. Receipt fields distinguish newly compiled syntax artifacts from reused
ones, so reuse and eviction remain observable rather than inferred.

The separate incremental CPG evidence provider now adds conservative
intraprocedural reads, writes, control blocks, fields, declared types, and
return types across the installed language pack. These relations normalize
into GraphGraph IR and carry provenance, confidence, evidence, and source
locations; they are not added to every base scan automatically.

Verified optional frontend behavior:

- Python: function/class definitions, `contains`, direct function `calls`.
- Rust: function/struct/enum/trait definitions, `contains`, direct function
  `calls`, `impl Trait for Type` as `implements`.

Unsupported or intentionally deferred:

- interprocedural data flow,
- executable basic-block control-flow graphs,
- build-system-aware module resolution.

Those require language compiler adapters beyond the implemented CST-based CPG
evidence layer; they do not belong in the low-latency scanner pass.

Type and alias analysis is no longer deferred. P02 shipped a bounded monotone
lattice in `scanner/frontends/type_facts.py`; see "Semantic derivation" below.

## Semantic derivation: where language-specific logic ends

Semantic inference belongs in a shared, language-neutral solver, not in each
frontend. That solver exists:

- `type_facts.py` is the evidence lattice — `unknown < concrete < ambiguous`,
  join is set union, so propagation is monotone and terminating. Only singleton
  facts project to receiver types; ambiguity abstains rather than guessing, and
  emits an explicit `depth_limit` / `unknown_root` / `ambiguous_root` /
  `unknown_field` / `ambiguous_field` / `ambiguous_target` receipt.
- `persistent_facts.py` is the file-incremental layer — each file contributes a
  finite fact set, project facts are the commutative join of those
  contributions, and a reverse-obligation relation identifies which unchanged
  files need re-joining.

Frontends should therefore emit *facts*, not resolved types. A frontend that
returns a flat `dict[str, str]` built with `setdefault` has encoded precedence
as merge order and cannot express a genuine conflict. Python routes through the
lattice; C#, C++, Rust, and TypeScript still build flat maps directly from
regex and bypass it. Closing that gap is Q02-D.

`persistent_facts.py` is language-neutral machinery with a hardcoded
`from .python import ...` dependency. Until that is parameterized over a
per-language fact provider, only Python has project-wide facts and exact
incremental re-joins; every other language sees one file at a time.

## External providers: what to adopt, what to avoid

This section records a measured evaluation, not a preference.

**Stack graphs is the validated model — do not depend on the code.** GitHub's
stack graphs proved that file-incremental, build-free name resolution works at
scale: per-file isolated subgraphs, joined, with resolution as path-finding,
powering Precise Code Navigation with no repository configuration and no CI
hook. That is the same shape as the fact-contribution/join design above. The
upstream repository was archived 2025-09-09 and its implementation is Rust,
so the paper (arXiv 2211.01224) and model are the reference, not the dependency.

**SCIP is a batch artifact, not an edit-loop provider.** Measured on pinned
ripgrep `435f59f`, identical source:

| | graphgraph (tree_sitter) | rust-analyzer SCIP |
| --- | --- | --- |
| wall time | 5.7 s | 31.8 s |
| artifact | 1.65 MB | 8.25 MB |
| resolved method-call sites | 1,308 | 10,514 internal method refs |
| external | 2,111 external-or-unmatched | 23,282, each precisely named |

SCIP resolves substantially more (counting bases differ; a positional per-site
join was not run, so treat the ratio as directional). But `rust-analyzer scip`
is a whole-index one-shot with no incremental mode: 31.8 s against the Q02-C
affected-key re-join p95 of 0.1387 ms. SCIP cannot ride the edit loop, and the
edit loop is the product. Ingest SCIP opportunistically when an index already
exists; never place it on the interactive path. This mirrors Glean's documented
hybrid ingestion model: native language indexers alongside SCIP/LSIF importers.

Two further limits: SCIP publishes rich protocol bindings only for Go and Rust
(TypeScript and Haskell are generated, Python has none), and `local N` symbols
carry no stable identity — 25,597 occurrences on ripgrep — so SCIP is not a
complete substitute for local inference even where it is used.

**C++ is the one bucket where a SCIP provider is justified.** The five
prerequisites recorded in the Q02-D C++ hold — qualified owner/name/overload
identity, macro-vs-declaration-vs-definition, translation-unit visibility, and
bare-call resolution against lexical owner rather than project-global leaf
uniqueness — are satisfied by a compile-database-driven indexer essentially by
construction. C++ sits at 0.045 % resolution and the structural experiment was
reverted over exactly the namespace-collision and overload-uniqueness failures
a compiler does not make. Batch-only is acceptable there: a C++ repository with
a compile database already has a build step.

Adopt SCIP's **global symbol identity grammar** at the provider boundary for
package/namespace/type/member symbols. Retain GraphGraph's path/span-derived
identity for locals and map SCIP `local N` IDs as artifact-scoped aliases; they
cannot be durable project IDs. The global grammar is cheap and reversible, and
the format moved to independent governance in March 2026 (steering committee
from Meta, Uber, and Sourcegraph), so it is interop currency rather than a
single-vendor bet. Keep that decision separate from adopting SCIP *indexers*,
which carry the build requirement.

Souffle/Datalog is not indicated on the interactive path: the existing worklist
is already incremental, while a whole-program fixed-point dependency would add
startup and integration cost before a measured solver bottleneck exists. LSP is
session-oriented and is the wrong primary shape for persistent repository
indexing.

## Incremental equivalence: observed Rust loss fixed, universal proof remains

The initial reproduction showed that `update_paths` did not reproduce every
edge a full scan produced for the same file. On pinned ripgrep `435f59f`, with
**no source change at all**:

```
graphgraph scan   -d . --depth symbols --frontend tree_sitter   # 13,138 edges
graphgraph update -d . --files crates/core/main.rs              # 13,133 edges
```

The delta contains `delete_edge_keys: 5`, `upsert_edges: 0`. All five are owned
by the re-extracted file — `references` 19 -> 15 and `calls` 43 -> 42 for
`main.rs`-sourced edges, with zero gained. Four target other files
(`HiArgs::mode`, `StandardImpl::wtr`); one is intra-file (`run -> special`).
The base `graph.gg` stays byte-identical; the loss lives in `graph.gg.delta`,
so comparing base files alone will not reveal it.

The exact no-op route is now closed before extraction. `update_paths` partitions
requested paths by manifest hash and extraction configuration, returns the
already-loaded graph when both changed and removed sets are empty, and the
validated lifecycle emits `built=false` without writing a delta. The proof is
`test_identical_exact_path_update_is_graph_identity_noop` plus
`test_validated_identical_update_reports_no_write`. A manifest is trusted for
this decision only when its recorded source root matches the requested root;
missing or relocated state stays on the repair and catastrophic-shrink path.

Before that gate, the loss was per-file and non-compounding for a repeated
update of the same file, but each newly touched file shed its own set:
`main.rs` -5, `flags/parse.rs` -3, `printer/src/standard.rs` -2.

The changed-file case is not hypothetical and is **not** closed by the no-op
gate. Appending one unrelated function to `crates/core/main.rs` on pinned
ripgrep, then comparing a targeted update against a clean scan of the
already-edited tree:

```
clean scan of edited tree : 13,139 edges
update_paths after edit   : 13,134 edges   (lost 5, gained 0)
```

The five were the identical set listed above. The no-op short-circuit removed
the unchanged case but, by itself, did not repair generation after a real edit.

**Use a clean scan as the equivalence oracle, never an incremental rescan.**
`scan_directory(previous_graph_path=...)` restores unchanged files from the
manifest and therefore shares the targeted path's loss: measured against each
other the two agree exactly (13,134 == 13,134) and the defect is invisible.
Only a scan with no prior graph and no prior manifest is a valid oracle. The
pre-existing `test_update_paths_matches_full_rescan_including_cross_file_calls`
used `previous_graph_path=` for its "full rescan," so it could not detect this
class of loss. It now uses a clean oracle, and a Rust-specific clean-versus-
incremental regression covers a derived-field name collision.

The root cause was not missing Rust type facts. Clean extraction built its
name index from CST definitions before derived Rust fields existed and skipped
names shorter than three characters. Incremental extraction indexed every
restored context node, including generated fields such as `special`, `mode`,
and `wtr`. Those extra candidates made the same-named callable falsely
ambiguous, suppressing the four weak references and the `run -> special` call.

The repaired context projection now uses the clean path's domain:

```text
eligible(node) = context_symbol(node)
              and node.kind != field
              and len(node.label) > 2
```

Call-site facts are also sorted before edge projection so duplicate semantic
edges retain deterministic receiver evidence across processes. Shared registry
concept nodes no longer store whichever contributor happened to be visited
last; that provenance remains on their incoming edges.

Verification on the available ripgrep `227381d` fixture after adding an
unrelated function to `crates/core/main.rs`:

```text
clean scan of edited tree : 4,216 nodes, 12,516 edges
update_paths after edit   : 4,216 nodes, 12,516 edges
exact edge delta          : 0 removed, 0 added
```

This closes the observed five-edge Rust failure, not universal incremental
equivalence. P07 still owns cross-language changed-file/deletion fixtures,
exact metadata equality, and the sub-100-ms pre-deserialization gate. The
project-wide fact-provider generalization remains necessary for semantic
changes whose obligations cross files; it is no longer claimed as the cause of
this particular loss.
