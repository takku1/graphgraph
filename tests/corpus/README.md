# The polyglot acceptance corpus

`polyglot/` is a fixed, committed, 15-language corpus, and `polyglot.snapshot`
is the canonical dump of the graph it produces. Together they are the gate that
distinguishes a **reorganisation** from a **capability change**:

| Kind of change | Expected effect on `polyglot.snapshot` |
|---|---|
| Reorganisation (e.g. moving grammar tables to `.scm` queries) | **zero bytes change.** Any diff is a bug. |
| Capability change (e.g. a new resolution layer) | **the diff is the evidence.** Regenerate and justify it in the commit message. |

Regenerate with `python scripts/graph_snapshot.py write`; check with
`python scripts/graph_snapshot.py check`. `tests/test_graph_snapshot.py` runs
the check automatically.

## Why the corpus looks the way it does

Every language defines the *same six names* — `Middle`, `Entry`, `Assist`,
`Service`, `Handle`, `Run` — in a **single flat directory**. That is
deliberate, and it is the property that makes the corpus load-bearing.

Repository-wide name lookup is therefore maximally ambiguous: there are 15
symbols called `Middle`. A resolver that matches on bare name alone cannot
produce a correct answer here, only a lucky one. Concretely, each language
contributes four things:

- **a same-file call** — `Entry()` calls `Middle()` in the same file;
- **a cross-file call** — `Entry()` calls `Assist()` defined in `helper`;
- **a member call** — `Service.Run()` calls its sibling `Handle()`;
- **an uncalled decoy** — `helper` defines its own `Middle`, never called.

The decoy is what separates "the right answer" from "the only answer." The
language-coverage finding recorded Ruby and Scala tests that passed *with their
fix reverted*, purely because the target name was globally unique; adding a
same-named sibling denied that fallback. A scope-resolution fixture with no
name collision is not testing scope resolution.

Go omits the decoy: two `Middle` functions in one package is a redeclaration
error, and a fixture that does not parse tests nothing.

## What the baseline currently records

Not all of it is correct behaviour, and it is not supposed to be. The snapshot
is a record of what the scanner does *today*, including its open defects, so
that a change which fixes one shows up as a visible, reviewable diff:

- **PHP** `$this->Handle()` and **Swift** `self.Handle()` both fall to
  `unknown_receiver` — 13 of 15 internal member calls resolve, an 86.67% rate.
- Five bare calls are unmatched.

Both are targets for the name-resolution work, and both should move this file
when they are fixed.
