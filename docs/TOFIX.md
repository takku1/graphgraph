# graphgraph — test findings

Feedback from a test pass on `graphgraph-main`. Setup was clean and the core
engine is solid: `uv pip install -e .` worked first try, and
`doctor / scan / query / profile / export / final` all ran without errors.
Retrieval quality is genuinely good - e.g. the query *"how does the planner
compute the token budget"* returned anchors all inside `planning/budgets.py`,
which is exactly the right neighborhood.

Verification update, 2026-07-04: this note previously claimed the two real bugs
were already fixed, but the working copy did **not** actually contain both fixes.
The empty-packet validator still passed, and `final --starts <bad-id>` exited
nonzero only by dumping a traceback. Both are now fixed and covered by
regression tests. One reported issue turned out to be a **false alarm** on my end
- details below so you don't chase it.

---

## 1. `validate` reported PASS on an empty packet — FIXED

A packet with the right markers but no content used to pass:

```
$ printf 'GRAPH:\n@nodes\n\n@edges\n' | graphgraph validate
PASS semantic_arrow nodes=0 edges=0          # before
FAIL semantic_arrow nodes=0 edges=0          # after
- empty packet: no nodes
```

**Root cause:** each `validate_*` returned `not errors` without checking that
any nodes were actually parsed.

**Fix:** `src/graphgraph/validate.py` — `validate_packet()` now centrally
fails any otherwise-OK result with `node_count == 0` (covers every packet
format in one place). `graphgraph validate` now exits nonzero when validation
fails, which matters for CI and shell pipelines.

---

## 2. `final --starts <bad-id>` failed noisily/uncleanly — FIXED

An unmatched start id originally emitted an empty packet with **exit code 0** and
no useful message. During 2026-07-04 verification it had improved to exit code
1, but only by dumping a Python traceback. Now it names the bad handle, prints a
clean `Error:` message to stderr, and exits nonzero:

```
$ graphgraph final --query-class blast_radius --starts totally_bogus_id
Error: No graph nodes matched the requested starts: ['totally_bogus_id']
  Closest matches in graph:
    ...
$ echo $?
1
```

**Fixes (small, related changes):**
- `src/graphgraph/services/context.py` already rejects unmatched starts before
  rendering an empty packet and includes closest-match suggestions.
- `src/graphgraph/cli/__init__.py` now catches `ValueError` and
  prints a clean `Error: ...` + `sys.exit(1)` instead of dumping a traceback.
- Regression tests cover both bad-start handling and empty-packet validation.

Good start ids are unaffected (no warning, exit 0).

---

## 3. README `final` example — FALSE ALARM, no change needed

I initially flagged the README example `--starts src_graphgraph_cli_py` as
using a wrong node id (no `src_` prefix on real ids). **That was my mistake:** I
had scanned `--directory src`, which strips the `src` path component. The
README's documented step-1 workflow scans `--directory .` (repo root), and with
that the real node id genuinely *is* `src_graphgraph_cli_py`. The example
produces a valid 164-line packet as written. **Nothing to fix here.**

(Possible papercut worth a thought, not a bug: node ids are
scan-root-relative, so the same file gets a different id depending on whether
you scan `.` vs `src`. Documenting that, or normalizing ids, could save users
the confusion I walked into.)

---

## 4. `final` emits two packet formats depending on content — by design, harmless now

`final` emits `@nodes/@edges` (semantic_arrow) for an empty subgraph but
`[r]/[n]/[e]` (gg_max) when populated. This is what let bugs #1/#2 hide. With
those fixed, the empty case now fails loudly, so the format split is no longer a
trap — leaving this as just an FYI.

---

**Net:** core engine (scan / rank / budget) is solid and well-tested. The two
real bugs were both "silent empties that should be loud failures," now fixed and
verified.
