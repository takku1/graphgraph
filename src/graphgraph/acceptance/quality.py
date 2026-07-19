"""Token-vs-quality evaluation loop.

The acceptance board proves correctness; this proves the value proposition the
project rests on: fewer tokens without losing the facts that answer the query.
For a fixed set of queries it measures, per packet:

- ``tokens`` — controlling packet token count (worse of cl100k/o200k, or proxy);
- ``recall`` — fraction of required facts present as structural nodes;
- ``precision`` — fraction of packet nodes that are relevant (not sibling noise);
- ``density`` — required facts recalled per 100 packet tokens.

A committed baseline locks the current numbers. Baseline token comparison uses
GraphGraph's deterministic proxy so installing an optional tokenizer cannot
change the unit. Real encoder counts remain telemetry. Recall may never fall;
tokens may rise beyond tolerance only when recall or precision improves.
"""

from __future__ import annotations

import json
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Optional

from graphgraph.packets import estimate_tokens

from .model import GroundTruth, Task
from .runner import run_probe

BASELINE_PATH = Path(__file__).with_name("quality_baseline.json")
TOKEN_TOLERANCE = 0.05  # allow <=5% token drift before flagging a rise


@dataclass(frozen=True)
class QualityQuery:
    id: str
    query: str
    query_class: str
    build: Callable[[Path], None]
    required_facts: tuple[str, ...]
    relevant_labels: tuple[str, ...] = ()
    max_nodes: int = 20
    fact_mode: str = "symbol"  # "symbol" (node label) or "text" (packet substring)


@dataclass(frozen=True)
class QualityMetrics:
    query: str
    tokens: int
    precise_tokens: Optional[int]
    nodes: int
    precision: Optional[float]
    required: int
    present: int
    recall: float
    density: float


# --- Hermetic fixtures -------------------------------------------------------

def _calls_repo(root: Path) -> None:
    (root / "app.py").write_text(
        "def normalize_value(x):\n    return x + 1\n\n"
        "def public_entry():\n    return normalize_value(1)\n\n"
        "def other_entry():\n    return normalize_value(2)\n",
        encoding="utf-8",
    )


def _doc_repo(root: Path) -> None:
    docs = root / "docs"
    docs.mkdir()
    stages = "\n\n".join(
        f"## Stage {n}: phase_{n}\n\nStage {n} performs the phase_{n} step." for n in range(1, 9)
    )
    (docs / "pipeline.md").write_text(
        f"# Backbone pipeline\n\nThe pipeline forms 8 stages.\n\n{stages}\n", encoding="utf-8"
    )


def _flow_repo(root: Path) -> None:
    (root / "engine").mkdir()
    (root / "engine" / "__init__.py").write_text("", encoding="utf-8")
    (root / "engine" / "expr.py").write_text(
        "class Expr:\n    def __init__(self, value):\n        self.value = value\n\n"
        "def lift(expr):\n    return expr.value\n",
        encoding="utf-8",
    )
    (root / "frontends").mkdir()
    (root / "frontends" / "__init__.py").write_text("", encoding="utf-8")
    (root / "frontends" / "parse.py").write_text(
        "from engine.expr import Expr, lift\n\n"
        "def parse_expr(source):\n    return lift(Expr(source))\n",
        encoding="utf-8",
    )


QUALITY_QUERIES: tuple[QualityQuery, ...] = (
    QualityQuery(
        id="reverse_callers",
        query="What directly calls normalize_value?",
        query_class="reverse_lookup",
        build=_calls_repo,
        required_facts=("public_entry", "other_entry"),
        relevant_labels=("normalize_value", "public_entry", "other_entry"),
    ),
    QualityQuery(
        id="direct_callee",
        query="What does public_entry call?",
        query_class="direct_lookup",
        build=_calls_repo,
        required_facts=("normalize_value",),
        relevant_labels=("public_entry", "normalize_value"),
    ),
    QualityQuery(
        id="doc_stages",
        query="According to docs/pipeline.md, what stages form the pipeline?",
        query_class="doc_summary",
        build=_doc_repo,
        required_facts=tuple(f"phase_{n}" for n in range(1, 9)),
        max_nodes=30,
        fact_mode="text",
    ),
    QualityQuery(
        id="flow_scope",
        query="How does expression parsing flow from frontends into the engine expression representation?",
        query_class="subsystem_summary",
        build=_flow_repo,
        required_facts=("parse_expr", "lift", "Expr"),
        relevant_labels=("parse_expr", "lift", "Expr"),
        max_nodes=40,
    ),
)


