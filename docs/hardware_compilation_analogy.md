# Systems Analogy: From Assembly/Hardware to LLM Attention Mechanics

This document establishes a rigorous mapping between traditional low-level systems compilation (Assembly $\rightarrow$ Machine Code $\rightarrow$ Register/ALU execution) and next-generation LLM-native context retrieval (Markdown Context $\rightarrow$ Tensor Representation $\rightarrow$ Attention Mask/KV Cache execution).

---

## 🗺️ The Compilation Stack Mapping

| Stack Layer | Traditional Systems | LLM-Native Context Graph |
| :--- | :--- | :--- |
| **High-Level Source** | C / C++ Source Code | raw Markdown, file listings, directory trees |
| **Assembly (ASM)** | Text Mnemonics (e.g., `MOV EAX, [ESP+4]`) | Textual graph packets (e.g., `[n] 1 file.py [e] 1 2 contains`) |
| **Binary/Machine Code** | Packed Opcode Bytes (e.g., `0x89 0x44 0x24 0x04`) | Compact CSR arrays, index pointer strings, high-entropy tokens |
| **CPU Cache / Registers** | L1/L2 Cache, General Purpose Registers | **KV Cache** (Key-Value cache prefix-pinning) |
| **CPU execution / ALU** | Hardwired pipelines executing micro-ops | **Attention Matrix Masking** (Softmax-weighted dot-products) |

---

## ⚡ 1. The Assembly vs. Binary Representation

In early LLM context engines, graphs were serialized as verbose JSON or prose. This is the equivalent of trying to execute a program by reading its assembly source code text line-by-line during runtime:
* **The High-Level Overhead**: A markdown representation like `"File A.py contains Function B"` requires the LLM's transformer layers to perform lexical parsing, syntax resolution, and pointer-chasing across the attention window.
* **The LLM Binary Format**: In GraphGraph, formats like `gg_max` or `semantic_arrow` act as context bytecodes. We assign static short integer indices to nodes, converting the text-chasing problem into a dense adjacency vector.

---

## 🧠 2. KV Cache as General Purpose Registers

Just as a compiler optimizes execution loops by pinning active variables into high-speed CPU registers, a context engine optimizes inference latency by utilizing the **Transformer's KV Cache**:

```
[ Static Codebase Graph ]  ==> (Prefilled & pinned in global VRAM KV Cache)
         +
[ Ephemeral Session Diff ] ==> (Appended dynamically; fast incremental prefill)
         +
[ User Active Query ]      ==> (Fastest execution; zero recompilation of static code)
```

By keeping the static AST layer pre-loaded in VRAM as a read-only prefix, the compiler (context planner) avoids re-running the token-prefill phase on unchanged files, reducing processing latency.

---

## 🎛️ 3. Direct Attention Masking: Context-as-Hardware

The ultimate goal of translating "hardware instructions" to LLM context is **bypassing the text token stream entirely**. Instead of feeding text representation to the model, we compile the retrieved sub-graph directly into the GPU attention layers:

$$\text{Attention}(Q, K, V) = \text{Softmax}\left(\frac{QK^T}{\sqrt{d_k}} + S\right)V$$

Where:
* **$QK^T$**: The model's semantic similarity query-key dot-product.
* **$S \in \mathbb{R}^{N \times N}$**: The **Spatial Bias Tensor** representing graph geodesic distances.

### The Hardware Translation:
If `Class A` calls `Function B`, the geodesic distance is $1$. The spatial bias tensor injects a positive bias $S_{A,B}$ directly into the attention matrix. During GPU execution, the attention heads are physically guided along the code pathway without ever reading the words *"Class A calls Function B"*. The graph shape is hardcoded directly into the attention mechanism.

---

## ⚙️ 4. Demand Paging & Context Page Faults

When a codebase is larger than the model's context window limit (e.g., $10^7$ tokens), we encounter a **Context Page Fault**:
1. **LRU Page Replacement**: The Personalized PageRank (PPR) scoring serves as the virtual page table.
2. **Page Fault Resolution**: As the developer navigates the session, the hot path swaps active code modules (pages) into the active context window, discarding stale modules using keystroke-decayed half-life weighting:
   $$W(t) = W_0 \cdot 2^{-\frac{\Delta t}{\lambda}}$$
