# @platforma-open/milaboratories.sort-seq-analysis.ui

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
