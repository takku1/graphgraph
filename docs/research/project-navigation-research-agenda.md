# Project Navigation Research Agenda

Status: research proposal, not implemented behavior.  This document turns the
question "how quickly can an agent figure out what is what in a project?" into
a measurable research program.  It complements the active execution plan; it
does not supersede it.

## Thesis

GraphGraph should optimize the complete project-orientation loop, not graph
retrieval in isolation:

```text
search -> identify -> relate -> collect -> test understanding -> stop safely
```

The winning system is the one that lets an agent form a correct, task-specific
mental model with the least elapsed time, source exposure, context, and tool
work.  Exact string lookup remains a job for `rg`; known-file reading remains a
job for `Get-Content`.  GraphGraph wins only when it makes the multi-step loop
cheaper and more reliable than composing those primitives manually.

This framing follows the empirical "search, relate, collect" model of program
understanding.  Ko et al. observed that navigation, returning from navigation,
iterating search results, and recovering task context consumed substantial
developer time.  Robillard et al. found that successful investigations were
more methodical and structurally guided.  More recent agent work reaches a
compatible conclusion: repository exploration should be measured as ranked
code-region coverage under a fixed evidence budget, not just eventual patch
success.

## Current local baseline

The active plan records the following useful starting measurements:

- exact-symbol retrieval is strong, while lexical-disjoint retrieval recall is
  `0.152778`;
- a broad improvement query routed with confidence `0.147` and abstained after
  emphasizing the wrong subsystem;
- the independent gray-box baseline reported mean positive-task recall `0.779`,
  false incompleteness on `6/10` complete-recall tasks, and no-op incremental
  equivalence `0/3`;
- cold-process exact relations are roughly `470 ms` median in the recorded
  environment;
- the current full materialization path makes loading inherently proportional
  to total graph size, even when the requested relation is one hop.

These numbers are diagnostic rather than a universal product score.  They do,
however, identify the main research gap: exact structural lookup is already a
strength; cold orientation, conceptual anchoring, compound coverage, and safe
stopping are not.

## Research object

For repository \(R\), task \(q\), and unknown task-relevant evidence
\(E^*(q,R)\), an explorer chooses actions \(a_1,\ldots,a_T\).  An action may be
lexical search, symbol resolution, relationship expansion, source reading,
history lookup, test execution, or abstention.  Each action returns an
observation and has a cost.

The research objective is not maximum raw recall.  It is minimum expected
navigation loss:

\[
\begin{aligned}
L ={}& \lambda_t t
 + \lambda_s \operatorname{source\_lines}
 + \lambda_k \operatorname{tokens}
 + \lambda_a T \\
 &+ \lambda_m \operatorname{missed\_evidence}(E^*, S_T)
 + \lambda_n \operatorname{noise}(S_T)
 + \lambda_u \operatorname{unsupported\_claims}
 + \lambda_f \operatorname{freshness\_risk}.
\end{aligned}
\]

The coefficients must be reported as an evaluation profile, not hidden in the
retriever.  At least three profiles are needed: interactive orientation,
high-recall change impact, and low-token agent context.

## Research questions

### RQ1: What constitutes successful orientation?

Evaluate a compact, task-independent project atlas containing:

- languages, build systems, runnable targets, and test commands;
- top-level subsystems and their responsibilities;
- entry points, public surfaces, state/data stores, and external boundaries;
- the dominant control/data paths through each subsystem;
- recent high-churn regions and ownership or provenance when available.

The atlas is a hypothesis about project structure.  It must link every label
back to code, configuration, documentation, or measured history and expose
conflicts between declared and inferred architecture.

### RQ2: Which evidence channels are complementary?

Run ablations over exact lexical, learned sparse or dense semantic, declared
hierarchy, call/import/type relations, control/data dependence, tests, change
history, and optional runtime traces.  Measure marginal gain at equal line and
token budgets.  Do not infer value from the mere existence of a new edge type.

The expected result is a staged ensemble:

1. cheap lexical and exact-symbol candidates;
2. optional semantic candidates for vocabulary mismatch;
3. graph expansion for relationships and intermediate paths;
4. an expensive reranker only over the bounded union.

GraphCoder's coarse-to-fine result and RepoGraph's early-session navigation
gains make this a stronger hypothesis than a single global scoring pass, but it
still requires GraphGraph-specific ablation.

### RQ3: Can project structure be inferred without inventing architecture?

Compare three maps:

1. declared hierarchy from packages, manifests, build targets, and docs;
2. dependency communities from a typed, weighted graph;
3. task-conditioned regions learned from successful exploration traces.

For inferred communities, compare Leiden/CPM with architecture-recovery
baselines and a directory-only control.  Stability under small code changes is
as important as modularity.  A community is promotable only when it is
connected, stable, grounded, and useful on held-out orientation tasks.

