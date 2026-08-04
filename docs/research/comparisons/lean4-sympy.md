# GraphGraph Serialization: SymPy vs. Lean4

This report evaluates codebase context serialization metrics for the Lean4 compiler/runtime repository and compares them to the SymPy benchmark. 

---

## 1. Metric Overview

| Metric | SymPy (Python-heavy) | Lean4 (Old, Fallback Scan) | Lean4 (New, Custom Scanner) |
| :--- | :---: | :---: | :---: |
| **Nodes** | 2,267 | 1,584 | **12,209** |
| **Edges** | 8,239 | 3,825 | **51,602** |
| **Edges/Node Ratio** | 3.63 | 2.41 | **4.227** |
| **Doc Bias (Doc Nodes / Total)** | ~0.81 | ~0.00 | **~0.22** |
| **Explains Edges (Doc -> Code)** | 861 | 0 | **22,801** |
| **Extraction-confidence Range** | provenance-dependent | N/A | **provenance-dependent** |
| **Sample Packet Size (Tokens)** | ~178 | ~120 | **~814** |

---

## 2. Key Findings

### 1. Custom Extractor Activation
* By adding `.lean` to `files.py` (`SOURCE_SUFFIXES`, `PARSEABLE_SUFFIXES`, and `EXT_KIND`) and implementing a custom regex definition parser in `ast.py` to capture Lean-specific declarations (`def`, `theorem`, `lemma`, `inductive`, `structure`, `class`, `abbrev`, `opaque`, `axiom`), we unlocked symbol-level extraction for Lean files.
* This increased the total node count from **1,584 to 12,209** (mostly code symbols, including **5,308 theorems** and **1,539 functions**).

### 2. Cross-File Imports Resolution
* We added Lean module-level import resolution (`import Init.Prelude` $\rightarrow$ `Init/Prelude.lean`) to `imports.py`.
* This generated **1,907 import edges** connecting `.lean` files, providing the structural topological backbone that was previously completely missing for the Lean codebase.

### 3. Document Extraction & Explains Edges
* Running the scanner with the `--docs` flag parsed concepts and sections from markdown documentation files.
* Because the compiler/runtime docs refer to core symbols frequently, we extracted **22,801 `explains` edges** linking doc sections to code symbols.
* This lowered the overall doc-bias from SymPy's high ~0.81 (4:1 doc-heavy) to **~0.22** (about 1:4 doc-to-code ratio). This is a highly balanced retrieval structure.

### 4. Confidence semantics correction (2026-07-12)
* Stored edge confidence now records extraction/provenance reliability only.
* Degree centrality and private/protected visibility no longer mutate that value
  during scanning. Those are relevance signals and belong in query-time ranking.
* This prevents unrelated graph-shape changes from changing whether an edge is
  presented as trustworthy evidence.

---

## 3. Recommended Next Steps

### 1. Calibrate relevance separately from confidence
Benchmark kind-normalized degree, personalized PageRank, and bridge measures as
retrieval features. Do not write them back into edge confidence. Promotion must
improve answer evidence without lowering path/hub recall.

### 2. Leverage Symbol Visibility & Modifiers
We can use the matched modifiers (like `private` or `protected` in Lean, or double-underscore prefixes in Python) as additional weights or confidence signals without needing new edges. For instance:
* `private` definitions can receive a query-dependent anchor penalty because
  they are less likely targets for cross-module queries.
* Public/exported symbols can receive a relevance bonus, without changing the
  confidence of edges that mention them.
