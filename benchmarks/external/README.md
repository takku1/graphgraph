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

## Reporting rule

Report the axis where GraphGraph loses. A comparison that only shows wins is
not evidence, and this project's own evidence bar says so.
