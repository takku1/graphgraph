"""Draw what a dependency grapher would show, and what it would miss.

The module-topology view in `build.py` is the picture every code-graph tool
produces. This one exists to show the three things that are actually
different about a GraphGraph graph, by rendering them rather than asserting
them:

  * **Prose is in the graph.** `explains`/`discusses`/`mentions` edges link
    documentation to the code it describes, so module pairs related only
    through prose are visible here and nowhere else. On this repository
    those outnumber the code-linked pairs.
  * **Relations are typed and weighted.** Evidence strength is a property of
    the edge, not of the reader's eye, so line weight means something.
  * **The blind spot is measured.** Member calls only become edges when the
    receiver can be typed; the unresolved remainder is counted and drawn to
    scale, so a missing line is never mistaken for a missing call.
"""

from __future__ import annotations

import html
import math
from pathlib import Path

from build import (
    HEIGHT,
    NARRATIVE_RELATIONS,
    STRUCTURAL_RELATIONS,
    WIDTH,
    build_layer_graph,
    build_module_graph,
    layout_3d,
    project,
)

BAND = 138  # reserved height for the blind-spot readout
CODE_COLOUR = "#4d78e8"
PROSE_COLOUR = "#d98a3a"


def resolution_receipt(graph) -> dict:
    """Resolved vs unresolved member calls, with the shape breakdown."""
    metadata = graph.metadata or {}

    def count(name: str) -> int:
        for key in (f"member_calls_{name}", f"member_calls_global_{name}"):
            raw = metadata.get(key)
            if raw:
                try:
                    return int(raw)
                except ValueError:
                    continue
        return 0

    resolved, unknown, ambiguous = count("resolved"), count("unknown_receiver"), count("ambiguous")
    shapes: dict[str, int] = {}
    raw = metadata.get("member_calls_global_unknown_receiver_classes") or metadata.get(
        "member_calls_unknown_receiver_classes", ""
    )
    for item in raw.split(","):
        name, _, value = item.partition(":")
        if name and value.isdigit():
            shapes[name] = int(value)
    return {
        "resolved": resolved,
        "unknown": unknown,
        "eligible": resolved + unknown + ambiguous,
        "shapes": dict(sorted(shapes.items(), key=lambda kv: -kv[1])),
    }


