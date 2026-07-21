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
