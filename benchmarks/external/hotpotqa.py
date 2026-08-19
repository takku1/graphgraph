#!/usr/bin/env python
"""Score GraphGraph on HotpotQA supporting-paragraph retrieval.

Each HotpotQA question ships its own 10-paragraph corpus: exactly 2 are the
gold supporting documents, 8 are distractors chosen to look relevant. So every
question is scored as an independent retrieval task over a fresh graph -- there
is no shared index to leak across questions, and no way to tune against a
corpus that is rebuilt per question.

What this scores is *retrieval*, deliberately. Answer generation would measure
whichever LLM was attached; supporting-fact retrieval measures this tool, and
it is the axis a context graph actually claims to win on.

The comparison arm is a BM25-style lexical ranker over the same 10 paragraphs.
That is the honest baseline: if a graph cannot beat term-frequency scoring on
multi-hop questions, its extra machinery is not buying retrieval quality.

Usage:
    python benchmarks/external/hotpotqa.py --limit 100
    python benchmarks/external/hotpotqa.py --limit 500 --json out.json
"""

from __future__ import annotations

import argparse
import json
import math
import random
import re
import sys
import tempfile
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

DEFAULT_DATA = REPO_ROOT / ".scratch" / "benchmarks" / "data" / "hotpot_distractor_validation.parquet"
_WORD = re.compile(r"[A-Za-z0-9]+")


@dataclass
class TaskResult:
    qid: str
    question: str
    level: str
    qtype: str
    gold: list[str]
    graph_titles: list[str] = field(default_factory=list)
    lexical_titles: list[str] = field(default_factory=list)
    graph_ms: float = 0.0
    error: str = ""


def _tokens(text: str) -> list[str]:
    return [w.lower() for w in _WORD.findall(text)]


def _bm25_rank(question: str, paragraphs: list[tuple[str, str]], k: int) -> list[str]:
    """Okapi BM25 over the question's own 10 paragraphs.

    The standard strong lexical baseline (k1=1.5, b=0.75). Scoped to this
    question's corpus so both arms see exactly the same candidate set.
    """
    k1, b = 1.5, 0.75
    docs = [_tokens(body) for _title, body in paragraphs]
    n = len(docs)
    avgdl = sum(len(d) for d in docs) / max(1, n)
    df: Counter[str] = Counter()
    for doc in docs:
        df.update(set(doc))
    scores: list[tuple[float, str]] = []
    query = _tokens(question)
    for (title, _body), doc in zip(paragraphs, docs):
        tf = Counter(doc)
        length = len(doc)
        score = 0.0
        for term in query:
            if term not in tf:
                continue
            idf = math.log(1 + (n - df[term] + 0.5) / (df[term] + 0.5))
            score += idf * (tf[term] * (k1 + 1)) / (tf[term] + k1 * (1 - b + b * length / max(1, avgdl)))
        scores.append((score, title))
    scores.sort(key=lambda item: (-item[0], item[1]))
    return [title for _score, title in scores[:k]]


def _write_corpus(root: Path, paragraphs: list[tuple[str, str]]) -> dict[str, str]:
    """Write each paragraph as its own markdown document.

    One file per paragraph, because the unit HotpotQA scores is the paragraph.
    The filename is a slug, and the title is the H1, so a retrieved node maps
    back to a gold title through either its path or its section heading.
    """
    mapping: dict[str, str] = {}
    for index, (title, body) in enumerate(paragraphs):
        slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-") or f"doc-{index}"
        slug = f"{index:02d}-{slug[:60]}"
        (root / f"{slug}.md").write_text(f"# {title}\n\n{body}\n", encoding="utf-8")
        mapping[slug] = title
    return mapping


def _titles_from_nodes(node_paths: list[str], mapping: dict[str, str], k: int) -> list[str]:
    """Map retrieved nodes back to gold titles, keeping retrieval order."""
    ordered: list[str] = []
    for path in node_paths:
        stem = Path(str(path)).stem
        title = mapping.get(stem)
        if title and title not in ordered:
            ordered.append(title)
        if len(ordered) >= k:
            break
    return ordered


def _score(retrieved: list[str], gold: list[str]) -> tuple[float, float]:
    """HotpotQA supporting-fact convention: exact match and F1 over titles."""
    gold_set, got = set(gold), set(retrieved)
    exact = 1.0 if gold_set <= got else 0.0
    if not got or not gold_set:
        return exact, 0.0
    hit = len(gold_set & got)
    precision = hit / len(got)
    recall = hit / len(gold_set)
    f1 = 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)
    return exact, f1


