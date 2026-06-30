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
| **Confidence-Boost Range** | 0.80 - 1.00 | N/A | **0.80 - 0.90** |
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

### 4. Confidence-Boost Logic Validation
* The confidence-boost logic successfully adjusted the confidence weights of the `explains` edges based on degree centrality.
* Boosted confidence values range from **0.80 to 0.90**. 
* The max confidence of `0.90` (instead of 1.00) indicates that the highest-degree nodes in the graph (e.g. core package directories or prelude files) are not target symbols of `explains` edges. The target symbols themselves are moderately central, receiving up to +10% boost.

---

## 3. Recommended Next Steps

### 1. Refactor/Tuning the Confidence-Boost Formula
Currently, the centrality boost uses the absolute degree of a node normalized against the maximum degree in the graph:
$$\text{boost} = 0.2 \times \frac{\text{degree}(v)}{\text{max\_degree}}$$
* **Problem**: In a hybrid graph, file nodes and directories have a massive degree compared to symbol nodes (e.g. a directory node `dir_Init` has hundreds of `contains` edges, whereas a theorem symbol node `Nat.lt_succ_self` has a degree of 5-10). Normalizing against `max_degree` makes the boost for code symbols very small.
* **Refactoring Proposal**: Normalize degree centrality *within* the same node kind (e.g., normalize a symbol's degree against the max degree of any symbol node, not directory/file nodes). This will scale the boost range for code symbols to its full potential (+20%).

### 2. Leverage Symbol Visibility & Modifiers
We can use the matched modifiers (like `private` or `protected` in Lean, or double-underscore prefixes in Python) as additional weights or confidence signals without needing new edges. For instance:
* `private` definitions could have their reference confidence slightly penalized because they are local and less likely to be target anchors for cross-module queries.
* Public/exported symbols or core structures can get a baseline confidence boost.
