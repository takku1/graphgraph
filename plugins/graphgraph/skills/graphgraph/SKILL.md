---
name: graphgraph
description: Use GraphGraph in Codex for structural codebase questions, dependency lookup, blast radius analysis, multi-hop paths, context packet rendering, packet validation, or graph-backed retrieval. Prefer this over raw file dumps when a repository has or can build a .graphgraph graph.
---

# GraphGraph For Codex

Use GraphGraph as Codex's local codebase context engine. It is a wrapper around
the project CLI and MCP server, not a separate implementation.

## When To Use

Use this skill when the user asks about:

- codebase architecture or subsystem summaries,
- dependencies, callers, blast radius, or multi-hop paths,
- compact graph packets for LLM context,
- `.graphgraph/graph.json` or `.graphgraph/graph.gg`,
- packet validation or retrieval quality.

Do not use it for ordinary single-file edits where reading the file directly is
faster and clearer.

## Preferred Flow

1. Look for `.graphgraph/graph.json` first.
2. If no native graph exists and the task needs structural retrieval, build one:

   ```powershell
   uv run --project . graphgraph scan --directory . --depth symbols --docs --output .graphgraph/graph.json
   ```

3. Route the question to a query class:

   | User need | Query class |
   | --- | --- |
   | What does this file/symbol do? | `direct_lookup` |
   | Who references this symbol? | `reverse_lookup` |
   | What changes if this changes? | `blast_radius` |
   | How does A reach B? | `multi_hop_path` |
   | Summarize a subsystem | `subsystem_summary` |
   | Is this isolated or absent? | `negative_query` |

4. Prefer the bundled MCP server when available. Otherwise use the CLI:

   ```powershell
   uv run --project . graphgraph query "query text" --query-class blast_radius --show-anchors
   uv run --project . graphgraph final --graph .graphgraph/graph.json --query-class blast_radius --starts <node-id-or-label>
   ```

5. Validate packets before relying on format-sensitive conclusions:

   ```powershell
   Get-Content packet.txt | uv run --project . graphgraph validate
   ```

## Evidence Rules

- Treat GraphGraph packets as evidence containers, not final answers.
- For `blast_radius` and `multi_hop_path`, prefer 2-hop evidence unless a
  benchmark or user constraint justifies a narrower packet.
- For negative queries, distinguish direct false-positive edges from unrelated
  local context edges.
- Do not use expected answer keys, benchmark labels, or evaluation fixtures to
  construct retrieval queries or packets.

## Benchmarks

Before promoting scanner, retrieval, traversal, or packet changes, run:

```powershell
uv run --project . python benchmarks/context_graph/promote_check.py
```

Live model-answer scoring is separate and must be explicitly enabled:

```powershell
$env:RUN_OPENAI_REASONING_EVAL="1"; uv run --project . python benchmarks/context_graph/model_reasoning_benchmark.py
$env:RUN_GEMINI_REASONING_EVAL="1"; uv run --project . python benchmarks/context_graph/model_reasoning_benchmark.py
```

Keep Gemini support intact. Codex integration is an additional distribution
surface, not a replacement for OpenAI or Gemini benchmark providers.
