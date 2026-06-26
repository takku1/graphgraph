# Model-Answer Test Battery

This is the first live-model test plan for `graphgraph`.

The goal is not to prove that the smallest packet always wins. The goal is to
find the lowest-cost packet that still preserves reasoning accuracy.

## Status

This document describes the target and testable hypotheses, not a proven
performance claim. A packet format only becomes a recommendation after it
passes the gates below on frozen prompts.

## Core Hypothesis

For codebase graph context, the optimal LLM-facing packet may not be the
canonical storage format. The target is a compact, query-specific wire format
that keeps graph evidence dense while providing only enough schema to prevent
model misreads.

Expected ordering:

1. `lowlevel_schema`: lowest token floor, best if the model can decode it
2. `sql_schema`: fallback when explicit column anchors improve recall
3. `hybrid_schema`: fallback when source snippets are required for semantic
   grounding
4. Markdown/JSON/GraphML: useful baselines, not expected winners for dense
   graph evidence

## Battery 1: Cheap-Model Packet Viability

Run first on the cheapest fast model available.

Purpose:

- expose whether `lowlevel_schema` is too compressed for weaker models
- measure TTFT sensitivity to packet size
- avoid tuning against an expensive frontier model

Inputs:

- `out/protocol/model_reasoning_prompts.jsonl`
- `out/protocol/prompt_preflight.md`
- variants: `lowlevel_schema`, `sql_schema`, `hybrid_schema`
- hops: `1`, `2`
- tasks: direct lookup, reverse lookup, multi-hop path, blast radius,
  subsystem summary, negative query

Pass gates:

- JSON parse pass rate: `>= 0.98`
- node recall: `>= 0.90`
- edge recall: `>= 0.85`
- hallucinated edge rate: `<= 0.03`
- negative-query false-positive edge rate: `0.00`

Decision rule:

- If `lowlevel_schema` passes, keep it as the default packet.
- If `lowlevel_schema` fails but `sql_schema` passes, make SQL rows the
  adaptive fallback.
- If both fail on semantic tasks but `hybrid_schema` passes, route abstract
  summary/explanation queries to hybrid packets only.

## Battery 2: Frontier-Model Sanity Check

Run only after Battery 1 finds a candidate winner.

Purpose:

- verify that the packet ranking is not an artifact of one small model
- measure how much stronger models reduce the need for verbose schema
- establish the best-possible recall/latency frontier

Inputs:

- same prompt records as Battery 1
- same temperature: `0`
- same strict JSON output contract

Pass gates:

- no lower than Battery 1 on recall
- no higher than Battery 1 on hallucinated edge rate
- same format ordering on median prompt tokens and TTFT

## Battery 3: Prompt-Schema Ablation

Run only on synthetic corpora first.

Compare:

- `lowlevel_bare`
- `lowlevel_schema`
- `lowlevel_verbose_schema`
- `sql_schema`
- `compact_schema`
- `hybrid_schema`

Purpose:

- isolate the minimum schema needed for model accuracy
- decide what belongs in a cached prefix versus per-packet payload

Pass gates:

- cached prompt token count improves over uncached
- `lowlevel_schema` should outperform `lowlevel_bare` on parse/edge recall
- `lowlevel_verbose_schema` must justify its token cost with measurable recall
  gains, otherwise reject it

## Battery 4: Real-Repo Transfer

Run only after synthetic prompt generation and answer scoring are stable.

Use:

- `external_repos.lock.json` as the source of truth
- one small repo first
- one medium repo second
- one large repo last

Purpose:

- test whether generated/synthetic graph patterns transfer to real code
- measure whether irrelevant-context pressure changes the winning packet
- catch parser and extraction errors hidden by synthetic data

Minimum repo order:

1. `python_click`
2. `python_requests`
3. `python_httpx`
4. `rust_mdbook`
5. `typescript_vite`

## Battery 5: Source-Route Ablation

Run after both a document parser and a code/AST parser can emit the shared graph
IR.

Compare:

- Markdown/wiki-derived IR
- SQLite/table-derived IR
- code/AST-derived IR
- merged document+code IR

Purpose:

- test whether document-native context is easier for models to interpret than
  code-native graph context
- test whether AST-derived edges are worth their extraction complexity
- find whether merged IR improves recall or just adds noise

Pass gates:

- same query set across every route
- same packet encoders across every route
- same model prompts except for packet body
- report route-level extraction coverage separately from packet-level model
  accuracy

## Metrics To Report

Every live run should report:

- model name
- packet variant
- hop depth
- prompt tokens
- output tokens when available
- TTFT milliseconds
- total latency milliseconds
- parse pass/fail
- node recall
- edge recall
- hallucinated node count
- hallucinated edge count
- negative-query false positives
- estimated input cost
- estimated output cost

## Anti-Cheating Rules

- Generate prompts before running the model.
- Reuse the same saved prompts for every model.
- Do not edit a packet after seeing an answer unless starting a new named
  benchmark version.
- Do not compare a cached-schema packet against an uncached verbose packet
  without reporting both cached and uncached token counts.
- Do not use expected answers in retrieval, packet construction, or prompt
  wording.
- If a model returns invalid JSON, count it as a parse failure. Do not manually
  repair the answer for scoring.
