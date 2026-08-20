#!/usr/bin/env python
"""Score GraphGraph on CodeSearchNet natural-language code retrieval.

This exists because of a specific failure. A retrieval change was validated on
HotpotQA -- ten-paragraph Wikipedia corpora -- passed every gate, and then
rewrote anchors on 22% of ordinary queries against this repository's own code
graph, displacing literal answers. Prose benchmarks cannot see that. A codebase
context tool needs a code corpus, and this is it (ROADMAP R-006).

Design follows the shape of the real product question: a developer asks in
English and expects the function that does it. Each task reconstructs a whole
repository from CodeSearchNet's held-out split -- real file paths, real module
layout, many functions per file -- scans it into a graph, and asks whether the
target function is retrieved.

Two decisions that keep this honest:

* **Docstrings are stripped from the corpus.** The query *is* the docstring, so
  leaving it in the file makes every task a substring match. That mistake was
  already made once in this project's own conceptual fixture (R-005), where
  docstrings restated their queries verbatim and produced a fake 0.80.
* **The corpus is a whole repository, not the target plus distractors.** The
  failure this benchmark exists to catch -- garbage follow-up queries built
  from concatenated headings, anchors displaced by unrelated modules -- only
  appears at realistic scale with realistic identifier shapes.

Usage:
    python benchmarks/external/codesearchnet.py --limit 60
    python benchmarks/external/codesearchnet.py --repo apache/airflow --limit 100
"""

from __future__ import annotations

import argparse
import ast
import json
import math
import random
import re
import sys
import tempfile
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

DEFAULT_DATA = REPO_ROOT / ".scratch" / "benchmarks" / "data" / "csn_python_test.parquet"
_WORD = re.compile(r"[A-Za-z0-9_]+")
#: Repositories small enough to scan per task but large enough to be realistic.
_MIN_FUNCTIONS = 40
_MAX_FUNCTIONS = 600


@dataclass
class TaskResult:
    repo: str
    func_name: str
    path: str
    query: str
    graph_rank: int | None = None
    lexical_rank: int | None = None
    graph_ms: float = 0.0
    error: str = ""
    status: str = ""
    anchors: int = 0


def _split_identifier(name: str) -> list[str]:
    parts: list[str] = []
    for chunk in name.split("_"):
        parts.extend(re.findall(r"[A-Z]+(?![a-z])|[A-Z][a-z]*|[a-z]+|\d+", chunk) or [chunk])
    return [p for p in parts if p]


def _tokens(text: str) -> list[str]:
    out: list[str] = []
    for raw in _WORD.findall(text or ""):
        out.append(raw.lower())
        out.extend(part.lower() for part in _split_identifier(raw) if part.lower() != raw.lower())
    return out


