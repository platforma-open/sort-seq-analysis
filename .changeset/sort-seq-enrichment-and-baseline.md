---
'@platforma-open/milaboratories.sort-seq-analysis.software': minor
'@platforma-open/milaboratories.sort-seq-analysis.workflow': minor
'@platforma-open/milaboratories.sort-seq-analysis.model': minor
'@platforma-open/milaboratories.sort-seq-analysis.ui': minor
'@platforma-open/milaboratories.sort-seq-analysis.block': minor
---

Optional per-gate enrichment, nucleotide-level scores, renamed score columns

- **Per-gate enrichment*. Name the gate value holding your unsorted library and
  the run emits one enrichment per condition and gate. Ordering the gates and naming an input are
  independent, so a run can produce either set of scores or both.
- **Nucleotide datasets** are scored per nucleotide variant and rolled up per protein. The
  synonymous variants of one protein disagree, and that disagreement is reported as a **noise
  estimate** beside each protein score, with the variant count it was measured on.
- The two score columns are renamed to the words the field uses: **Mean bin** and **Mean bin vs
  parent**. Column names, domains and values are unchanged.
