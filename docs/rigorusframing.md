# Rigor Notes

This document is a review checklist, not an architectural claim. It exists so
the remaining work stays tied to evidence rather than to a narrative.

## Promotion Rules

Do not promote a packet format, traversal policy, or planner change unless all
of the following are true:

- it improves a benchmark that measures the relevant behavior,
- it keeps mechanical validation green,
- it does not regress answerability on the saved real-project corpus,
- it has a clear token-cost explanation,
- live model scoring has been run if the change is intended to affect model
  quality rather than only retrieval shape.

## Current Status

- frontier traversal is now passing the saved benchmark suite,
- packet validation is stable for `gg_max`, `semantic_arrow`, and
  `gg_max_hybrid`,
- live reasoning scoring is still blocked locally because no model API key is
  available in environment or credential store.

## Claims That Still Need Evidence

- lexical node handles outperform numeric IDs,
- dynamic sparse/dense context switching improves answer quality,
- `gg_max_hybrid` is better than `gg_max` for doc-heavy corpora,
- any quantization claim that mixes runtime compression with prompt compression.

## What To Keep Writing

Write architecture only when it is about the system boundary or data flow.
Write empirical findings only when there is a benchmark or saved run behind the
claim.
Write hypotheses separately and label them as hypotheses.

The codebase should not have exploratory prose masquerading as settled design.
