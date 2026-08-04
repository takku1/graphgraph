# Q02-D language volume and C++ hold

Date: 2026-07-31

## Decision

Continue Q02-D with C# next. Do not promote the experimental C++ out-of-line
owner slice yet.

C++ has the largest measured topology gap, but the experiment showed that
recovering its omitted definitions changes the callable universe before
GraphGraph has a namespace-, overload-, macro-, and translation-unit-aware
identity model. The apparent receiver gain is real, but the end-to-end call
delta is not precise enough to ship.

GraphGraph output was diagnostic evidence, not the oracle. Pinned source and
normalized before/after topology determined the hold.

## Fresh pinned measurements

All scans used the current `f46cbe1` engine, tree-sitter, symbol depth, no
documents, no history, and no incremental restoration.

| repository | revision | dominant language | resolved | unknown receiver | ratio |
| --- | --- | --- | ---: | ---: | ---: |
| ripgrep | `227381db0ee83dfa4341f1e27ff9617c0f5ad992` | Rust | 1,210 | 2,328 | 34.20% |
| UniGetUI | `5b05b35bedfa5e15927c4e586644a0e40c9aba4a` | C# | 486 | 5,271 | 8.44% |
| Z3 | `1564e00215e18dc3557ee86bae4a9d91e098c449` | C++ stratum | 14 | 31,053 | 0.045% |

The dominant-language repository receiver-shape histograms were:

| repository | call result | complex | field chain | named local | short local |
| --- | ---: | ---: | ---: | ---: | ---: |
| ripgrep | 938 | 435 | 160 | 632 | 163 |
| UniGetUI | 33 | 650 | 872 | 3,665 | 51 |

Z3 is multi-language. Its status metadata reports one aggregate shape
histogram, not a per-language partition, so assigning those shapes to C++
would overstate the instrument. The per-language outcome counters are valid;
the shape split needs a language dimension before it can rank C++ sub-buckets
cleanly.

Z3's Java stratum was already much stronger at
`1,559 / (1,559 + 1,300) = 54.53%`. The held-out C# repository is therefore
the next actionable low stratum while the C++ identity prerequisite is built.

## C++ experiment

Pinned Z3 contains 14,578 source lines matching a qualified out-of-line
definition shape such as:

```text
solver::adjust_cfg(...)
```

Tree-sitter exposes this owner structurally through nested
`qualified_identifier` declarators. A local experiment:

1. recovered the innermost `(owner, method)` pair;
2. retained lowercase C++ type names instead of treating capitalization as
   type evidence;
3. joined unanimous field facts across headers and implementation files;
4. limited bare calls to same-owner or same-translation-unit candidates; and
5. cached quoted-include stems for constant-time visibility checks.

The final experimental Z3 graph moved the C++ counters:

| metric | baseline | experiment |
| --- | ---: | ---: |
| method-call sites resolved | 14 | 936 |
| ambiguous | 0 | 1 |
| unknown receiver | 31,053 | 10,769 |
| external resolved | 26,723 | 76,316 |
| unmatched | 47 | 10,087 |
| graph nodes | 30,813 | 41,093 |
| graph edges | 64,677 | 78,407 |

The denominator is not comparable: recovering 10,280 omitted definitions also
exposed their bodies and reclassified tens of thousands of previously unseen
or untyped sites. The useful signal is the 922 additional resolved C++ sites,
not the superficially improved ratio.

## Why it did not ship

Normalized by source path/label, target path/label, and relation, the final
experiment added 1,800 logical calls and removed 1,834. That is far beyond a
bounded receiver-only delta.

Source inspection found categorical identity failures:

- before the translation-unit fence, `contrib/qprofdiff/main.cpp`'s
  `std::max` calls linked to an unrelated repository method named `max`;
- headers produced malformed callable identities such as `class`,
  `namespace`, and field/type labels;
- owner leaves such as `power` collided across unrelated namespaces and
  modules;
- newly recovered overloads changed project-global uniqueness and therefore
  rewired pre-existing bare-call edges.

The visibility fence removed the observed `std::max` false edge, but it cannot
repair malformed definition identity or represent transitive includes,
namespaces, overload sets, and macro-defined API functions. Shipping the
receiver gain on top of that unstable identity layer would hide topology
errors behind a better scalar.

All experimental source and test edits were reverted. Only this measurement
receipt is promotable.

## Required C++ prerequisite

Before retrying the receiver slice:

1. represent a C++ callable key as at least
   `(qualified namespace/type owner, method name, overload signature)`;
2. distinguish macro/API wrappers, declarations, and real definitions;
3. construct translation-unit visibility from include edges, including
   header/implementation counterparts, without per-call rescans;
4. resolve bare calls inside a method against lexical owner, bases, and visible
   free functions instead of project-global leaf uniqueness; and
5. gate on a normalized source oracle with zero source-disproved additions.

## Next queue item

UniGetUI's 3,665 `named_local` and 872 `field_chain` sites are the largest
cleanly attributed remaining buckets. The next Q02-D slice should sample those
sites, separate external/framework types from in-repository owners, and
implement only the largest syntactically provable join. C++ remains queued
behind the identity prerequisite above.
