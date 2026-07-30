# Global Project Attention Under Finite Compute

## A research proposal for a dynamic, multiresolution context graph

**Status:** research hypothesis and experimental program, not implemented behavior.

CPUs do not keep every byte in registers. An operating system instead keeps a
virtual address space in which every byte is addressable while only a bounded
working set is resident. Project reasoning should be tested under the same
contract: every source entity remains addressable and represented, while the
active frontier is materialized exactly and the far field is compressed with
measurable error. The analogy is a design constraint, not evidence that the
resulting representation improves an LLM.

**Working thesis:**

> The ideal is global project attention. A context graph should approximate it
> by representing every project entity at some resolution, materializing exact
> detail only where its expected value exceeds its cost, and reporting the mass,
> uncertainty, and provenance of what remains compressed.

This proposal develops a stronger objective than “retrieve the best files.” It
asks how a finite system can preserve the *possibility of influence* from an
entire changing project while operating inside a bounded prompt, latency
budget, memory budget, and model capability.

### Operational definition

> **Global Project Attention (GPA).** A context system exhibits
> $\varepsilon$-GPA for query $q$ when (1) every project entity is
> source-addressable, (2) every entity belongs to exactly one exact or
> traceable aggregate representation chosen conditionally on $q$, and (3) a
> machine-checkable receipt upper-bounds the unresolved *effective* influence
> by $\varepsilon$ under a declared oracle, metric, and model boundary.

Global project attention is not the claim that every token is processed
equally. It is the claim that every project entity remains in the external
influence field, with resolution allocated dynamically according to expected
reasoning value. Exactness is unnecessary, but the approximation, metric, and
error boundary cannot be implicit.

Merely requiring $a_v>0$ is vacuous for common softmax and diffusion operators:
they often assign positive mass to every reachable node by construction. An
entity has **effective influence** only relative to a preregistered threshold
or a counterfactual intervention, such as a measurable change in packet,
answer, loss, or action when the entity's representation is removed or
refined.

The phrase **global project attention** is deliberate. It is related to, but is
not identical to, a transformer's internal softmax attention. For ordinary
model APIs, GraphGraph cannot inject arbitrary attention weights into model
layers. It can only control the external evidence representation, its ordering,
its resolution, and an iterative tool loop. The research target is therefore a
model-independent project-level influence field that can later compile to:

1. a prompt packet for current APIs,
2. an external key-value memory for memory-aware models, or
3. graph-derived attention biases for a model runtime that explicitly supports
   them.

The proposal keeps four layers separate:

| Layer | Object | What can be guaranteed? |
| --- | --- | --- |
| Durable memory | source graph and content | every entity remains addressable and fresh |
| Retrieval/compiler | query-conditioned cover $M_q$ | total cover, budget, provenance, and approximation receipts |
| Ideal external field | evaluator-only $a^*(q,G)$ | a declared mathematical target on oracle-sized tasks |
| Realized model influence | $I_m(v\mid q,M_q)$ | only measured counterfactually for model/runtime $m$; never inferred from packet presence |

Search and vector retrieval normally reason only over selected results. A
context window permits reasoning over included tokens but not omitted project
state. A context graph can keep the whole project represented at varying
resolution, but it only *approximately* reasons over the project until a model
actually uses that representation. The ideal system would make all effective
project influence available simultaneously; this proposal studies bounded
approximations to that ideal.

## 1. The important correction: literal omniscience is impossible

Let a project at time $t$ be a typed attributed graph

$$
G_t = (V_t, E_t, X_t, Z_t),
$$

where $V_t$ contains entities such as symbols, files, tests, requirements,
policies, traces, and documentation; $E_t$ contains typed relationships; $X_t$
contains content and features; and $Z_t$ contains provenance, confidence, and
temporal validity.

Suppose a finite representation $M(G)$ has a fixed capacity smaller than the
information content of every possible project. There must be two distinguishable
projects $G_1 \neq G_2$ with the same representation $M(G_1)=M(G_2)$. A future
query can ask for precisely the fact on which they differ. No decoder receiving
only $M$ can answer both correctly. Therefore:

> No fixed-size, query-independent summary can be lossless for every possible
> project and every possible future query.

This is the relevant information-theoretic boundary. “Nothing is forgotten”
cannot honestly mean “every raw token remains simultaneously recoverable from
a bounded prompt.” It can mean three defensible things instead:

- every source entity remains addressable in durable storage;
- every source entity is covered by either an exact representation or a
  traceable multiresolution aggregate;
- any aggregate can be refined back toward source evidence when a query, edit,
  or uncertainty signal makes that refinement valuable.

The research problem is consequently an **error-bounded, resource-rational
approximation**, not literal finite omniscience.

## 2. The ideal object: an omniscient project influence operator

For a query $q$, agent state $h$, task policy $p$, and project $G_t$, define an
ideal but generally intractable operator

$$
\mathcal{O}(q,h,p,G_t) \rightarrow (y^*, A^*).
$$

$y^*$ is the best answer or action available from the entire project. $A^*$ is
an explanation of which project factors influenced it. Those factors must be
richer than nodes alone:

$$
\mathcal{F}_t = V_t \cup E_t \cup \mathcal{P}_t \cup \mathcal{C}_t,
$$

