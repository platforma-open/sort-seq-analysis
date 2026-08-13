# @platforma-open/milaboratories.sort-seq-analysis.block

## 1.0.2

### Patch Changes

- bd2c759: Release fix

## 1.0.1

### Patch Changes

- 2efd95b: Sort-Seq Analysis — first implementation.

  Scores protein variants from a sort-seq (FACS bin) experiment. Per condition the block emits the
  read-weighted mean of the gate ranks each variant sorted into (`pl7.app/facsBin/gateRankMean`) and that
  value minus the parent's (`pl7.app/facsBin/binScore`), both keyed on the profiler's variant axis and
  carrying the condition — and, on the bin score, the reference mode — as matchable domain keys.

  - **software** — the score computation as a Python package on the scientific-slim runenv, with its own
    pytest suite pinning the arithmetic clause by clause against hand-computed numbers.
  - **workflow** — resolves the inputs against the abundance anchor, exports the reads and variants tables,
    invokes the entrypoint once, and constructs one PColumn per file the manifest names.
  - **model** — the seven-argument surface with every configuration rule validated before the run, the four
    option lists, and the outputs the three views read.
  - **ui** — one settings drawer plus Results, Read distribution and Run summary.

  Integration tests against the real upstream chain are not in this change.
