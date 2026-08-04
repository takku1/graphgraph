> **Academic title:** Terminology

# Terminology

Living docs use the academic term. The informal alias is what the codebase, CLI
output, and older write-ups often say — both name the same thing, so this table
is the translation layer when reading source or pre-2026-08 documents.

| Academic term | Informal alias (legacy) |
|---------------|-------------------------|
| **Context packet** | packet, `#gg` blob |
| **Corpus extraction** | scan |
| **Intermediate representation (IR)** | graph model / shared IR |
| **Language frontend** | scanner frontend |
| **Name resolution / receiver-type inference** | receiver resolution |
| **Call graph / dependence graph** | call edges |
| **Change-impact neighborhood** | blast radius |
| **Retrieval anchors** | anchors / seeds |
| **Query class** | query class (unchanged) |
| **Information-retrieval ranking** | search scoring |
| **Abstention / selective prediction** | refuse / low confidence |
| **Gray-box evaluation** | graybox |
| **Mechanical validation** | packet validation |
| **Native graph store** | `.gg` / GGB4 |
| **Epistemic stage / evidence stage** | evidence stage |
| **Held-out evaluation** | frozen eval split |
| **Resident process transport** | MCP long-lived server |
| **Cold-start process latency** | CLI spawn cost |

## Documentation conventions

1. **One incomplete-work registry.** Incomplete product and research work is
   tracked only in [../open-work.md](../open-work.md). Do not reintroduce
   parallel checklists in research essays or evidence records.
2. **Evidence records are not task lists.** Dated records under
   [../evaluation/graybox-cycles/](../evaluation/graybox-cycles/README.md) state
   what was measured on a date. Work arising from them becomes an open-work row.
3. **Every living document is reachable from [../README.md](../README.md).**
   This is enforced by `tests/test_docs_contract.py`.
4. **Promote, don't accumulate.** When a concept becomes a stable subsystem,
   expand the relevant `architecture/**/SYSTEM.md` rather than adding a
   free-floating page.

## Document renames (2026-08-02 redesign)

The flat `docs/` tree was reorganized into `guides/`, `architecture/`,
`evaluation/`, and `research/`. Pre-redesign filenames are recorded in each
migrated document's `Legacy:` breadcrumb, and the full pre-redesign tree remains
in git history. Notable renames:

| Pre-redesign | Living |
|--------------|--------|
| `architecture.md` | `architecture/system-architecture.md` |
| `source-layout.md` | `architecture/package-structure.md` |
| `start-here.md` / `welcome.md` | `guides/getting-started.md` / `guides/overview.md` |
| `rigorous-framing.md` | `guides/evidence-standards.md` |
| `planned-work.md` | `open-work.md` (incomplete rows only) |
| `empirical-findings.md` | `evaluation/empirical-evaluation.md` |
| `findings/BUGS.md` | `evaluation/defect-ledger.md` |
| `findings/2026-*.md` | `evaluation/graybox-cycles/` |
| `kiminotes*.md` | `research/external-mechanism-notes*.md` |
| `notes/LOCUS-FINDINGS.md` | `research/comparisons/locus-engine-findings.md` |
