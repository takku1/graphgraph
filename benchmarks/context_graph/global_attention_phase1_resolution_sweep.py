from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

try:
    from .global_attention_phase1 import GRAPH_NAMES, REAL_GRAPH_DIR, evaluate_graph_path
    from .global_attention_phase1_formula_sweep import render_markdown, summarize
except ImportError:
    from global_attention_phase1 import (  # type: ignore[no-redef]
        GRAPH_NAMES,
        REAL_GRAPH_DIR,
        evaluate_graph_path,
    )
    from global_attention_phase1_formula_sweep import (  # type: ignore[no-redef]
        render_markdown,
        summarize,
    )

OUT = ROOT / "benchmarks" / "context_graph" / "out" / "global_attention"
REPORT_JSON = OUT / "phase1_resolution_sweep.json"
REPORT_MD = OUT / "phase1_resolution_sweep.md"
WEIGHTS = (0.001, 0.01, 0.1, 1.0)
BUDGETS = (32, 64)


def main() -> None:
    graph_paths = [REAL_GRAPH_DIR / f"{name}.json" for name in GRAPH_NAMES]
    missing = [path.name for path in graph_paths if not path.exists()]
    if missing:
        print(f"SKIP: missing resolution-sweep graphs: {', '.join(missing)}")
        return

    rows: list[dict[str, object]] = []
    for weight in WEIGHTS:
        for graph_path in graph_paths:
            for row in evaluate_graph_path(
                graph_path,
                budgets=BUDGETS,
                exactness_weight=0.0,
                resolution_weight=weight,
            ):
                rows.append({**row, "resolution_weight": weight})

    report = summarize(
        rows,
        weights=WEIGHTS,
        budgets=BUDGETS,
        weight_key="resolution_weight",
    )
    report["formula_family"] = "L2 plus weight times mass times normalized log cell size"
    OUT.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(json.dumps(report, indent=2), encoding="utf-8")
    markdown = render_markdown(report).replace(
        "Phase 1 Formula Sweep",
        "Phase 1 Log-Resolution Formula Sweep",
    )
    REPORT_MD.write_text(markdown, encoding="utf-8")
    print(markdown)


if __name__ == "__main__":
    main()
