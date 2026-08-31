# @platforma-open/milaboratories.sort-seq-analysis.ui

## 1.0.5

### Patch Changes

- 4945fef: Pool replicate samples instead of refusing the run

  A condition-and-gate group holding more than one sample used to fail the run. Its reads are
  now summed, matching what `titeseq-analysis` and `clonotype-enrichment` already do.

  The pooling is reported rather than silent, which is the objection the original refusal was
  raised against: the manifest gains a `pooledGroups` list, the run log names every merged
  group and its samples, and the Run statistics dialog shows a warning listing them. The dialog
  resolves sample ids to sample labels through the sample axis's label column, so the alert
  names samples the way the user does. Only retained conditions are reported — an excluded
  condition is not part of the run. Where replicates supplied different sort fractions, the
  non-null values are averaged and that is flagged separately.

  Two things broke quietly on replicate samples and are fixed at the source, by pooling before
  anything reads the table: the read-distribution file emitted duplicate `(variantKey, gate)`
  keys, and the sort-fraction check counted a twice-collected gate's fraction twice and refused
  runs that were entirely valid.

  This is temporary. It does not decide whether replicates should be pooled at all rather than
  scored separately, nor what to do when they disagree on the sort fraction.

- Updated dependencies [4945fef]
  - @platforma-open/milaboratories.sort-seq-analysis.model@1.0.5

## 1.0.4

### Patch Changes

- Updated dependencies [d3a1dba]
- Updated dependencies [9ca1d8a]
  - @platforma-open/milaboratories.sort-seq-analysis.model@1.0.4

## 1.0.3

### Patch Changes

- 97db2d1: Gate order is a selection, not a ranking of every value the gate column carries

  The block no longer refuses to run until every distinct value of the gate column has been
  given an order position. The gate column of a real sort-seq run routinely carries values
  that are not rungs on the binding ladder — an unsorted input, a specificity arm, a
  stability arm — and demanding a rank for each refused configurations the computation runs
  perfectly well.

  The ordered list is now the run's gate scope: the gates it holds, in the order it holds
  them, are the ladder, and removing a value takes it and its samples out of the run. Ranks
  stay contiguous from 1 over the gates that remain, so a removal leaves no gap that would
  shift every score.

  - **Model** — the coverage check is gone; what remains is that the list is non-empty and
    names nothing the column does not carry.
  - **Computation** — rows outside the declared ladder are dropped before the depths are
    taken, so an unselected gate contributes to neither sum of the weighted mean. Its
    samples are likewise outside the one-sample-per-group and sort-fraction refusals, and
    its fraction is not part of a condition's sum.
  - **A condition whose every sample sits in an unselected gate** is dropped from the run,
    exactly as an excluded condition is, rather than scored to an empty file.

- Updated dependencies [97db2d1]
  - @platforma-open/milaboratories.sort-seq-analysis.model@1.0.3

## 1.0.2

### Patch Changes

- bd2c759: Release fix
- Updated dependencies [bd2c759]
  - @platforma-open/milaboratories.sort-seq-analysis.model@1.0.2
