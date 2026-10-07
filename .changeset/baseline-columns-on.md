---
'@platforma-open/milaboratories.sort-seq-analysis.workflow': minor
'@platforma-open/milaboratories.sort-seq-analysis.software': minor
'@platforma-open/milaboratories.sort-seq-analysis.model': minor
'@platforma-open/milaboratories.sort-seq-analysis.ui': minor
'@platforma-open/milaboratories.sort-seq-analysis.block': minor
---

Per-position baseline: a reference value for the parent residue

A **Per-position baseline** checkbox in the settings drawer, and the columns it produces. The
baseline is measured from the parent's synonymous variants — same protein, different DNA — so each
position gets its own value, and the Mutation Explorer draws it in the parent row of the mutation
map as the reference every other cell is read against.

The checkbox appears on a nucleotide-level dataset when the run names an unsorted input.

What a run with it on produces:

- **Baseline** per gate per position on `[parentId, position]`, keyed on the profiler's own
  position labels, so the Mutation Explorer draws it directly.
- **Baseline** per gate on `[parentId]` — the same measurement pooled over the whole sequence.
- The per-gate level also rides as an annotation on each enrichment column, so a consumer reads it
  without a second query.

Each baseline is a level — the median of the set — and the count of variants behind it.
