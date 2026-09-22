---
'@platforma-open/milaboratories.sort-seq-analysis.software': minor
'@platforma-open/milaboratories.sort-seq-analysis.workflow': minor
'@platforma-open/milaboratories.sort-seq-analysis.model': minor
'@platforma-open/milaboratories.sort-seq-analysis.ui': minor
'@platforma-open/milaboratories.sort-seq-analysis.block': minor
---

Score per-gate enrichment against an unsorted input, with a per-gate baseline

- New **Per-gate enrichment** mode: name the gate value holding your unsorted library and the run
  emits one score per (condition, gate), so each gate draws its own map.
- **Baseline** sets where "no change" sits — the wild type, the variants synonymous with it, or a
  nucleotide sequence you name. Each gate's level and spread ride as annotations on its score
  column, and the synonymous baseline is also split by codon position.
- The library's degenerate codon (NNK, NNS, NNN) is inferred from the run's own reads, so no codon
  setting is needed. Positions that cannot carry a synonymous change are reported.
- Nucleotide datasets now work. Scores are emitted per nucleotide variant and rolled up per
  protein with an uncertainty and a variant count, shown as two tables.
- The two score columns are renamed to the words the field uses: **Mean bin** and
  **Mean bin vs parent**. Column names, domains and values are unchanged.

An existing gate-ranking block projects none of the new arguments, so it does not go stale.
