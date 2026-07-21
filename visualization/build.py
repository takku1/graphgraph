"""Render a GraphGraph graph as a single 3D-projected SVG image.

Usage:
    python visualization/build.py                        # this repo's graph
    python visualization/build.py --graph path/to.gg --output out.svg
    python visualization/build.py --rotate 35            # spin the camera

Symbols are aggregated to their module: 7,000 nodes drawn one-per-sphere is
a hairball that answers nothing, while ~20 modules shows the actual shape of
a codebase. Positions come from a force-directed layout in three dimensions,
projected with perspective -- depth is carried by size, brightness, and draw
order, which is what makes a static image read as 3D.

Pure SVG with no scripts or external requests, so it opens anywhere and can
be dropped straight into a README.
"""

from __future__ import annotations

import argparse
import html
import math
import random
from collections import Counter, defaultdict
from pathlib import Path

from graphgraph.io import find_graph_path, load_any

# Relations meaning "this code depends on that code". Doc/concept relations
# are real but would swamp a dependency picture.
STRUCTURAL_RELATIONS = ("calls", "imports", "imports_from", "implements", "returns", "references")

# Prose-to-code relations. Most code graphs do not have these at all -- the
# documentation is simply not in the graph -- so they are the clearest visual
# difference between this system and a dependency grapher.
NARRATIVE_RELATIONS = ("explains", "discusses", "mentions", "formalizes", "section_of")

WIDTH, HEIGHT = 1200, 820
FOCAL = 1500.0
CAMERA_DISTANCE = 1500.0


def module_of(path: str, depth: int = 3) -> str:
    """Collapse a file path to the module that owns it."""
    if not path:
        return ""
    parts = path.replace("\\", "/").split("/")
    if len(parts) > 1 and "." in parts[-1]:
        parts = parts[:-1]
    return "/".join(parts[:depth]) or parts[0]


def build_layer_graph(graph, relations, depth: int = 3):
    """Module-to-module traffic restricted to one family of relations."""
    owner = {
        nid: module_of(n.path, depth)
        for nid, n in graph.nodes.items()
        if n.active and n.path and module_of(n.path, depth)
    }
    weights: Counter = Counter()
    for edge in graph.edges:
        if not edge.active or edge.type not in relations:
            continue
        a, b = owner.get(edge.source), owner.get(edge.target)
        if a and b and a != b:
            weights[(a, b)] += 1
    return dict(weights)


def build_module_graph(graph, depth: int = 3):
    """Aggregate symbols into modules and count structural traffic between them."""
    owner: dict[str, str] = {}
    modules: dict[str, dict] = defaultdict(lambda: {"symbols": 0, "kinds": Counter()})
    for node_id, node in graph.nodes.items():
        if not node.active or not node.path:
            continue
        module = module_of(node.path, depth)
        if not module:
            continue
        owner[node_id] = module
        modules[module]["symbols"] += 1
        modules[module]["kinds"][node.kind] += 1

    weights: Counter = Counter()
    for edge in graph.edges:
        if not edge.active or edge.type not in STRUCTURAL_RELATIONS:
            continue
        a, b = owner.get(edge.source), owner.get(edge.target)
        if a and b and a != b:
            weights[(a, b)] += 1
    return dict(modules), dict(weights)


def layout_3d(names, weights, seed: int = 11, iterations: int = 400):
    """Force-directed placement in 3D (Fruchterman-Reingold), deterministic.

    O(n^2) repulsion is fine here: this runs over modules, not symbols, so n
    is a few dozen and a spatial index would be pure complexity.
    """
    rng = random.Random(seed)
    count = max(1, len(names))
    span = 460.0
    k = span / (count ** (1 / 3))
    pos = {
        n: [rng.uniform(-span, span), rng.uniform(-span, span), rng.uniform(-span, span)]
        for n in names
    }
    peak = max(weights.values(), default=1)
    springs = {pair: 0.3 + 0.7 * (w / peak) for pair, w in weights.items()}

    temperature = span / 4.0
    for _ in range(iterations):
        shift = {n: [0.0, 0.0, 0.0] for n in names}
        for i, a in enumerate(names):
            for b in names[i + 1:]:
                d = [pos[a][axis] - pos[b][axis] for axis in range(3)]
                dist = math.sqrt(sum(v * v for v in d)) or 0.01
                force = (k * k) / dist
                for axis in range(3):
                    unit = d[axis] / dist
                    shift[a][axis] += unit * force
                    shift[b][axis] -= unit * force
        for (a, b), strength in springs.items():
            if a not in pos or b not in pos:
                continue
            d = [pos[a][axis] - pos[b][axis] for axis in range(3)]
            dist = math.sqrt(sum(v * v for v in d)) or 0.01
            force = (dist * dist) / k * strength
            for axis in range(3):
                unit = d[axis] / dist
                shift[a][axis] -= unit * force
                shift[b][axis] += unit * force
        for n in names:
            dist = math.sqrt(sum(v * v for v in shift[n])) or 0.01
            step = min(dist, temperature)
            for axis in range(3):
                pos[n][axis] += shift[n][axis] / dist * step
                pos[n][axis] = max(-span, min(span, pos[n][axis]))
        temperature *= 0.97

    # Flatten the vertical axis. A free 3D layout spreads roughly spherically,
    # which wastes a landscape frame -- the fit pass then scales to whichever
    # axis binds and leaves wide empty margins. Compressing y trades a little
    # separation for a scene shaped like the canvas it is drawn on.
    for n in names:
        pos[n][1] *= 0.55
    return pos


