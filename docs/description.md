## Overview

A sort-seq experiment hands you a library of protein variants and, for each gate the sorter collected, a
count of how many reads of each variant landed in it. Nothing in that table is a binding measurement: it is
a spread of reads across gates, and the gates' order along the binding axis is the only thing that makes one
variant's spread better than another's.

This block turns that spread into a score, one per condition. For every variant it emits:

- **Gate rank mean** — the read-weighted mean of the gate ranks the variant's reads fell in, in gate-rank
  units. Higher means the variant sorted into higher gates. Not an affinity and not calibrated.
- **Bin score** — the gate rank mean minus the parent's. Zero means the variant behaves like the parent at
  that condition.

A run over N conditions emits both quantities N times, once per condition. A one-condition run is an
ordinary run: it gets both quantities, with the run's single condition on each column exactly as a
two-condition run would carry two.

## Downstream

Everything downstream of this block is a comparison of these scores — a pH switch is the difference between
a variant's bin score at two pH arms, the on-state is its raw score at the arm the campaign treats as *on*,
and a shortlist is a ranking over one of them.

## Status

Under development. The specification lives in `docs/text/work/projects/sequence-repertoires/facs-bin-analysis/`.
