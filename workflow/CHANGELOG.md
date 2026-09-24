# @platforma-open/milaboratories.sort-seq-analysis.workflow

## 1.1.1

### Patch Changes

- ea684c4: Republish the software package off version 1.1.0

  The binary registry already held `software/.../main/1.1.0.tgz`, uploaded on 13 August from a much
  older source tree. The 1.1.0 release did not replace it, so the block paired its new workflow with
  that old Python and every run failed with `unrecognized arguments: --positions --parents`.

  No behaviour changes. This moves every package to 1.1.1, which is free on both registries.

  Column labels are also put in title case, so "Mean bin vs parent" now reads "Mean Bin vs Parent".
  Only the display labels change; column names, domains and values are untouched.

- Updated dependencies [ea684c4]
  - @platforma-open/milaboratories.sort-seq-analysis.software@1.1.1

## 1.1.0

### Minor Changes

- 6d40a83: Optional per-gate enrichment, nucleotide-level scores, renamed score columns

  - **Per-gate enrichment**. Name the gate value holding your unsorted library and
    the run emits one enrichment per condition and gate. Ordering the gates and naming an input are
    independent, so a run can produce either set of scores or both. A variant missing from a gate
    scores 0, and for the enrichment the read-count floor counts the variant's input reads.
  - **Nucleotide datasets** are scored per nucleotide variant and rolled up per protein by pooling
    their reads. Each protein enrichment carries an **error** in the same units: the larger of the
    read-count error and the disagreement between the protein's nucleotide variants.
  - The two score columns are renamed to the words the field uses: **Mean bin** and **Mean bin vs
    parent**. Column names and values are unchanged.
  - **Breaking for downstream picks:** both score columns now carry a `pl7.app/alphabet` domain
    (`aminoacid` or `nucleotide`), so the protein and nucleotide levels of one run can be told
    apart. A block that picked one of them before the upgrade, such as the Mutation Explorer's
    score list, must pick it again after this block re-runs.

### Patch Changes

- Updated dependencies [6d40a83]
  - @platforma-open/milaboratories.sort-seq-analysis.software@1.1.0

## 1.0.5

### Patch Changes

- Updated dependencies [4945fef]
  - @platforma-open/milaboratories.sort-seq-analysis.software@1.0.5

## 1.0.4

### Patch Changes

- Updated dependencies [3639cc1]
  - @platforma-open/milaboratories.sort-seq-analysis.software@1.0.4

## 1.0.3

### Patch Changes

- Updated dependencies [97db2d1]
  - @platforma-open/milaboratories.sort-seq-analysis.software@1.0.3

## 1.0.2

### Patch Changes

- bd2c759: Release fix
- Updated dependencies [bd2c759]
  - @platforma-open/milaboratories.sort-seq-analysis.software@1.0.2