def measure(query: QualityQuery) -> QualityMetrics:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        query.build(root)
        task = Task(
            id=query.id,
            title=query.id,
            dimension="quality",
            severity="P2",
            query=query.query,
            query_class=query.query_class,
            max_nodes=query.max_nodes,
            ground_truth=GroundTruth(relevant_labels=query.relevant_labels),
        )
        probe = run_probe(task, root, root / ".graphgraph" / "graph.gg")

    if query.fact_mode == "text":
        present = sum(1 for fact in query.required_facts if fact in probe.packet)
    else:
        present = sum(1 for fact in query.required_facts if probe.has_symbol(fact))
    required = len(query.required_facts)
    recall = round(present / required, 4) if required else 1.0

    precision: Optional[float] = None
    if query.relevant_labels:
        ratio, _ = probe.irrelevant_ratio(set(query.relevant_labels))
        precision = round(1.0 - ratio, 4)

    tokens = estimate_tokens(probe.packet)
    precise_tokens = probe.tokens.controlling if probe.tokens.precise else None
    density = round(present / (tokens / 100), 4) if tokens else 0.0
    return QualityMetrics(
        query=query.id,
        tokens=tokens,
        precise_tokens=precise_tokens,
        nodes=len(probe.packet_nodes),
        precision=precision,
        required=required,
        present=present,
        recall=recall,
        density=density,
    )


def run_quality() -> dict[str, QualityMetrics]:
    return {query.id: measure(query) for query in QUALITY_QUERIES}


@dataclass(frozen=True)
class Regression:
    query: str
    reason: str
    baseline: float
    current: float


def compare(current: dict[str, QualityMetrics], baseline: dict[str, dict]) -> list[Regression]:
    """Reject recall loss and token growth without a measured quality gain."""
    regressions: list[Regression] = []
    for qid, metrics in current.items():
        base = baseline.get(qid)
        if base is None:
            continue
        base_tokens = float(base["tokens"])
        base_recall = float(base["recall"])
        base_precision = base.get("precision")
        precision_improved = (
            metrics.precision is not None
            and base_precision is not None
            and metrics.precision > float(base_precision) + 1e-9
        )
        quality_improved = metrics.recall > base_recall + 1e-9 or precision_improved
        if (
            metrics.tokens > base_tokens * (1 + TOKEN_TOLERANCE)
            and not quality_improved
        ):
            regressions.append(Regression(qid, "tokens rose", base_tokens, float(metrics.tokens)))
        if metrics.recall < base_recall - 1e-9:
            regressions.append(Regression(qid, "recall fell", base_recall, metrics.recall))
    return regressions


def to_json(report: dict[str, QualityMetrics]) -> dict[str, dict]:
    return {qid: asdict(metrics) for qid, metrics in report.items()}


def save_baseline(report: dict[str, QualityMetrics], path: Path = BASELINE_PATH) -> None:
    path.write_text(json.dumps(to_json(report), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_baseline(path: Path = BASELINE_PATH) -> dict[str, dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def format_report(report: dict[str, QualityMetrics]) -> str:
    lines = ["query            tokens  nodes  precision  recall  density"]
    for m in report.values():
        prec = "  n/a  " if m.precision is None else f"{m.precision:>7.2f}"
        lines.append(f"{m.query:<16} {m.tokens:>6}  {m.nodes:>5}  {prec}  {m.recall:>5.2f}  {m.density:>6.2f}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    import sys

    args = argv if argv is not None else sys.argv[1:]
    command = args[0] if args else "run"
    report = run_quality()
    print(format_report(report))
    if command == "baseline":
        save_baseline(report)
        print(f"\nbaseline written: {BASELINE_PATH}")
        return 0
    if command == "check":
        if not BASELINE_PATH.exists():
            print("\nno baseline; run: python -m graphgraph.acceptance.quality baseline", file=sys.stderr)
            return 2
        regressions = compare(report, load_baseline())
        if regressions:
            print("\nREGRESSIONS:")
            for r in regressions:
                print(f"  {r.query}: {r.reason} {r.baseline} -> {r.current}")
            return 1
        print("\nno regression: tokens not up, recall not down")
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