def render(graph, graph_path: Path, rotation: float, depth: int) -> str:
    modules, _ = build_module_graph(graph, depth)
    code = build_layer_graph(graph, STRUCTURAL_RELATIONS, depth)
    prose = build_layer_graph(graph, NARRATIVE_RELATIONS, depth)

    names = sorted(modules, key=lambda m: -modules[m]["symbols"])[:20]
    keep = set(names)
    code = {k: v for k, v in code.items() if k[0] in keep and k[1] in keep}
    prose = {k: v for k, v in prose.items() if k[0] in keep and k[1] in keep}
    # The claim is about pairs a dependency grapher cannot reach at all, so
    # prose links that merely echo an existing code edge are not counted.
    prose_only = {k: v for k, v in prose.items() if k not in code and (k[1], k[0]) not in code}

    # Prose pulls weakly: it should influence grouping without overwhelming
    # the dependency structure that gives the picture its shape.
    pull = dict(code)
    for pair, weight in prose_only.items():
        pull[pair] = pull.get(pair, 0) + max(1, weight // 4)

    positions = layout_3d(names, pull)
    projected = {n: project(positions[n], rotation) for n in names}

    biggest = max((modules[n]["symbols"] for n in names), default=1)

    def radius_at(name: str, scale: float) -> float:
        return (10 + 26 * math.sqrt(modules[name]["symbols"] / biggest)) * scale

    lo_x = min(projected[n][0] - radius_at(n, projected[n][3]) for n in names)
    hi_x = max(projected[n][0] + radius_at(n, projected[n][3]) for n in names)
    lo_y = min(projected[n][1] - radius_at(n, projected[n][3]) for n in names)
    hi_y = max(projected[n][1] + radius_at(n, projected[n][3]) + 18 for n in names)
    # Scale up as well as down. Capping at 1.0 left a compact layout marooned
    # in the middle of the frame; the cap that matters is the viewport, not
    # the projection's natural size.
    fit = min(
        (WIDTH - 170) / max(1e-6, hi_x - lo_x),
        (HEIGHT - BAND - 170) / max(1e-6, hi_y - lo_y),
    )
    cx, cy = (lo_x + hi_x) / 2, (lo_y + hi_y) / 2
    projected = {
        n: (WIDTH / 2 + (x - cx) * fit, (HEIGHT - BAND) / 2 + 30 + (y - cy) * fit, z, sc * fit)
        for n, (x, y, z, sc) in projected.items()
    }

    depths = [p[2] for p in projected.values()]
    near, far = max(depths, default=1.0), min(depths, default=0.0)
    spread = (near - far) or 1.0

    def nearness(z: float) -> float:
        return (z - far) / spread

    def lines(pairs: dict, colour: str, peak: int, dashed: bool, note: str) -> list[str]:
        out = []
        ordered = sorted(pairs.items(), key=lambda kv: projected[kv[0][0]][2] + projected[kv[0][1]][2])
        for (a, b), weight in ordered:
            xa, ya, za, _ = projected[a]
            xb, yb, zb, _ = projected[b]
            near_ratio = nearness((za + zb) / 2)
            width = (0.6 + (3.0 if not dashed else 1.7) * (weight / peak)) * (0.55 + 0.45 * near_ratio)
            opacity = (0.20 + 0.48 * (weight / peak)) * (0.5 + 0.5 * near_ratio)
            dash = ' stroke-dasharray="5 5"' if dashed else ""
            out.append(
                f'<line x1="{xa:.1f}" y1="{ya:.1f}" x2="{xb:.1f}" y2="{yb:.1f}" stroke="{colour}" '
                f'stroke-width="{width:.2f}" opacity="{opacity:.2f}" stroke-linecap="round"{dash}>'
                f'<title>{html.escape(a)} &#8212; {html.escape(b)}: {weight} {note}</title></line>'
            )
        return out

    prose_svg = lines(prose_only, PROSE_COLOUR, max(prose_only.values(), default=1), True,
                      "prose references, no code dependency")
    code_svg = lines(code, CODE_COLOUR, max(code.values(), default=1), False, "code references")

    spheres = []
    for name in sorted(names, key=lambda n: projected[n][2]):
        x, y, z, scale = projected[name]
        ratio = nearness(z)
        rad = radius_at(name, scale)
        spheres.append(
            f'<g opacity="{0.68 + 0.32 * ratio:.2f}">'
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{rad:.1f}" fill="hsl(222 14% {56 + 24 * ratio:.0f}%)"/>'
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{rad:.1f}" fill="url(#shade)"/>'
            f'<title>{html.escape(name)}: {modules[name]["symbols"]} symbols</title></g>'
            f'<text x="{x:.1f}" y="{y + rad + 14 * scale:.1f}" font-size="{max(9.0, 11.5 * scale):.1f}" '
            f'text-anchor="middle" fill="var(--ink)" opacity="{0.45 + 0.55 * ratio:.2f}" '
            f'font-weight="600">{html.escape(name.split("/")[-1])}</text>'
        )

    receipt = resolution_receipt(graph)
    top = HEIGHT - BAND
    if receipt["eligible"]:
        bar_x, bar_w = 150, WIDTH - 300
        known_w = bar_w * (receipt["resolved"] / receipt["eligible"])
        shape_text = "   ".join(f"{k} {v:,}" for k, v in list(receipt["shapes"].items())[:4])
        blind = (
            f'<text x="{bar_x}" y="{top + 32}" font-size="12.5" font-weight="700" fill="var(--ink)">'
            f'What this graph cannot see</text>'
            f'<rect x="{bar_x}" y="{top + 44}" width="{bar_w:.0f}" height="15" rx="7.5" '
            f'fill="{PROSE_COLOUR}" opacity="0.28"/>'
            f'<rect x="{bar_x}" y="{top + 44}" width="{known_w:.0f}" height="15" rx="7.5" fill="{CODE_COLOUR}"/>'
            f'<text x="{bar_x}" y="{top + 78}" font-size="11.5" fill="var(--muted)">'
            f'{receipt["resolved"]:,} member calls resolved to an edge &#183; '
            f'{receipt["unknown"]:,} call sites had no receiver evidence and produce no edge at all, '
            f'so a missing line is not proof of a missing call</text>'
            f'<text x="{bar_x}" y="{top + 96}" font-size="10.5" fill="var(--muted)">'
            f'unresolved by shape: {html.escape(shape_text)}</text>'
        )
    else:
        blind = (f'<text x="150" y="{top + 32}" font-size="12" fill="var(--muted)">'
                 f'No member-call telemetry on this graph.</text>')

    repo = graph_path.parent.parent.name or str(graph_path)
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH} {HEIGHT}" width="{WIDTH}" height="{HEIGHT}" role="img" aria-label="Code dependencies versus prose relations, with the measured blind spot">
  <style>
    :root {{ --ink:#1b1b22; --muted:#6d6d7d; --bg0:#f7f8fc; --bg1:#eaedf7; --rule:#d8dae6; }}
    @media (prefers-color-scheme: dark) {{
      :root {{ --ink:#ececf4; --muted:#9c9cae; --bg0:#0c0d12; --bg1:#161825; --rule:#282a38; }}
    }}
    text {{ font-family: ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif; }}
  </style>
  <defs>
    <radialGradient id="bg" cx="50%" cy="36%" r="80%">
      <stop offset="0%" stop-color="var(--bg1)"/><stop offset="100%" stop-color="var(--bg0)"/>
    </radialGradient>
    <radialGradient id="shade" cx="34%" cy="30%" r="72%">
      <stop offset="0%" stop-color="#fff" stop-opacity="0.40"/>
      <stop offset="45%" stop-color="#fff" stop-opacity="0.04"/>
      <stop offset="100%" stop-color="#000" stop-opacity="0.32"/>
    </radialGradient>
  </defs>
  <rect width="{WIDTH}" height="{HEIGHT}" fill="url(#bg)"/>

  <text x="34" y="44" font-size="19" font-weight="700" fill="var(--ink)">One graph, two kinds of knowledge</text>
  <text x="34" y="67" font-size="12.5" fill="var(--muted)">{html.escape(repo)} &#183; {len(code)} module pairs linked by code &#183; <tspan fill="{PROSE_COLOUR}" font-weight="700">{len(prose_only)} linked only by prose</tspan> &#8212; a dependency grapher draws the solid lines and stops there</text>

  <g>{"".join(prose_svg)}</g>
  <g>{"".join(code_svg)}</g>
  <g>{"".join(spheres)}</g>

  <line x1="34" y1="{top}" x2="{WIDTH - 34}" y2="{top}" stroke="var(--rule)"/>
  <line x1="34" y1="{top + 27}" x2="74" y2="{top + 27}" stroke="{CODE_COLOUR}" stroke-width="3" stroke-linecap="round"/>
  <text x="34" y="{top + 46}" font-size="10.5" fill="var(--muted)">code</text>
  <line x1="34" y1="{top + 66}" x2="74" y2="{top + 66}" stroke="{PROSE_COLOUR}" stroke-width="3" stroke-dasharray="5 5" stroke-linecap="round"/>
  <text x="34" y="{top + 85}" font-size="10.5" fill="var(--muted)">prose</text>
  {blind}
</svg>
"""