def project(point, rotation_deg: float, tilt_deg: float = 24.0):
    """Rotate about Y, tilt about X, then apply perspective divide."""
    x, y, z = point
    ry = math.radians(rotation_deg)
    x, z = x * math.cos(ry) - z * math.sin(ry), x * math.sin(ry) + z * math.cos(ry)
    rx = math.radians(tilt_deg)
    y, z = y * math.cos(rx) - z * math.sin(rx), y * math.sin(rx) + z * math.cos(rx)
    scale = FOCAL / (CAMERA_DISTANCE - z)
    return WIDTH / 2 + x * scale, HEIGHT / 2 + y * scale, z, scale


# Hue-rotated family so adjacent modules stay distinguishable without
# depending on a colour library.
HUES = [212, 172, 28, 268, 328, 96, 192, 4, 248, 148, 56, 300]


def module_colour(index: int, depth_ratio: float) -> str:
    """Colour by module identity, lightened with distance for depth."""
    hue = HUES[index % len(HUES)]
    lightness = 46 + 26 * depth_ratio
    saturation = 70 - 26 * depth_ratio
    return f"hsl({hue} {saturation:.0f}% {lightness:.0f}%)"


def render_svg(graph, graph_path: Path, rotation: float, depth: int) -> str:
    modules, weights = build_module_graph(graph, depth)
    names = sorted(modules, key=lambda m: -modules[m]["symbols"])[:22]
    keep = set(names)
    weights = {(a, b): w for (a, b), w in weights.items() if a in keep and b in keep}

    pos = layout_3d(names, weights)
    projected = {n: project(pos[n], rotation) for n in names}

    # Perspective projection has no idea about the viewport: a wide layout or
    # a near-camera sphere lands outside it and gets clipped. Fit the whole
    # projected scene, radii included, into the canvas before drawing.
    biggest_symbols = max((modules[n]["symbols"] for n in names), default=1)

    def base_radius(name: str, scale: float) -> float:
        return (11 + 30 * math.sqrt(modules[name]["symbols"] / biggest_symbols)) * scale

    xs_lo = min(projected[n][0] - base_radius(n, projected[n][3]) for n in names)
    xs_hi = max(projected[n][0] + base_radius(n, projected[n][3]) for n in names)
    # Labels sit below each sphere, so reserve room for them in the fit.
    ys_lo = min(projected[n][1] - base_radius(n, projected[n][3]) for n in names)
    ys_hi = max(projected[n][1] + base_radius(n, projected[n][3]) + 20 for n in names)
    pad = 70
    fit = min(
        (WIDTH - 2 * pad) / max(1e-6, xs_hi - xs_lo),
        (HEIGHT - 2 * pad - 60) / max(1e-6, ys_hi - ys_lo),
        1.0,
    )
    cx, cy = (xs_lo + xs_hi) / 2, (ys_lo + ys_hi) / 2
    projected = {
        n: (
            WIDTH / 2 + (x - cx) * fit,
            HEIGHT / 2 + 24 + (y - cy) * fit,
            z,
            scale * fit,
        )
        for n, (x, y, z, scale) in projected.items()
    }

    depths = [p[2] for p in projected.values()]
    near, far = max(depths, default=1.0), min(depths, default=0.0)
    spread = (near - far) or 1.0

    def depth_ratio(z: float) -> float:
        """1.0 = nearest to camera, 0.0 = furthest."""
        return (z - far) / spread

    biggest = max((modules[n]["symbols"] for n in names), default=1)
    heaviest = max(weights.values(), default=1)
    order = {n: i for i, n in enumerate(sorted(names))}

    # Painter's algorithm: far things first so near things occlude them.
    edge_svg = []
    for (a, b), weight in sorted(weights.items(), key=lambda kv: projected[kv[0][0]][2] + projected[kv[0][1]][2]):
        xa, ya, za, _ = projected[a]
        xb, yb, zb, _ = projected[b]
        ratio = depth_ratio((za + zb) / 2)
        width = (0.5 + 3.0 * (weight / heaviest)) * (0.55 + 0.45 * ratio)
        opacity = (0.14 + 0.42 * (weight / heaviest)) * (0.45 + 0.55 * ratio)
        edge_svg.append(
            f'<line x1="{xa:.1f}" y1="{ya:.1f}" x2="{xb:.1f}" y2="{yb:.1f}" '
            f'stroke="url(#wire)" stroke-width="{width:.2f}" opacity="{opacity:.2f}" '
            f'stroke-linecap="round"><title>{html.escape(a)} → {html.escape(b)}  '
            f'{weight} refs</title></line>'
        )

    sphere_svg = []
    for name in sorted(names, key=lambda n: projected[n][2]):
        x, y, z, scale = projected[name]
        ratio = depth_ratio(z)
        symbols = modules[name]["symbols"]
        radius = (11 + 30 * math.sqrt(symbols / biggest)) * scale
        colour = module_colour(order[name], ratio)
        label = name.split("/")[-1]
        detail = ", ".join(f"{k}={v}" for k, v in modules[name]["kinds"].most_common(3))
        # A radial highlight offset toward the light source is what sells a
        # flat circle as a sphere.
        sphere_svg.append(
            f'<g opacity="{0.62 + 0.38 * ratio:.2f}">'
            f'<ellipse cx="{x:.1f}" cy="{y + radius * 0.92:.1f}" rx="{radius * 0.75:.1f}" '
            f'ry="{radius * 0.2:.1f}" fill="#000" opacity="{0.10 + 0.10 * ratio:.2f}"/>'
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{radius:.1f}" fill="{colour}"/>'
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{radius:.1f}" fill="url(#shade)"/>'
            f'<title>{html.escape(name)}\n{symbols} symbols\n{html.escape(detail)}</title>'
            f'</g>'
            f'<text x="{x:.1f}" y="{y + radius + 15 * scale:.1f}" '
            f'font-size="{max(9.5, 12 * scale):.1f}" text-anchor="middle" '
            f'fill="var(--ink)" opacity="{0.5 + 0.5 * ratio:.2f}" '
            f'font-weight="600">{html.escape(label)}</text>'
        )

    node_total = sum(1 for n in graph.nodes.values() if n.active)
    edge_total = sum(1 for e in graph.edges if e.active)
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH} {HEIGHT}" width="{WIDTH}" height="{HEIGHT}" role="img" aria-label="3D module dependency graph">
  <style>
    :root {{ --ink:#1b1b22; --muted:#6d6d7d; --bg0:#f7f8fc; --bg1:#e9ecf6; }}
    @media (prefers-color-scheme: dark) {{
      :root {{ --ink:#ececf4; --muted:#9c9cae; --bg0:#0d0e13; --bg1:#171926; }}
    }}
    text {{ font-family: ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif; }}
  </style>
  <defs>
    <radialGradient id="bg" cx="50%" cy="38%" r="78%">
      <stop offset="0%" stop-color="var(--bg1)"/>
      <stop offset="100%" stop-color="var(--bg0)"/>
    </radialGradient>
    <radialGradient id="shade" cx="34%" cy="30%" r="72%">
      <stop offset="0%" stop-color="#fff" stop-opacity="0.42"/>
      <stop offset="45%" stop-color="#fff" stop-opacity="0.05"/>
      <stop offset="100%" stop-color="#000" stop-opacity="0.30"/>
    </radialGradient>
    <linearGradient id="wire" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#6f8cff"/>
      <stop offset="100%" stop-color="#43b6a8"/>
    </linearGradient>
  </defs>

  <rect width="{WIDTH}" height="{HEIGHT}" fill="url(#bg)"/>
  <g>{"".join(edge_svg)}</g>
  <g>{"".join(sphere_svg)}</g>

  <text x="34" y="46" font-size="19" font-weight="700" fill="var(--ink)">{html.escape(graph_path.parent.parent.name or str(graph_path))}</text>
  <text x="34" y="68" font-size="12.5" fill="var(--muted)">{node_total:,} nodes &#183; {edge_total:,} edges &#183; {len(modules)} modules &#183; spheres sized by symbol count</text>
  <text x="34" y="{HEIGHT - 26}" font-size="11.5" fill="var(--muted)">Edges are structural references ({", ".join(STRUCTURAL_RELATIONS[:4])}&#8230;). Depth shown by size, brightness and occlusion.</text>
</svg>
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Render a GraphGraph graph as a 3D SVG image.")
    parser.add_argument("--graph", help="Graph path. Auto-detected from .graphgraph if omitted.")
    parser.add_argument("--output", default="visualization/graph.svg", help="Output SVG path.")
    parser.add_argument("--rotate", type=float, default=28.0, help="Camera rotation in degrees.")
    parser.add_argument("--depth", type=int, default=3, help="Path segments defining a module.")
    parser.add_argument(
        "--mode",
        choices=["structure", "contrast"],
        default="structure",
        help="structure: module topology. contrast: what a dependency grapher would miss.",
    )
    args = parser.parse_args()

    graph_path = Path(args.graph) if args.graph else find_graph_path()
    graph = load_any(graph_path)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    if args.mode == "contrast":
        from contrast import render as render_contrast

        svg = render_contrast(graph, graph_path, args.rotate, args.depth)
    else:
        svg = render_svg(graph, graph_path, args.rotate, args.depth)
    out.write_text(svg, encoding="utf-8")
    print(f"wrote {out}  ({out.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
