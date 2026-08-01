# Coverage for the seven languages the scope work did not touch

**Date:** 2026-07-31
**Method:** one two-file fixture per language, each with a same-file call, a
cross-file call, and an uncalled decoy sharing a name with a live symbol —
the same shape as `fixtures/polyglot-scope-2026-07-31`, reduced to three
edge classes.
**Companion:** `2026-07-31-critical-graybox-scope-resolution.md`, whose coverage
section listed these seven as untested so that silence would not read as a pass.

---

## Result

| Language | Symbols | Same-file call | Cross-file call | False edge to decoy |
|---|---:|---|---|---:|
| Ruby | 4/4 | yes | yes | 0 |
| Kotlin | 4/4 | yes | yes | 0 |
| Scala | 4/4 | yes | yes | 0 |
| C | 4/4 | yes | yes | 0 |
| C++ | 4/4 | yes | yes | 0 |
| Swift | 4/4 | yes | yes | 0 |
| PHP | 4/4 | yes | yes | 0 |

**Definition extraction is correct in all seven**, with every symbol found at the
right path. **Precision holds everywhere**: no language produced an edge into an
uncalled decoy, which is the property worth protecting most.

Ruby, Scala, Swift, and PHP were fixed by this run. All seven languages now
resolve both edge classes without introducing a false edge to the decoy.

---

## Fixed here

**Ruby.** A top-level `def` parses as a `method` rather than a `function`, and
the file-local binding layer admitted only functions. An ownerless method is a
free function under another name — nothing owns it and a bare call reaches it —
so the layer now admits methods with no owner.

**Scala.** `object Core { def Middle() }` gives the method an owner, so it needs
the enclosing-type scope rather than the file scope. Scala and Ruby joined C#,
Java and C++ as languages where an unqualified call reaches a sibling member.

**Swift.** The grammar represents `Middle() + Assist()` as a nested pair of
call expressions: the outer call's first named child is the entire additive
expression, while its trailing call suffix belongs specifically to the RHS
identifier `Assist`. The generic fallback consequently misclassified `Assist`
as a member call on `Middle()`. Swift call extraction now unwraps that precise
RHS-plus-suffix shape; the regression also keeps a same-named cross-file decoy
to verify that the precision fix remains intact.

**PHP.** The grammar names a bare callee node `name`, a kind missing from the
shared normalized name-node set. Definitions were already present, but calls
never reached resolution. Adding PHP's concrete name node restores both
same-file and cross-file call edges; the decoy assertion remains clean.

---

## Regression cover, and the decoy that makes it load-bearing

All four fixes carry a regression test in `tests/test_scanner_frontends.py`. Each
was verified by reverting the source fix and confirming the test fails, so none of
them passes vacuously.

The Ruby and Scala tests needed one deliberate detail. A first version of each
fixture defined `Middle` only in the core file, and both passed **with the fix
reverted** — `Middle` was globally unique, so repository-wide name resolution
found it without ever consulting the file-local or enclosing-type scope. The test
would have guarded nothing. Adding a same-named `Middle` to the helper file denies
that fallback and forces the scope layer to do the work:

| Language | Without decoy | With decoy |
|---|---|---|
| Ruby | passes with fix reverted | fails with fix reverted |
| Scala | passes with fix reverted | fails with fix reverted |

**A scope-resolution test that does not contain a name collision is not testing
scope resolution.** The decoy is what distinguishes "the right answer" from "the
only answer," and it is the same asymmetry the precision assertions rely on.

---

## A fixture artifact worth recording

C and C++ initially failed the cross-file case in the combined fixture, then
passed when scanned alone. The cause was the fixture, not the tool: C and C++
share one language family by design (they share an extractor and legitimately
call across each other), so `Assist` defined in both `c/helper.c` and
`cpp/helper.cpp` is genuinely ambiguous and correctly dropped.

This is the same trap the predecessor report flagged for Go, whose `Middle` had
to be renamed to satisfy Go's single-package rule. A polyglot fixture that
reuses one symbol name across every language creates collisions inside each
language family, and those collisions are indistinguishable from defects until
the language is isolated. **Isolate before concluding.**

---

## Not claimed

- Three edge classes per language, against nine in the main fixture. Member
  calls, recursion, inheritance and test-to-production edges were not exercised
  here.
- Idiomatic code was not tested. These fixtures are minimal by construction, so
  they establish that a language works at all, not that it works at scale.