where $\mathcal{P}_t$ contains relevant paths or higher-order motifs and
$\mathcal{C}_t$ contains communities or hierarchical aggregates. This avoids
an additive-node fallacy: a bug can depend on a path, a contradiction between
two policies, or an interaction among files even when no single node is highly
relevant by itself.

For a simplified node field, define a query-conditioned potential

$$
\psi_v =
\theta_s s(q,v)
+ \theta_g g(q,v,G_t)
+ \theta_r r(v,p)
+ \theta_\tau \tau(v,h,t)
+ \theta_u u(v)
+ \theta_c c(v),
$$

where:

- $s$ is lexical or semantic compatibility,
- $g$ is typed structural influence,
- $r$ is task- and policy-specific relevance,
- $\tau$ is temporal/session activation,
- $u$ is uncertainty or value of inspecting the entity, and
- $c$ is confidence/provenance quality.

An ideal normalized field is then

$$
a_v^* = \frac{\exp(\psi_v/T)}{\sum_{j \in V_t}\exp(\psi_j/T)},
\qquad
\sum_{v \in V_t}a_v^* = 1.
$$

This equation is a target abstraction, not a claim that the score is known.
The actual research task is to learn or approximate $\psi$, represent
higher-order interactions, and estimate the regret caused by compressing the
field.

Do not conflate this evaluator target with either the compiled representation
or model behavior. Let $M_q=C(G_t,q,B,A_m)$ be the external representation
compiled under budget $B$ and adapter capabilities $A_m$, let
$\widehat a(M_q)$ be its reconstructed field, and define realized influence
for model/runtime $m$ counterfactually, for example

$$
I_m(v\mid q,M_q)=
D\!\left(P_m(y\mid q,M_q),
P_m(y\mid q,\operatorname{intervene}(M_q,v))\right).
$$

$D$ is a declared output, loss, or action divergence. Phase 0 can measure
$a^*$ versus $\widehat a$ without an LLM. Only later model rounds can estimate
$I_m$, and black-box APIs permit behavioral estimates rather than claims about
hidden attention tensors.

## 3. Replace a retrieved set with a multiresolution attention field

A binary retriever returns $S \subset V$: selected nodes are present and all
others are absent. The proposed system instead maintains a **coverage
partition** over the full project.

Let $\mathcal{H}_t$ be a hierarchy whose leaves are source entities and whose
internal nodes are semantically and structurally coherent clusters. For each
query, construct:

- an exact active frontier $F \subseteq V_t$;
- an antichain of aggregate cells $\mathcal{K} \subset \mathcal{H}_t$; and
- an optional sparse residual set $R$ for anomalies and bridge entities.

They must satisfy the coverage invariant

$$
V_t = F \;\dot\cup\; R \;\dot\cup\;
\left(\dot\bigcup_{K \in \mathcal{K}} \operatorname{leaves}(K)\right).
$$

Every leaf is therefore represented exactly once at the resolution used for
this query. The system is not claiming that a cluster summary is lossless. It
is claiming that compression is explicit, attributable, and reversible.

Each aggregate cell should contain at least:

- typed node and edge counts;
- one or more semantic/structural centroids or landmark nodes;
- boundary and bridge nodes connecting the cell to other cells;
- high-confidence invariants, policies, and tests;
- a change digest and version interval;
- a source-addressable membership reference;
- score variance and approximation uncertainty; and
- a bounded set of exceptional facts that do not fit the centroid.

The query packet carries exact detail for $F$ and coarse information for
$\mathcal{K}$. When a cell is relevant but internally heterogeneous, it is
split. When its members are uniformly low-value, it remains coarse.

### 3.1 Near field, far field, and sparse exceptions