Software reflexion models suggest a better contract than automatic clustering
alone: present agreements and disagreements between a declared project model
and the source-derived model.  A surprising mismatch is often more useful than
another unlabeled cluster.

### RQ4: Which next navigation action is worth its cost?

Treat navigation as a partially observed decision process.  At step \(t\), the
system holds a belief \(b_t\) over missing evidence and available actions
\(\mathcal A_t\).  A practical one-step controller is:

\[
a_t^* = \arg\max_{a\in\mathcal A_t}
\frac{H(b_t)-\mathbb E[H(b_{t+1})\mid a]}
     {c_{latency}(a)+\eta c_{tokens}(a)+\rho c_{risk}(a)}.
\]

The implementation need not begin with reinforcement learning.  A fitted
cost-sensitive decision table is a valid first model.  The important change is
that `retry narrower` becomes an explicit choice among actions with estimated
information value: disambiguate a symbol, inspect a manifest, expand callers,
read source, warm semantic search, run a focused test, or stop.

### RQ5: How should a bounded evidence packet be selected?

Let each candidate region or graph node have relevance, provenance,
facet-coverage, novelty, and cost.  Select a connected packet:

\[
\max_{S\subseteq V,\;S\text{ connected}}
\left[
\sum_f w_f\min\left(1,\sum_{v\in S}p(v,f)\right)
+\alpha\sum_{v\in S}r(v)
-\beta\sum_{u,v\in S}\operatorname{redundancy}(u,v)
-\gamma\sum_{e\in E(S)}c(e)
\right]
\]

subject to line, token, latency, and hard path constraints.  Compare:

- current connected/tree-knapsack selection;
- budgeted submodular greedy;
- maximum-weight connected subgraph or prize-collecting Steiner approximations;
- a simple MMR control.

Submodularity supplies useful diminishing-return behavior and approximation
results; connected-subgraph methods preserve explanatory paths.  Neither
should be promoted without an equal-budget answerability win.

### RQ6: When is the system allowed to stop?

Separate four events:

- identity is correct;
- retrieved evidence is relevant;
- required facets are covered;
- topology and source are complete enough for the requested claim.

Fit selective prediction by query class and language stratum.  Report the
risk-coverage curve and false-complete/false-incomplete rates.  Conformal risk
control is a candidate wrapper for monotone losses such as missed-evidence
rate, but only when the calibration/test exchangeability assumptions are
defensible.  It is not a magic certificate under repository or language shift.

### RQ7: Can updates scale with changed evidence rather than repository size?

The scanner should emit a typed delta directly.  Persistent indices and derived
facts should be maintained from affected keys, with full-rebuild equivalence as
an invariant.  Compare self-adjusting/differential maintenance, semi-naive rule
evaluation, and purpose-built invalidation before replacing the current simple
path.  The companion storage proposal defines the experiments.

## Benchmark design

### Task strata

1. **Cold orientation:** identify languages, entry points, build/test workflow,
   major subsystems, and a grounded one-paragraph architecture.
2. **Concept location:** natural-language queries with no identifier overlap.
3. **Relationship:** callers, implementations, data/control predecessors, and
   cross-file paths.
4. **Compound investigation:** implementation location, constraints, affected
   tests, and supporting docs in one task.
5. **Change impact:** rank regions actually consulted or modified by successful
   fixes.
6. **Negative/completeness:** establish absence or explicitly refuse it.
7. **Edit-loop:** repeat queries after one-file edits, renames, and deletions.

Use frozen held-out repositories and the SWE-Explore formulation: return ranked
code regions under fixed line budgets.  Add GraphGraph-specific relationship
and completeness labels derived independently from the tested system.

### Baselines

- `rg` plus bounded source reads with the same agent and prompt;
- language-server definition/reference navigation where available;
- lexical BM25;
- optional semantic retrieval;
- flat long-context source, where it fits;
- GraphGraph with each evidence channel ablated;
- an agent allowed to adaptively combine the primitives.

The primary product comparison is GraphGraph-assisted agent versus the adaptive
primitive agent, not GraphGraph versus one `rg` invocation.

### Metrics

- line coverage at budget \(B\), nDCG, MRR, and facet completeness;
- area under the evidence-coverage/budget curve;
- time to first relevant region and time to sufficient evidence;
- source lines, tokens, tool calls, and wall-clock latency;
- repeated navigations and avoidable source rereads;
- final answer/patch success and unsupported-claim rate;
- risk-coverage, Brier score, ECE, false-complete, and false-incomplete rates;
- incremental/full logical equivalence and crash recovery.

