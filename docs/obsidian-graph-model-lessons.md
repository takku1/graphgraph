# Obsidian graph-model lessons for GraphGraph

Date: 2026-07-20

## Research boundary

Obsidian is proprietary. Its public help documents the graph's behavior and
controls, but it does not identify the exact layout implementation. Claims
about a particular Obsidian renderer, numerical integrator, or force library
would therefore be speculation.

The documented model is intentionally small:

- notes are nodes and internal links are edges;
- inbound-link count affects displayed node size;
- filters can include or exclude unresolved notes, orphans, tags, attachments,
  and search-query groups;
- the local graph is a breadth expansion from the active note with adjustable
  depth;
- the visual layer exposes center, repel, link, and link-distance controls.

Source: [Obsidian Graph view help](https://obsidian.md/help/Plugins/Graph%2Bview).

The public plugin API separates the vault from a derived `MetadataCache`.
Cached metadata includes links, embeds, tags, headings, and blocks. It exposes
`resolvedLinks` and `unresolvedLinks` separately as source-to-destination count
maps and emits index/resolve lifecycle events.

Sources:

- [Obsidian API architecture](https://github.com/obsidianmd/obsidian-api#app-architecture)
- [MetadataCache type definitions](https://raw.githubusercontent.com/obsidianmd/obsidian-api/master/obsidian.d.ts)

## Force-layout mathematics

Obsidian's documented controls are consistent with the general
spring-electrical family of force-directed layouts, but they do not prove which
member of that family Obsidian uses.

A common reference model is Fruchterman-Reingold. For distance \(d\) and ideal
spacing \(k\), its characteristic force magnitudes are:

\[
f_a(d) = \frac{d^2}{k}
\]

\[
f_r(d) = \frac{k^2}{d}
\]

Attractive edge forces shorten long links; repulsive node forces keep unrelated
nodes apart. Iteration plus cooling seeks a readable drawing rather than an
exact global optimum.

Source: [Fruchterman and Reingold, “Graph drawing by force-directed
placement”](https://doi.org/10.1002/spe.4380211102).

D3's public force engine illustrates a modern implementation shape: a
velocity-Verlet integrator applies named center/link/many-body forces, velocity
decay damps oscillation, and Barnes-Hut quadtree approximation reduces
many-body work to approximately \(O(n \log n)\) per application.

Sources:

- [D3 force simulation](https://d3js.org/d3-force/simulation)
- [D3 many-body force](https://d3js.org/d3-force/many-body)

This mathematics is useful for visualization. It is not a retrieval-ranking
formula: geometric proximity after a force simulation is layout-dependent and
must not be promoted to semantic or dependency evidence.

## Comparison with GraphGraph

| Obsidian pattern | GraphGraph equivalent | Decision |
| --- | --- | --- |
| Files are source of truth | Source tree is source of truth | Keep |
| Metadata cache | Manifest plus cached search, adjacency, and PageRank state | Keep |
| Resolved/unresolved link maps | Resolved/ambiguous/unknown/unresolved extraction receipts | Keep explicit receipt states |
| Adjustable local-graph depth | Query-class hop plan and bounded expansion | Keep |
| Search filters and groups | Scope, relation policy, facets, and packet selection | Keep before expansion/packing |
| Degree-sized visual nodes | Typed traversal strength plus confidence and bounded PPR | Do not substitute raw degree |
| Force-directed positions | No retrieval equivalent | Do not add to the core |

## Resulting storage decision

Obsidian reinforces a useful separation: one authoritative content layer,
derived caches, and optional views. Applied to GraphGraph:

```text
source
  -> canonical Graph IR
  -> binary .graphgraph/graph.gg
  -> cached adjacency/search/ranking state
  -> bounded local packet
  -> JSON control receipt
```

Graph JSON, `.ggb`, legacy text `.gg`, CSV, and TSV remain explicit
interchange or migration inputs. They are not competing native stores.

On the 2026-07-20 GraphGraph self-index (7,080 nodes and 25,643 edges), the old
binary-save validation path materialized 15,628,939 bytes of JSON and took
508.97 ms. Direct validation of the same in-memory graph took 5.60 ms, a 90.9x
validation-stage speedup before the binary write. Both paths produced the same
structural verdict.

Unresolved references should remain observable in extraction and quality
receipts. Materializing every unresolved call as a graph node would enlarge
packets and create false structural certainty, so it should happen only when a
frontend can emit a stable target identity and explicit unresolved provenance.

## Conclusion

The useful lesson from Obsidian is not its force layout. It is the clean
separation between source files, a link metadata cache, bounded local views,
and presentation. GraphGraph already follows that structure; consolidating
native persistence on `.gg` removes the remaining competing-store ambiguity.
