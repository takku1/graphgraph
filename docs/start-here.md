# Start Here

The one blessed path from a fresh checkout to a working context packet. One
command per stage. Everything else in `docs/` is architecture detail for when
you need to go deeper — you don't need any of it to get running.

```powershell
# 0. Install and register with your assistant (see README Install section for alternatives)
uv tool install .
graphgraph install

# 1. Confirm the environment is healthy
graphgraph doctor

# 2. Build the graph for the current directory
graphgraph scan --depth symbols --docs

# 3. Ask a question — this discovers anchors and renders a packet in one step
graphgraph context "how does X work" --query-class subsystem_summary

# 4. Sanity-check a packet before trusting it (mechanical validator, not a model judgment)
graphgraph validate --graph .graphgraph/graph.gg

# 5. Pull exact source lines for the nodes a packet named
graphgraph query "where is X defined" --show-stats
```

That's the whole default path: **install → doctor → scan → context → validate
→ query/snippets.**

## What's expert mode

Everything not in the six commands above — alternate packet formats
(`render`/`final` with non-default renderers), the benchmark suite, the
planner's per-query-class policy tuning, git-history ingestion, cross-language
frontend selection — is there for people extending or evaluating the system,
not for getting a packet into an agent's context window. Use the [command
reference](../README.md#command-reference) and the docs index below once
you've outgrown the six commands.

## Where the honesty check lives

Before trusting a specific quantitative claim about this project (token
savings, answerability, packet quality), read
[`docs/rigorous-framing.md`](rigorous-framing.md) first. It's the actual
promotion/evidence bar the project holds itself to, and it lists which claims
are settled vs. still hypotheses.
