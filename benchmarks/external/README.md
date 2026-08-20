# External benchmarks

Public, held-out datasets this project did not build and cannot tune against.
They exist to answer one question the in-repo suites structurally cannot:
**does GraphGraph retrieve the right context on a corpus nobody here chose?**

Everything in this directory is opt-in and downloads nothing at import time.
Data lives outside the repository (default `.scratch/benchmarks/data/`, which
is git-ignored) so a 27 MB corpus is never committed.

## HotpotQA (multi-hop retrieval)

- **Source:** `hotpotqa/hotpot_qa`, `distractor` config, `validation` split,
  mirrored as parquet by HuggingFace. Upstream: <https://hotpotqa.github.io/>.
  CC BY-SA 4.0.
- **Why this one:** each question ships 10 paragraphs, exactly 2 of which are
  the gold supporting documents, and answering requires combining both. That is
  a direct test of the claim a context graph makes over flat search -- connect
  facts across documents -- and the distractors make lexical overlap an
  actively misleading signal.
- **What is scored:** supporting-paragraph *retrieval*, not answer generation.
  Generation would measure whichever LLM was attached; retrieval measures this
  tool. Metrics are the HotpotQA supporting-fact convention -- per-question
  Exact Match (both gold titles retrieved, at rank <= k) and F1 over retrieved
  vs gold titles.
- **Setup:**

  ```
  curl -L -o .scratch/benchmarks/data/hotpot_distractor_validation.parquet \
    https://huggingface.co/datasets/hotpotqa/hotpot_qa/resolve/main/distractor/validation-00000-of-00001.parquet
  python benchmarks/external/hotpotqa.py --limit 100
  ```

## CodeSearchNet (natural-language code retrieval)

- **Source:** `code-search-net/code_search_net`, `python` config, `test` split,
  mirrored as parquet by HuggingFace. Upstream: <https://github.com/github/CodeSearchNet>.
  MIT / permissive per-repository licences.
- **Why this one:** it is the gap R-006 names. HotpotQA is Wikipedia prose, and
  a retrieval change validated only there passed every gate and still rewrote
  anchors on 22% of ordinary queries against a real code graph. This is a
  *code* corpus: 22,176 held-out Python functions across 680 real repositories,
  with real file paths and real module layout.
- **What is scored:** a developer asks in English, and the target function
  should be retrieved. Each task reconstructs a whole repository from its
  functions, scans it, and looks for the target among the ranked anchors.
  Metrics are recall@k and MRR against an Okapi BM25 arm over the same corpus.
- **Docstrings are stripped from the corpus.** The query *is* the docstring, so
  leaving it in would make every task a substring match -- the same defect this
  project already shipped once in its own conceptual fixture (R-005).
- **Abstention is reported separately from ranking.** They are different
  defects with different fixes, and summing them into one recall number hides
  which one is happening.
- **Setup:**

  ```
  curl -L -o .scratch/benchmarks/data/csn_python_test.parquet     https://huggingface.co/api/datasets/code-search-net/code_search_net/parquet/python/test/0.parquet
  python benchmarks/external/codesearchnet.py --limit 60
  ```

## Reporting rule

Report the axis where GraphGraph loses. A comparison that only shows wins is
not evidence, and this project's own evidence bar says so.