Use Kaplan-Meier or another censored time-to-event analysis for timeouts,
paired bootstrap confidence intervals for retrieval deltas, and a mixed-effects
model with repository and task as random effects.  Report per-language and
per-query-class strata; one aggregate can hide exactly the failures that matter.

## Falsifiable hypotheses

| ID | Hypothesis | Promotion gate |
| --- | --- | --- |
| H1 | A grounded project atlas reduces cold-orientation actions | At least 20% lower median actions and lines, no answer regression on held-out repos |
| H2 | Hybrid candidate union fixes vocabulary mismatch | Lexical-disjoint recall +0.15 absolute at equal token budget, paired CI excludes zero |
| H3 | Typed dependence slices beat uniform hop expansion | Higher compound facet completeness with no path-recall loss |
| H4 | Connected submodular/PCST selection reduces noise | At least 15% fewer lines at equal required-evidence recall |
| H5 | Value-of-information routing reduces wasted calls | At least 15% lower navigation cost with unchanged false-complete rate |
| H6 | Calibrated stopping reduces false incompleteness | `6/10` baseline falls below 10% on a materially larger held-out set, with zero unsafe complete claims |
| H7 | Direct deltas make update cost local | One-file update growth tracks affected facts, and full/incremental outputs are identical |
| H8 | Storage specialization beats a generic DB for hot relations | Candidate wins cold/warm latency and footprint while matching durability and query coverage |

Failed hypotheses should remain recorded as `no change`; the held-out set must
not become a tuning set.

## Recommended research order

1. Import or reproduce a SWE-Explore-style line-budget benchmark locally.
2. Add cold-orientation and negative/completeness tasks with independent qrels.
3. Establish the `rg + source reads` adaptive-agent baseline.
4. Build the grounded project atlas as a derived view, not a new truth store.
5. Evaluate hybrid candidate generation and typed dependence slicing.
6. Compare packet selectors at equal budgets.
7. Fit next-action and stopping policies only after the action/evidence logs are
   large enough to support calibration.
8. Change `.gg` storage only when the workload benchmark attributes a material
   share of navigation cost to persistence or index access.

## Primary research basis

- Ko et al., [An Exploratory Study of How Developers Seek, Relate, and Collect
  Relevant Information during Software Maintenance Tasks](https://www.cs.cmu.edu/~NatProg/papers/Ko2006SeekRelateCollect.pdf),
  IEEE TSE 2006.
- Robillard, Coelho, and Murphy, [How Effective Developers Investigate Source
  Code](https://www.cs.ubc.ca/~murphy/papers/cg/effective-investigation-tse.pdf),
  IEEE TSE 2004.
- LaToza, Venolia, and DeLine, [Maintaining Mental Models: A Study of Developer
  Work Habits](https://www.microsoft.com/en-us/research/publication/maintaining-mental-models-a-study-of-developer-work-habits/),
  ICSE 2006.
- Zhang et al., [SWE-Explore: Benchmarking How Coding Agents Explore
  Repositories](https://arxiv.org/abs/2606.07297), 2026 preprint.
- Ouyang et al., [RepoGraph: Enhancing AI Software Engineering with
  Repository-level Code Graph](https://arxiv.org/abs/2410.14684), 2024.
- Liu et al., [GraphCoder: Enhancing Repository-Level Code Completion via Code
  Context Graph-based Retrieval](https://arxiv.org/abs/2406.07003), 2024.
- Yamaguchi et al., [Modeling and Discovering Vulnerabilities with Code Property
  Graphs](https://mlsec.org/docs/2014-ieeesp.pdf), IEEE S&P 2014.
- Horwitz, Reps, and Binkley, [Interprocedural Slicing Using Dependence
  Graphs](https://www.cs.odu.edu/~cmo/classes/old/cs791sp05/readings/HorwitzRepsBinkley90.pdf),
  TOPLAS 1990.
- Reps, Horwitz, and Sagiv, [Precise Interprocedural Dataflow Analysis via Graph
  Reachability](https://doi.org/10.1145/199448.199462), POPL 1995.
- Murphy, Notkin, and Sullivan, [Software Reflexion Models](https://homes.cs.washington.edu/~notkin/NotkinLibrary.html),
  FSE 1995 / IEEE TSE 2001.
- Traag, Waltman, and van Eck, [From Louvain to Leiden: Guaranteeing
  Well-connected Communities](https://www.nature.com/articles/s41598-019-41695-z),
  Scientific Reports 2019.
- Lin and Bilmes, [Multi-document Summarization via Budgeted Maximization of
  Submodular Functions](https://aclanthology.org/N10-1134/), NAACL 2010.
- Angelopoulos et al., [Conformal Risk Control](https://arxiv.org/abs/2208.02814),
  ICLR 2024.

