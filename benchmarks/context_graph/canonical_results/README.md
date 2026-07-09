# Canonical Reproducible Result

Everything under `benchmarks/context_graph/out/` is gitignored (large,
regenerated, and mostly keyed to whatever repos happen to be checked out
locally). That made every quantitative claim in this project's docs
unverifiable off the author's machine.

This directory is the one exception: a committed, checked-in result from the
one benchmark that needs **no external repo checkout** — `protocol_benchmark.py`
generates its own synthetic corpus from a fixed seed (see `make_corpus` /
`manifest["seed"]` in that script), so it runs identically for anyone who
clones this repo.

## Regenerate it

```powershell
python benchmarks\context_graph\protocol_benchmark.py
```

Output lands at `benchmarks/context_graph/out/protocol/protocol_summary.md`
and `protocol_results.csv`. Diff those against the files in this directory —
that diff *is* the honesty check for this benchmark.

## What's stable vs. what isn't

- **Deterministic** (same corpus seed, same retrieval/rendering code): `tokens`,
  `node_recall`, `edge_recall`, `path_recall`, `irrelevant_context_ratio`,
  `retrieved_nodes`, `retrieved_edges`, `corpus_coverage`. If these differ from
  a fresh run, something in retrieval/rendering changed behavior.
- **Not deterministic** (real wall-clock measurement): `latency_ms`,
  `build_ms`, `render_ms`, `update_ms`. Expect these to vary run to run and
  machine to machine — don't treat a latency diff as a regression by itself.

## Scope of this claim

This is one synthetic-corpus benchmark, not the full empirical program. The
real-project numbers in `docs/empirical-findings.md` (e.g. the promoted shape
rule's measured `2.87%` token savings) still depend on external repos checked
out under `$AIPROJECTS_ROOT` / `resources/`, which aren't part of this repo and
aren't reproducible from a fresh clone. That gap is real — this file doesn't
close it, it just makes sure at least one number in this project can be
checked by someone who isn't the author.
