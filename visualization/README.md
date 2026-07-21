# visualization

Renders a GraphGraph graph as one self-contained 3D SVG image.

```bash
python visualization/build.py                              # this repo's graph
python visualization/build.py --graph ../other/.graphgraph/graph.gg
python visualization/build.py --rotate 60                  # spin the camera
python visualization/build.py --depth 2                    # coarser modules
```

Output: `visualization/graph.svg` — no scripts, no external requests, so it
opens in any browser or editor and can be embedded in a README directly.

## What it draws, and why that way

Symbols are aggregated to their **module**. A 7,000-node graph drawn one
sphere per symbol is a hairball that answers no question; ~20 modules shows
the actual shape of a codebase.

- **Sphere size** — symbol count in that module
- **Line thickness** — volume of structural references between two modules
  (`calls`, `imports`, `imports_from`, `implements`, `returns`, `references`)
- **Depth** — size, brightness, and occlusion. Positions come from a
  force-directed layout in three dimensions, projected with perspective;
  nearer modules are larger and brighter and are drawn last so they occlude.

Doc and concept relations are excluded deliberately. They are real edges, but
on a documentation-heavy graph they outnumber code relations and turn a
dependency picture into a fog.

## Reading it honestly

An absent line does not prove an absent dependency. Member calls only become
`calls` edges when the receiver's type can be determined, and that rate varies
by language — `graphgraph status` reports the current figure and the shape
breakdown of what went untyped. A module that looks isolated here may simply
be reached through receivers the resolver could not type.


## `--mode contrast` — what makes this graph different

```bash
python visualization/build.py --mode contrast --output visualization/contrast.svg
```

The structure view above is the picture every code-graph tool draws. This mode
exists to show the parts that are not standard, by rendering them rather than
claiming them.

- **Solid blue** — module pairs linked by code. This is the whole picture a
  dependency grapher produces.
- **Dashed amber** — module pairs linked *only* through prose, via
  `explains` / `discusses` / `mentions` edges between documentation and the
  code it describes. On this repository there are more of these than there are
  code-linked pairs; on flask it is 96 against 12. A tool that does not put
  documentation in the graph cannot draw a single one of them.
- **The bar at the bottom** — resolved member calls against call sites that had
  no receiver evidence and therefore produced no edge at all, broken down by
  syntactic shape. The blind spot is drawn to scale, because an absent line is
  not evidence of an absent call.

That last panel is the point. Most graph tools render what they found; the
interesting claim here is that the graph also knows the size and shape of what
it missed, and says so in the same frame.