def run(rows: list[dict], k: int, source_mode: str) -> list[TaskResult]:
    from graphgraph.io import save_graph
    from graphgraph.platform.compiler import CompileRequest, ContextCompiler
    from graphgraph.scanner import scan_directory

    results: list[TaskResult] = []
    for row in rows:
        context = row["context"]
        paragraphs = [
            (title, " ".join(sentences))
            for title, sentences in zip(context["title"], context["sentences"])
        ]
        gold = sorted(set(row["supporting_facts"]["title"]))
        task = TaskResult(
            qid=row["id"],
            question=row["question"],
            level=str(row.get("level", "")),
            qtype=str(row.get("type", "")),
            gold=gold,
        )
        task.lexical_titles = _bm25_rank(row["question"], paragraphs, k)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            corpus = root / "corpus"
            corpus.mkdir()
            mapping = _write_corpus(corpus, paragraphs)
            try:
                graph = scan_directory(corpus, depth="symbols", frontend="tree_sitter", docs=True)
                graph_path = root / "graph.json"
                save_graph(graph, graph_path)
                compiler = ContextCompiler.open(
                    graph_path,
                    graph=graph,
                    enable_evidence=False,
                    source_mode=source_mode,
                    memory_scopes=(),
                )
                started = time.perf_counter()
                outcome = compiler.compile(CompileRequest(query=row["question"]))
                task.graph_ms = (time.perf_counter() - started) * 1000
                # `starts` is the ranked anchor sequence; `nodes` is the packet's
                # node set, ordered for packing rather than relevance. Scoring
                # `nodes` measures the packer and reported 0.0 while the correct
                # title was sitting at anchor rank 1 -- so rank on `starts` and
                # fall back to `nodes` only if a run produced no anchors at all.
                ranked = list(outcome.retrieval.starts) or list(
                    getattr(outcome.retrieval, "nodes", None) or []
                )
                paths = [getattr(graph.nodes.get(n, None), "path", "") for n in ranked]
                task.graph_titles = _titles_from_nodes([p for p in paths if p], mapping, k)
            except Exception as exc:  # noqa: BLE001 - one bad task must not end the run
                task.error = f"{type(exc).__name__}: {exc}"
        results.append(task)
    return results


def summarize(results: list[TaskResult]) -> dict:
    scored = [r for r in results if not r.error]
    out: dict = {
        "tasks": len(results),
        "errors": sum(1 for r in results if r.error),
        "arms": {},
    }
    for arm, attr in (("graphgraph", "graph_titles"), ("bm25", "lexical_titles")):
        em = [_score(getattr(r, attr), r.gold)[0] for r in scored]
        f1 = [_score(getattr(r, attr), r.gold)[1] for r in scored]
        out["arms"][arm] = {
            "supporting_em": round(sum(em) / max(1, len(em)), 4),
            "supporting_f1": round(sum(f1) / max(1, len(f1)), 4),
        }
    latencies = sorted(r.graph_ms for r in scored)
    if latencies:
        out["arms"]["graphgraph"]["p50_ms"] = round(latencies[len(latencies) // 2], 1)
        out["arms"]["graphgraph"]["p95_ms"] = round(latencies[min(len(latencies) - 1, int(len(latencies) * 0.95))], 1)
    by_level: dict[str, dict] = {}
    for level in sorted({r.level for r in scored if r.level}):
        subset = [r for r in scored if r.level == level]
        by_level[level] = {
            "n": len(subset),
            "graphgraph_em": round(sum(_score(r.graph_titles, r.gold)[0] for r in subset) / len(subset), 4),
            "bm25_em": round(sum(_score(r.lexical_titles, r.gold)[0] for r in subset) / len(subset), 4),
        }
    out["by_level"] = by_level
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--limit", type=int, default=100, help="questions to score (0 = all)")
    parser.add_argument("--k", type=int, default=2, help="titles retained per question; HotpotQA has 2 gold")
    parser.add_argument("--seed", type=int, default=20260819)
    parser.add_argument("--source-mode", default="all", help="'all' consults semantic; 'auto' is the shipped default")
    parser.add_argument("--json", type=Path, help="write the full per-task record here")
    args = parser.parse_args()

    if not args.data.exists():
        print(f"missing dataset: {args.data}\nSee benchmarks/external/README.md for the download command.", file=sys.stderr)
        return 2

    import pyarrow.parquet as pq

    table = pq.read_table(args.data)
    rows = table.to_pylist()
    random.Random(args.seed).shuffle(rows)
    if args.limit:
        rows = rows[: args.limit]

    print(f"scoring {len(rows)} HotpotQA questions (k={args.k}, source_mode={args.source_mode})", file=sys.stderr)
    results = run(rows, args.k, args.source_mode)
    summary = summarize(results)
    print(json.dumps(summary, indent=2))

    if args.json:
        args.json.write_text(
            json.dumps(
                {
                    "summary": summary,
                    "tasks": [vars(r) for r in results],
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