def _strip_docstrings(source: str) -> str:
    """Remove docstrings so the query is not literally present in the corpus."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return source
    spans: list[tuple[int, int]] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)):
            continue
        body = getattr(node, "body", None)
        if not body:
            continue
        first = body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
            and first.end_lineno is not None
        ):
            spans.append((first.lineno, first.end_lineno))
    if not spans:
        return source
    drop = {line for start, end in spans for line in range(start, end + 1)}
    return "\n".join(line for index, line in enumerate(source.splitlines(), 1) if index not in drop)


def _build_repo(root: Path, rows: list[dict]) -> dict[str, str]:
    """Write a repository from its functions, grouped by real file path."""
    by_path: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_path[row["func_path_in_repository"]].append(row)
    written: dict[str, str] = {}
    for rel, funcs in by_path.items():
        rel = rel.replace("\\", "/").lstrip("/")
        if not rel.endswith(".py") or ".." in rel:
            continue
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        body = "\n\n".join(_strip_docstrings(f["whole_func_string"] or f["func_code_string"]) for f in funcs)
        try:
            target.write_text(body + "\n", encoding="utf-8")
        except OSError:
            continue
        for f in funcs:
            written[f["func_name"]] = rel
    return written


def _bm25_rank(query: str, docs: list[tuple[str, str]], target: str) -> int | None:
    """Rank of *target* under Okapi BM25 over the same corpus (1-based)."""
    k1, b = 1.5, 0.75
    tokenized = [_tokens(text) for _name, text in docs]
    n = len(tokenized)
    avgdl = sum(len(d) for d in tokenized) / max(1, n)
    df: Counter[str] = Counter()
    for doc in tokenized:
        df.update(set(doc))
    scored: list[tuple[float, str]] = []
    q = _tokens(query)
    for (name, _text), doc in zip(docs, tokenized):
        tf = Counter(doc)
        length = len(doc)
        score = 0.0
        for term in q:
            if term not in tf:
                continue
            idf = math.log(1 + (n - df[term] + 0.5) / (df[term] + 0.5))
            score += idf * (tf[term] * (k1 + 1)) / (tf[term] + k1 * (1 - b + b * length / max(1, avgdl)))
        scored.append((score, name))
    scored.sort(key=lambda item: (-item[0], item[1]))
    for index, (_score, name) in enumerate(scored, 1):
        if name == target:
            return index
    return None


def _rank_of(graph, starts, func_name: str, limit: int) -> int | None:
    """Position of the target function among ranked anchors (1-based)."""
    seen: list[str] = []
    for node_id in starts:
        node = graph.nodes.get(node_id)
        if node is None:
            continue
        label = str(node.label or "")
        short = label.rsplit(".", 1)[-1]
        if short and short not in seen:
            seen.append(short)
        if len(seen) >= limit:
            break
    target = func_name.rsplit(".", 1)[-1]
    return seen.index(target) + 1 if target in seen else None


def run(rows_by_repo: dict[str, list[dict]], tasks: list[dict], k: int, source_mode: str) -> list[TaskResult]:
    from graphgraph.io import save_graph
    from graphgraph.platform.compiler import CompileRequest, ContextCompiler
    from graphgraph.scanner import scan_directory

    results: list[TaskResult] = []
    by_repo: dict[str, list[dict]] = defaultdict(list)
    for task in tasks:
        by_repo[task["repository_name"]].append(task)

    for repo, repo_tasks in by_repo.items():
        rows = rows_by_repo[repo]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            root.mkdir()
            _build_repo(root, rows)
            docs = [
                (r["func_name"], _strip_docstrings(r["whole_func_string"] or r["func_code_string"]))
                for r in rows
            ]
            try:
                graph = scan_directory(root, depth="symbols", frontend="tree_sitter", docs=True)
                graph_path = Path(tmp) / "graph.json"
                save_graph(graph, graph_path)
                compiler = ContextCompiler.open(
                    graph_path,
                    graph=graph,
                    enable_evidence=False,
                    source_mode=source_mode,
                    memory_scopes=(),
                )
            except Exception as exc:  # noqa: BLE001
                for task in repo_tasks:
                    results.append(
                        TaskResult(repo, task["func_name"], task["func_path_in_repository"], "", error=str(exc)[:120])
                    )
                continue

            for task in repo_tasks:
                query = " ".join((task["func_documentation_string"] or "").split())[:220]
                result = TaskResult(repo, task["func_name"], task["func_path_in_repository"], query)
                if not query:
                    result.error = "empty docstring"
                    results.append(result)
                    continue
                try:
                    started = time.perf_counter()
                    outcome = compiler.compile(CompileRequest(query=query))
                    result.graph_ms = (time.perf_counter() - started) * 1000
                    result.graph_rank = _rank_of(graph, outcome.retrieval.starts, task["func_name"], k)
                    result.anchors = len(outcome.retrieval.starts)
                    answerability = outcome.retrieval.metadata.get("answerability", {})
                    result.status = str(answerability.get("status", ""))
                except Exception as exc:  # noqa: BLE001
                    result.error = f"{type(exc).__name__}: {exc}"[:160]
                result.lexical_rank = _bm25_rank(query, docs, task["func_name"])
                results.append(result)
    return results


def summarize(results: list[TaskResult], k: int) -> dict:
    scored = [r for r in results if not r.error]
    out: dict = {"tasks": len(results), "errors": sum(1 for r in results if r.error), "k": k, "arms": {}}
    for arm, attr in (("graphgraph", "graph_rank"), ("bm25", "lexical_rank")):
        ranks = [getattr(r, attr) for r in scored]
        hits = [r for r in ranks if r is not None and r <= k]
        mrr = sum(1.0 / r for r in ranks if r is not None and r <= k) / max(1, len(ranks))
        out["arms"][arm] = {
            f"recall_at_{k}": round(len(hits) / max(1, len(ranks)), 4),
            "mrr": round(mrr, 4),
        }
    latencies = sorted(r.graph_ms for r in scored if r.graph_ms)
    if latencies:
        out["arms"]["graphgraph"]["p50_ms"] = round(latencies[len(latencies) // 2], 1)
        out["arms"]["graphgraph"]["p95_ms"] = round(latencies[min(len(latencies) - 1, int(len(latencies) * 0.95))], 1)
    out["repos"] = len({r.repo for r in scored})
    # An abstention and a wrong ranking are different defects with different
    # fixes, so they are never summed into one recall number here.
    abstained = [r for r in scored if r.anchors == 0]
    out["abstained"] = {
        "count": len(abstained),
        "share": round(len(abstained) / max(1, len(scored)), 4),
        "recoverable": sum(1 for r in abstained if r.lexical_rank and r.lexical_rank <= k),
    }
    answered = [r for r in scored if r.anchors > 0]
    if answered:
        hits = sum(1 for r in answered if r.graph_rank is not None and r.graph_rank <= k)
        out["arms"]["graphgraph"][f"recall_at_{k}_when_answered"] = round(hits / len(answered), 4)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--limit", type=int, default=60, help="tasks to score")
    parser.add_argument("--k", type=int, default=10, help="rank cutoff for recall@k")
    parser.add_argument("--repo", help="restrict to one repository")
    parser.add_argument("--seed", type=int, default=20260819)
    parser.add_argument("--source-mode", default="auto", help="'auto' is the shipped default; 'all' forces semantic")
    parser.add_argument(
        "--no-abstain",
        action="store_true",
        help=(
            "research arm: disable ungrounded-packet abstention so the ranking "
            "underneath it can be measured. Not a supported mode -- it answers "
            "the question 'what would have been returned if the gate had not "
            "fired', which is the only way to tell a protective abstention from "
            "a discarded correct answer."
        ),
    )
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()

    if not args.data.exists():
        print(f"missing dataset: {args.data}\nSee benchmarks/external/README.md.", file=sys.stderr)
        return 2

    import pyarrow.parquet as pq

    rows = pq.read_table(args.data).to_pylist()
    by_repo: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_repo[row["repository_name"]].append(row)
    eligible = {
        name: rs
        for name, rs in by_repo.items()
        if _MIN_FUNCTIONS <= len(rs) <= _MAX_FUNCTIONS and (not args.repo or name == args.repo)
    }
    if not eligible:
        print("no eligible repositories", file=sys.stderr)
        return 2

    rng = random.Random(args.seed)
    candidates = [r for rs in eligible.values() for r in rs if (r["func_documentation_string"] or "").strip()]
    rng.shuffle(candidates)
    tasks = candidates[: args.limit]

    if args.no_abstain:
        from graphgraph.retrieval import result_assembly

        def _keep_everything(metadata, selection, selected_matches, nodes, edges, starts):
            return selected_matches, nodes, edges, starts

        result_assembly._apply_ungrounded_packet_abstention = _keep_everything
        print("research arm: ungrounded-packet abstention DISABLED", file=sys.stderr)

    print(
        f"scoring {len(tasks)} CodeSearchNet tasks over {len({t['repository_name'] for t in tasks})} "
        f"repositories (k={args.k}, source_mode={args.source_mode})",
        file=sys.stderr,
    )
    results = run(eligible, tasks, args.k, args.source_mode)
    summary = summarize(results, args.k)
    print(json.dumps(summary, indent=2))
    if args.json:
        args.json.write_text(json.dumps({"summary": summary, "tasks": [vars(r) for r in results]}, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