The most useful computational analogy is the fast multipole method and
hierarchical matrices: compute nearby interactions exactly while approximating
large distant groups collectively. Hierarchical attention research has applied
the same idea to sequences, including
[H-Transformer-1D](https://arxiv.org/abs/2107.11906) and
[Fast Multipole Attention](https://arxiv.org/abs/2310.11960).

For project attention, “distance” cannot be only shortest-path length. It should
combine:

$$
d_q(u,v) =
\beta_1 d_{\text{typed-graph}}(u,v)
+ \beta_2 d_{\text{semantic}}(u,v)
+ \beta_3 d_{\text{scope}}(u,v)
+ \beta_4 d_{\text{temporal}}(u,v).
$$

A cluster is admissible as a far-field aggregate when its internal response to
the current query is sufficiently smooth. One possible criterion is

$$
\Delta(K,q) =
\max_{v \in K}\left|\widehat{\psi}_v - \bar{\psi}_K\right|
+ \lambda_b B(K,q)
+ \lambda_z Z(K)
\le \epsilon_K,
$$

where $B(K,q)$ measures unresolved boundary influence and $Z(K)$ measures stale
or low-confidence evidence. A cell that fails the criterion is refined.

This suggests the decomposition

$$
\widehat{A}
= A_{\text{near}}
+ A_{\text{hierarchical-far}}
+ A_{\text{sparse-exception}}.
$$

The near term protects local precision. The hierarchical term gives global
coverage. The sparse exception term protects rare bridge nodes, policies,
security constraints, and other low-frequency facts that averaging would erase.

### 3.2 Why this is more than community summarization

GraphRAG pregenerates community summaries for global questions
([Edge et al., 2024](https://arxiv.org/abs/2404.16130)). That is an important
precedent, but a global project-attention system needs additional contracts:

- resolution must be query-adaptive rather than fixed at indexing time;
- source changes must invalidate only affected aggregates;
- summaries must expose uncertainty and exceptional members;
- structural paths and typed boundaries must survive compression; and
- the returned cells must form an auditable cover of the project, not merely a
  collection of high-scoring communities.

## 4. Four coupled fields, not one ranking score

A robust system should avoid forcing every concern into one scalar too early.
Maintain four query-conditioned fields and combine them only at planning time.

### 4.1 Structural diffusion field

Let $P_r$ be a transition matrix for relation type $r$ and let
$\omega_r(q,p)$ be a task-dependent relation weight. Define

$$
P(q,p) = \sum_r \omega_r(q,p)P_r.
$$

A Personalized PageRank field is

$$
\pi_q = \alpha s_q + (1-\alpha)P(q,p)^\top\pi_q,
$$

where $s_q$ is the anchor distribution. This gives global support on a
connected graph while concentrating most mass locally. Approximate PPR is known
to be highly localizable in many real graphs; PPRGo uses sparse PPR vectors to
scale graph propagation to millions of nodes
([Bojchevski et al., 2020](https://arxiv.org/abs/2007.01570)). Heat-kernel
diffusion offers a second scale parameter and a different walk-length
distribution ([Chung, 2007](https://doi.org/10.1073/pnas.0708838104)). Modern
local solvers can approximate several graph diffusion equations in sublinear
time when their solutions are localizable
([Bai et al., 2024](https://proceedings.neurips.cc/paper_files/paper/2024/hash/0506ad3d1bcc8398a920db9340f27fe4-Abstract-Conference.html)).

Typed directed software graphs may not always have this localization property.
That becomes a measured precondition, not an assumption.

### 4.2 Semantic compatibility field

Lexical, embedding, and source-fact compatibility supply seeds and weak edges
that topology alone cannot discover. To preserve global influence cheaply, a
semantic attention kernel can be approximated with landmarks or random
features. This is analogous to the linear approximations in
[Performer](https://arxiv.org/abs/2009.14794) and
[Nyströmformer](https://arxiv.org/abs/2102.03902), although GraphGraph would be
approximating a project relevance kernel rather than replacing a model's own
self-attention.

The approximation should be explicitly residualized:

$$
K_{qV} \approx K_{qL}K_{LL}^{+}K_{LV} + e_q,
$$

where $L$ is a set of diverse landmarks and $e_q$ is the measured or estimated
residual. Landmarks should include structural bridges and policy/test nodes,
not only embedding centroids. Diversity-aware selection can be informed by
determinantal point processes, which formalize the quality-versus-redundancy
tradeoff ([Kulesza and Taskar, 2012](https://arxiv.org/abs/1202.3738)).

### 4.3 Temporal and change field

The project is not static. A save, branch switch, test failure, trace, or agent
decision injects a change impulse $\delta_t$:

$$
c_{t+1} = \rho c_t + J\delta_t,
$$

followed by typed diffusion over the affected graph. $\rho$ provides decay and
$J$ maps events to nodes. This is the mathematical version of “a change
perturbs the attention field.”

The system should maintain additive error rather than promise exact dynamic
PageRank. Strong worst-case lower bounds exist for explicitly maintaining some
forms of dynamic PageRank, especially multiplicative approximations on directed
graphs ([Jayaram et al., 2024](https://arxiv.org/abs/2404.16267)). That result
matters: a credible design must allow local residual updates, lazy repair, and
periodic rebuilds rather than assuming every edit can update a globally exact
field in constant time.

### 4.4 Uncertainty and value-of-refinement field

A low relevance estimate is not equivalent to low importance when the estimate
is uncertain. Define the utility of refining a cell as

$$
\operatorname{VoR}(K) =
\frac{\mathbb{E}[L(\widehat{y}) - L(\widehat{y}\mid\operatorname{refine}(K))]
\;\cdot\; \Pr(K\text{ changes decision})}
{\operatorname{tokens}(K)+\eta\operatorname{latency}(K)}.
$$

This is a value-of-information policy: spend computation where another look is
most likely to improve the final decision. It also supplies an exploration
channel. A small budget should be reserved for cells with high uncertainty,
unusual changes, or low similarity but high structural leverage.

## 5. A dynamic algorithm: the Attention Field Compiler

The proposed runtime is an **Attention Field Compiler (AFC)** layered on the
existing `SYNC -> EXTRACT -> NORMALIZE IR -> ANCHOR -> EXPAND -> SELECT -> PACK`
pipeline.

```mermaid
flowchart LR
    A[Project events and query] --> B[Typed graph and temporal state]
    B --> C[Structural semantic temporal uncertainty fields]
    C --> D[Multiresolution hierarchy]
    D --> E[Adaptive refine or coarsen]
    E --> F[Budgeted exact frontier plus aggregate cover]
    F --> G[Prompt memory or native attention adapter]
    G --> H[Model answer and unresolved questions]
    H --> C
```

### 5.1 Offline or amortized state

Maintain:

1. a typed source-grounded graph;
2. a hierarchy over symbols, files, packages, subsystems, and learned
   communities;
3. cluster sketches, boundary sets, landmarks, and exception lists;
4. versioned temporal state and operation logs;
5. cached diffusion bases or sparse seed vectors where empirically useful; and
6. learned calibration models for relevance, uncertainty, and token cost.

Hierarchies should not rely on one partition. File/package containment is
stable and interpretable; call/import communities capture behavior; semantic
clusters capture concepts. The runtime may maintain several overlapping views
but must emit one non-overlapping coverage antichain per packet.

### 5.2 Edit-time update

For a change set $\Delta_t$:

1. splice changed source nodes and typed edges;
2. expire invalid facts rather than silently overwriting provenance;
3. seed a residual queue at changed nodes and adjacent boundaries;
4. update leaf sketches and propagate digests up affected hierarchy paths;
5. recompute only clusters whose error or coherence threshold is violated;
6. update semantic landmarks or diffusion caches lazily;
7. record remaining global approximation error and rebuild debt.

The desired *typical* update cost is

$$
O(|\Delta_t|\log |V| + |\operatorname{affected\ residual}|),
$$

not a guaranteed worst-case bound. Large refactors, hub edits, or community
splits may require a rebuild. The receipt must say so.

### 5.3 Query-time initialization

Construct a seed mixture

$$
s_q = \lambda_l s_{\text{lex}}
+ \lambda_e s_{\text{embed}}
+ \lambda_h s_{\text{history}}
+ \lambda_d s_{\text{diff}}
+ \lambda_p s_{\text{policy}}
+ \lambda_x s_{\text{explore}}.
$$

The weights depend on query class and evidence quality. An exact symbol query
should favor lexical and structural evidence; a subsystem summary should favor
hierarchy and community coverage; a recent-regression query should favor the
change field; a negative query should favor coverage and absence certificates.

### 5.4 Adaptive refinement

Start from the hierarchy root cells. Repeatedly refine the cell with maximum
value of refinement while all constraints remain satisfied:

$$
K^* = \arg\max_K \operatorname{VoR}(K).
$$

This is a candidate policy, not an optimality result. The Phase 0 exact
laboratory already contains a six-leaf counterexample where immediate-gain
greedy has $42.67\%$ more squared-error regret than the exhaustive optimum at
five representation units. Discrete child costs and complementary refinements
break the one-step argument. Consequently the tournament must compare
one-step greedy with exact dynamic programming on small graphs and with
lookahead, knapsack, or bounded approximation methods on larger graphs. Any
production controller must publish regret or an empirical gap to the exact
oracle; “highest local VoR” alone is insufficient.

Stop when one of the following holds:

- the prompt token budget is exhausted;
- the latency or graph-operation budget is exhausted;
- all cells have estimated distortion below their allocated tolerance;
- the expected marginal value of refinement falls below its cost; or
- required facets and evidence contracts are satisfied with calibrated
  confidence.

Adaptive Computation Time provides a neural precedent for spending variable
computation on harder inputs
([Graves, 2016](https://arxiv.org/abs/1603.08983)). Here the halting decision is
external, auditable, and constrained by evidence receipts.

### 5.5 Budgeted selection and packet construction

The compiler solves a multi-objective budget problem:

$$
\max_{F,\mathcal{K},R}
\quad
\underbrace{\widehat{M}}_{\text{attention mass}}
+ \lambda_1\underbrace{\operatorname{coverage}}_{\text{facets/relations}}
+ \lambda_2\underbrace{\operatorname{diversity}}_{\text{nonredundancy}}
+ \lambda_3\underbrace{\operatorname{trust}}_{\text{provenance}}
- \lambda_4\underbrace{\operatorname{distortion}}_{\text{compression error}}
$$

subject to token, latency, and computation budgets. Coverage and diversity are
set functions with diminishing returns, so greedy/submodular approximations are
a practical starting point. Relation quotas and bridge-node reserves prevent a
dense relation class or hub from monopolizing the packet.

The packet should be ordered as a stable global-to-local ladder:

1. task and policy constraints;
2. compact global cells and their mass/error bounds;
3. exact active frontier and typed edges;
4. source facts/snippets for the highest-value nodes;
5. unresolved cells and refinement handles; and
6. an attention receipt.

### 5.6 Iterative reasoning

One packet is rarely enough for complex tasks. The model may return an answer
plus explicit unresolved needs. These become new seeds, after which the compiler
refines the relevant cells. This resembles the coarse-to-fine graph exploration
in [GraphReader](https://arxiv.org/abs/2406.14550) and iterative retrieval in
[RepoCoder](https://arxiv.org/abs/2303.12570), but the proposed loop has a
coverage invariant and an explicit stopping policy.

## 6. What “full attention” means at different model boundaries

The graph, field, cover, receipt schema, and candidate objective are the
model-agnostic core. A thin adapter may serialize the same packet plan as
prompt tokens, tool results, external memory records, or native biases. No
provider name, tokenizer, chat role, KV-cache layout, or hidden-state dimension
may enter the core optimizer. Adapter-specific token cost and capability
constraints are explicit inputs, and unsupported features degrade to the
prompt/tool protocol rather than changing the research claim.

### 6.1 Current black-box API: prompt-compiled attention

The only guaranteed interface is tokens. The AFC can rank, aggregate, order,
and expose refinement handles. It cannot claim to control internal attention.
Long-context models also do not uniformly use all available tokens: relevant
evidence can be neglected depending on position
([Lost in the Middle](https://arxiv.org/abs/2307.03172)), and RULER finds that
effective context can be much smaller than advertised context on multi-hop and
aggregation tasks ([Hsieh et al., 2024](https://arxiv.org/abs/2404.06654)).
Therefore full-corpus prompting is a baseline, not the oracle by definition.

### 6.2 Memory-aware model: graph-routed external memory

The compiler can expose exact nodes or aggregate cells as key-value memory.
[Memorizing Transformers](https://arxiv.org/abs/2203.08913) shows gains from
approximate nearest-neighbor access to stored key-value pairs, while
[Compressive Transformer](https://arxiv.org/abs/1911.05507) and
[Infini-attention](https://arxiv.org/abs/2404.07143) show how fine recent memory
can coexist with bounded compressed history. The project analogue is an exact
working frontier plus compressed global cells.

### 6.3 Open model runtime: graph-biased native attention

If a runtime exposes attention control, typed graph distance and hierarchy can
be injected as biases:

$$
\operatorname{Attn}(Q,K,V)
= \operatorname{softmax}\left(
\frac{QK^\top}{\sqrt{d}}
+ B_{\text{graph}}
+ B_{\text{time}}
+ B_{\text{policy}}
\right)V.
$$

This is closest to literal project attention, but it requires model training or
runtime modification. Sparse-attention work provides design priors:
[Longformer](https://arxiv.org/abs/2004.05150) combines local windows with
task-motivated global tokens, and
[BigBird](https://arxiv.org/abs/2007.14062) combines local, random, and global
attention while retaining a global receptive field. A project-native version
could map these roles to local dependency neighborhoods, exploration edges,
and global policy/community tokens. Whether that helps code reasoning is an
experiment, not a settled claim.

## 7. Required receipts: make approximation observable

Every compiled context should carry a machine-readable receipt with:

- graph and hierarchy version;
- exact frontier, residual exceptions, and aggregate antichain;
- project coverage check;
- estimated attention mass by resolution;
- per-cell distortion/uncertainty bounds;
- stale or invalidated regions;
- relation and facet coverage;
- provenance and confidence distribution;
- bridge nodes preserved or omitted;
- token, latency, and graph-operation costs;
- reasons for each refinement and stopping decision; and
- handles for the highest-value next refinements.

A minimal mass accounting is

$$
1 = \widehat{M}_{\text{exact}}
+ \widehat{M}_{\text{aggregate}}
+ \widehat{M}_{\text{residual}}
+ e_{\text{mass}},
$$

where $e_{\text{mass}}$ is reported rather than silently normalized away. This
turns “the graph considered the project” into a falsifiable statement.

## 8. Research questions and preregistered hypotheses

### RQ1 — Approximation

Can a multiresolution field approximate an explicitly computed full-project
influence operator on projects small enough to admit exhaustive computation?

**H1:** at a fixed token budget, exact-near/hierarchical-far packets will have
lower oracle regret than top-$k$ lexical, vector, BFS, or flat-PPR packets.

### RQ2 — Scaling

How does answer quality degrade as $|V|$ grows while the model window stays
fixed?

**H2:** hierarchy changes the degradation curve from abrupt evidence loss to a
slower, calibrated loss in resolution. The claim concerns empirical scaling,
not an assumed asymptotic guarantee.

### RQ3 — Dynamic updates

Can local residual propagation maintain the field after ordinary edits without
global recomputation?

**H3:** for small non-hub diffs, update cost grows with the affected region, not
total project size, while field error remains within a declared tolerance.

### RQ4 — Rare but decisive evidence

Do bridge reserves, exception sketches, and uncertainty exploration recover
facts that smooth diffusion and cluster summaries suppress?

**H4:** the exception channel improves worst-decile evidence recall and reduces
catastrophic misses with a small median token premium.

### RQ5 — Downstream model utility

Does better field approximation improve actual agent performance?

**H5:** improvements in evidence containment will correlate with, but not fully
predict, patch/test success. Packet interpretation and ordering remain separate
causal factors.

### RQ6 — Calibration

Can receipts predict when the system lacks enough context?

**H6:** estimated omitted mass, cell distortion, and facet gaps will predict
answer failure better than raw retrieval score or packet size alone.

### RQ7 — Query adaptivity

Is selective expansion better than always materializing the same graph radius?

**H7:** a value-of-refinement controller will Pareto-dominate fixed hop and fixed
node budgets across direct lookup, path, blast-radius, global summary, change,
and negative-query classes.

## 9. Evaluation program

Evaluation must separate five questions that are often conflated.

| Layer | Question | Principal metrics |
| --- | --- | --- |
| Graph truth | Did extraction represent the project correctly? | node/edge/path precision and recall, provenance accuracy |
| Field approximation | Did the finite field match the declared oracle? | $L_1$/KL mass error, rank correlation, top-mass recall, aggregate distortion |
| Evidence planning | Did the packet contain sufficient nonredundant evidence? | node/edge/path/facet recall, irrelevant ratio, token cost |
| Model use | Did a frozen model understand and use the packet? | answer accuracy, patch success, tests passed, abstention calibration |
| Dynamics | Did edits update the right influence region? | update latency, stale exposure, affected-mass error, rebuild frequency |

### 9.1 Exact-oracle laboratory

Build small synthetic and real projects for which all graph nodes and candidate
interactions fit in memory. Define the oracle scorer *before* evaluating the
approximation. Compute full diffusion, full semantic-kernel rows, exhaustive
path factors up to a declared length, and where possible a full-context model
baseline.

The primary approximation metrics are:

$$
E_1 = \lVert a^* - \widehat{a}\rVert_1,
$$

$$
R_{\text{mass}}(k) = \sum_{v \in \operatorname{TopK}(\widehat{a})} a_v^*,
$$

and task-weighted oracle regret

$$
\mathcal{R} = L(\widehat{y}) - L(y^*).
$$

The oracle must not be used as retrieval evidence during a scored run. It is an
answer key used only after packet construction.

### 9.2 Synthetic graph laboratory

Generate typed graphs with planted evidence and controlled distractors:

- long chains for multi-hop decay;
- stars and scale-free hubs for budget saturation;
- two dense communities joined by one bridge;
- diamond paths for multi-path accumulation;
- disconnected components with semantic-only links;
- duplicated names and lexical adversaries;
- policies that apply globally but have low lexical similarity;
- rare tests that uniquely constrain a common implementation;
- renamed/moved symbols with preserved semantics;
- deleted or expired facts; and
- coordinated edits that split or merge communities.

Scale from $10^2$ to at least $10^7$ lightweight graph nodes in the non-model
benchmark. At each size hold prompt budget constant, then sweep prompt budget
separately. Report quality-versus-size and quality-versus-budget curves, not
only aggregate averages.

### 9.3 Metamorphic and invariant tests

These tests do not require a single known natural-language answer:

1. **Permutation invariance:** relabel internal IDs without changing source
   semantics; field and packet evidence should be equivalent.
2. **Irrelevant-component stability:** add a disconnected unrelated project;
   exact-frontier rankings should change only within a declared normalization
   tolerance, while global coverage grows.
3. **Duplicate-distractor robustness:** clone lexically similar but structurally
   irrelevant nodes; decisive evidence should not be crowded out.
4. **Bridge sensitivity:** remove the only inter-community bridge; cross-boundary
   influence and recommended paths must fall.
5. **Objective-specific refinement:** replacing a cell by its children should
   not increase the preregistered optimization objective. This is
   metric-specific, not a universal theorem: on a measured six-leaf
   counterexample the L2-optimal cover lowers squared error from $0.23737317$
   to $0.23734963$ while L1 error rises from $1.05019035$ to $1.05299159$. L1,
   L2, task loss, calibration, and downstream utility therefore receive
   separate curves and gates.
6. **Mass conservation:** diffusion and aggregation operations must account for
   injected, retained, transmitted, and residual mass.
7. **Version safety:** after a deletion, no packet may cite the expired fact as
   current evidence.
8. **Local edit proportionality:** a leaf edit should not rebuild unrelated
   cells unless a measured global criterion is crossed.
9. **Query paraphrase stability:** meaning-preserving paraphrases should produce
   comparable fields, modulo measured embedding variance.
10. **Negative-query integrity:** absence claims must fail closed when coverage,
    extraction, or freshness is incomplete.

### 9.4 Real repository retrieval tasks

Use the existing GraphGraph evidence-containment suites, then add:

- repository-level retrieval and completion from
  [RepoBench](https://arxiv.org/abs/2306.03091);
- selective-retrieval comparisons inspired by
  [Repoformer](https://arxiv.org/abs/2403.10059);
- long-repository tasks from
  [Long Code Arena](https://arxiv.org/abs/2406.11612);
- multi-file issue repair from
  [SWE-bench](https://arxiv.org/abs/2310.06770) and a fresh or live-updated
  subset to reduce contamination risk; and
- project-history tasks constructed from commits, diffs, tests, and issue text.

For every task, curate a minimal and an acceptable evidence set, required
paths/facets, and forbidden answer-key leakage. The gold patch is never an input
to retrieval. Where gold evidence is ambiguous, use multiple independent
annotators and report agreement.

### 9.5 Downstream agent evaluation

Freeze:

- model and version,
- system prompt,
- tool permissions,
- maximum turns,
- temperature/sampling policy,
- token and wall-clock budgets, and
- execution environment.

Run the frozen comparison first within each model, then repeat it across a
preregistered transfer matrix containing at least:

- two unrelated closed-model provider families when available;
- two unrelated open-weight model families runnable at the chosen scale;
- short-, medium-, and long-context regimes;
- prompt-only and tool-calling protocols; and
- at least two tokenizer families.

All models receive semantically equivalent evidence plans, but adapters may
serialize them according to the model's documented protocol. Report both
per-model results and a hierarchical estimate with model family and repository
as effects. A mechanism is **model-agnostic** only if its deterministic
coverage/receipt invariants are adapter-independent. It is **cross-model
validated** only if it clears guardrails on every preregistered family and its
quality effect does not depend on a single provider. A family-specific winner
is retained as an explicitly scoped adapter policy, not promoted as the global
default.

Change only the context policy. Compare:

1. no external project context;
2. full corpus where it fits;
3. lexical/BM25 top-$k$;
4. embedding top-$k$;
5. fixed-radius graph expansion;
6. flat Personalized PageRank;
7. current GraphGraph planner;
8. multiresolution AFC without iteration; and
9. full AFC with value-of-refinement iteration.

Measure exact answer quality, compile/test success, accepted patch rate,
unnecessary edit count, time-to-first-correct-action, model tokens, retrieval
tokens, graph compute, latency, and total cost. Full corpus is not assumed to
win: long-context utilization must be measured. Long-context suites such as
[LongBench](https://arxiv.org/abs/2308.14508) and RULER motivate explicit
multi-hop and aggregation probes rather than needle retrieval alone.

### 9.6 Dynamic edit benchmark

Replay real commit sequences and controlled mutations. After each change:

1. run the incremental update;
2. compute a from-scratch reference field asynchronously;
3. compare field error and selected evidence;
4. issue preselected change-impact queries;
5. record update/query latency and cells touched; and
6. check whether the receipt correctly predicted rebuild debt.

Stratify edits by leaf change, API signature change, file move, hub change,
policy change, community merge/split, large refactor, and deletion. Plot cost
against actual affected volume rather than raw lines changed.

## 10. Metrics that make the central claim falsifiable

### 10.1 Global Representation Coverage

$$
\operatorname{GRC} =
\frac{|F|+|R|+\sum_{K\in\mathcal{K}}|\operatorname{leaves}(K)|}{|V|}.
$$

This should equal $1$ mechanically. It proves coverage, not usefulness.

### 10.2 Exact Attention Mass Capture

$$
\operatorname{EAMC} = \sum_{v\in F\cup R} a_v^*.
$$

On oracle-sized graphs, this measures how much ideal mass receives exact
representation.

### 10.3 Resolution-Weighted Coverage

$$
\operatorname{RWC} =
\sum_{v\in F\cup R}a_v^*
+ \sum_{K\in\mathcal{K}}m_K^*\,q(K),
$$

where $q(K)\in[0,1]$ is the measured fidelity of the aggregate. Unlike GRC,
this penalizes coarse or misleading coverage.

### 10.4 Attention Approximation Regret

Compare the loss of the chosen packet or action with the oracle under identical
budgets. Report median, mean, and worst-decile regret. Catastrophic misses are
more important than small average gains.

### 10.5 Receipt calibration

Bucket predictions by claimed sufficiency, omitted mass, or distortion. Measure
expected calibration error and Brier score against actual evidence or answer
failure. A receipt that cannot predict failure is decorative.

### 10.6 Dynamic work factor

$$
\operatorname{DWF}(\Delta) =
\frac{\text{nodes and cells touched incrementally}}
{\text{nodes and cells touched by full rebuild}}.
$$

Report DWF together with field error; a tiny update that returns a stale field
is not a success.

### 10.7 Project-size elasticity

For fixed model and budget, fit the slope of quality against $\log |V|$ and
identify breakpoints. This directly tests whether the system adapts to project
size rather than merely performing well at one scale.

## 11. Ablations

Remove one component at a time:

- hierarchy;
- structural diffusion;
- semantic kernel;
- temporal/change field;
- uncertainty and exploration;
- bridge/exception reserve;
- diversity penalty;
- relation quotas;
- exact-near/far-field split;
- iterative refinement;
- learned versus analytic stopping;
- stable global packet prefix;
- provenance and confidence weighting; and
- incremental cache reuse.

Also compare alternative diffusion kernels, hierarchy constructions, landmark
selection methods, and summary representations. An ablation is meaningful only
if the same task set, extraction graph, model, and budget are held fixed.

## 12. Statistical and reproducibility protocol

- Predeclare primary metrics and the smallest practically meaningful effect.
- Split by repository, not randomly by nearly duplicate snippets.
- Report per-repository and per-query-class results plus macro averages.
- Use paired bootstrap confidence intervals for retrieval/answer differences.
- For binary patch success, use paired tests and a mixed-effects logistic model
  with repository and task as random effects where sample size permits.
- Run multiple seeds for stochastic model evaluations and publish all failures.
- Correct for multiple comparisons in large ablation families.
- Separate tuning, development, and held-out repositories.
- Record model/API versions, prices, prompts, packet hashes, graph versions,
  hardware, and wall-clock timestamps.
- Publish raw receipts and traces without private source content.
- Never count an unscored or unvalidated task as a pass.

The central result should be a Pareto frontier over answer quality, catastrophic
miss rate, tokens, latency, update cost, and project size—not a single composite
score chosen after seeing results.

## 13. Phased implementation and decision gates

### Phase 0 — formal simulator

Implement typed synthetic graphs, exact influence operators, hierarchy
construction, coverage antichains, and metric computation without an LLM.

**Gate:** invariants and metamorphic tests pass; approximation error decreases
monotonically with budget for the preregistered objective on controlled graphs.
The current Phase 0 receipt establishes this only for exhaustive L2
optimization with uniform-within-cell reconstruction. It also records that
GRC=1 does not imply utility, one-step greedy can be suboptimal, and L2
monotonicity does not imply L1 monotonicity. These are mathematical limits, not
H1 evidence.

### Phase 1 — static multiresolution prototype

Add containment/community hierarchies, aggregate sketches, bridge exceptions,
and query-time refinement on saved real graphs.

The first bounded-path variant, `C1-PATH-L2MASS-001`, is now measured and
rejected as a cross-project champion. At 64 units it beat the equal-token flat
baseline in aggregate and on GraphGraph/Requests, but failed the preregistered
Chess and Express transfer gates. This narrows the claim: total cover and an
L2-plus-mass objective do not by themselves produce project-independent useful
resolution. H1 remains pending for new formulas and newly frozen holdouts.

**Gate:** lower oracle regret or better evidence Pareto frontier than flat PPR,
BFS, and current planning on held-out tasks.

### Phase 2 — dynamic field maintenance

Add residual queues, versioned aggregate invalidation, rebuild debt, and commit
replay benchmarks.

**Gate:** declared error bounds remain calibrated and ordinary small edits are
materially cheaper than rebuilds without stale-evidence regressions.

### Phase 3 — resource-rational control loop

Add uncertainty estimates, value-of-refinement, stopping, and iterative model
requests.

**Gate:** the controller Pareto-dominates fixed budgets on held-out query-class
and repository splits.

### Phase 4 — downstream agent study

Run frozen-model repository tasks and issue repair with complete cost and trace
capture.

**Gate:** evidence improvements translate into statistically credible task
gains within models, survive the cross-model transfer matrix, or the failure
analysis identifies and scopes packet-interpretation limits. A provider-only
gain cannot establish a model-agnostic default.

### Phase 5 — native model research

Only after the external compiler is understood, test graph-routed memory or
attention biases in an open model.

**Gate:** compare against prompt-compiled AFC at equal total compute, not only
against vanilla full attention.

## 14. What would falsify or substantially weaken the idea?

The proposal should be rejected or narrowed if any of these persist after fair
tuning:

- full-project influence is not localizable or compressible on software graphs;
- hierarchy summaries systematically erase rare decisive evidence and the
  exception channel cannot recover it economically;
- receipt uncertainty does not predict failures;
- dynamic maintenance approaches rebuild cost for common edits;
- better oracle-field approximation does not improve evidence containment;
- better evidence containment does not improve downstream answers at controlled
  cost;
- a simpler vector or fixed-radius baseline matches the Pareto frontier;
- performance gains disappear on repository-held-out or fresh tasks; or
- model positional/interpretation failures dominate retrieval quality so
  strongly that the additional graph machinery has negligible value.

Negative results would still be useful. They would locate the actual boundary
between graph quality, prompt representation, and model capability.

## 15. Relationship to existing GraphGraph work

This proposal unifies but does not supersede several current documents:

- [Dynamic Surface Math](dynamic_surface_math.md) supplies spreading activation,
  density throttling, and conversational decay.
- [Mathematical Formulations](mathematical_formulations.md) supplies the current
  PPR, budget allocation, relation quotas, and hub decay formulations.
- [LLM-Native Context Graph](llm-native-context-graph.md) supplies typed,
  temporal, hierarchical, provenance-aware graph semantics and the packet
  ladder.
- [Runtime Context Graph](runtime-context-graph.md) supplies typed mutations,
  temporal views, policy nodes, and decision traces.
- [Tensor Context Architecture](tensor_context_architecture.md) supplies the
  longer-term native attention-bias direction.
- [Rigorous Framing](rigorous-framing.md) supplies the rule that exploratory
  architecture remains a hypothesis until benchmarks support it.

The new contribution is the **coverage-and-resolution invariant**: context is
not merely a selected subgraph. It is a complete project cover in which exact
and compressed representations coexist, refine dynamically, and expose their
error.

## 16. Related-work map and precise lessons

| Research line | What it contributes | What it does not establish for GraphGraph |
| --- | --- | --- |
| Transformer full attention ([Vaswani et al., 2017](https://arxiv.org/abs/1706.03762)) | all-pairs learned token interaction | scalable, persistent project memory |
| Longformer / BigBird | local + global + exploration-style sparse patterns | which code graph edges or global nodes are correct |
| Performer / Nyströmformer | low-cost kernel/landmark approximations | that project relevance is well approximated by the same kernels |
| H-Transformer / Fast Multipole Attention | exact-near and compressed-far hierarchy | a hierarchy and error criterion for typed evolving software graphs |
| Compressive Transformer / Infini-attention | fine recent memory plus bounded compressed history | source-grounded reversible project summaries |
| PPRGo / local diffusion solvers | sparse approximations to global graph diffusion | universal localization on directed heterogeneous code graphs |
| Dynamic PageRank theory | algorithms and hard limits for evolving fields | a free constant-time exact update mechanism |
| GraphRAG | community summaries for global corpus questions | query-adaptive exact/aggregate coverage with dynamic receipts |
| [HippoRAG](https://arxiv.org/abs/2405.14831) | PPR-based associative graph memory | code-specific provenance, compilation, tests, and edit dynamics |
| [LightRAG](https://arxiv.org/abs/2410.05779) | dual-level graph retrieval and incremental indexing | full-project influence accounting |
| GraphReader / RepoCoder | iterative coarse-to-fine graph or repository exploration | error-bounded coverage and resource-rational halting |
| Repoformer | learning when retrieval is useful | what multiresolution evidence should be represented |
| Lost in the Middle / RULER | nominal context length is not effective attention | a solution to project-scale context by itself |

## 17. The compact research claim

The strongest defensible version of the original intuition is:

> A finite context system cannot literally attend to every raw project detail.
> It can maintain a complete, source-addressable, multiresolution cover of the
> project; approximate a query-conditioned global influence field; materialize
> exact detail where value and uncertainty justify it; and report the residual
> influence and error that remain compressed.

That changes the engineering objective from **retrieve a relevant subset** to
**allocate resolution over a globally represented project**.

If the experiments succeed, GraphGraph becomes less like a search engine and
more like a virtual-memory system for attention: the full project has an
address and an influence path, the working set is exact, the far field is
compressed, edits generate local invalidations, and page-in decisions are made
by expected reasoning value under a measurable budget.
