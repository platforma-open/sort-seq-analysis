## Overview

A sort-seq experiment hands you a library of protein variants. For each gate the sorter collected, you get a
count of how many reads of each variant landed in it. Nothing in that table is a binding measurement. It is a
spread of reads across gates, and the block turns that spread into a score.

Two things decide what a run produces, and they are independent:

- **Are the gates ordered?** An order along the binding axis is what makes one variant's spread better than
  another's.
- **Is one gate an unsorted input?** An unsorted sample is a reference each gate can be compared against.

A run may have either, or both. With both, the block emits both sets of scores.

## Ordered Gates: Mean Bin

When the gates are ordered, every variant gets two values per condition:

- **Mean Bin** — the read-weighted mean of the gate ranks the variant's reads fell in, in gate-rank units.
  Higher means the variant sorted into higher gates. Not an affinity and not calibrated.
- **Mean Bin vs Parent** — the mean bin minus the parent's. Zero means the variant behaves like the parent at
  that condition.

## An Unsorted Input: Per-Gate Enrichment

Name the gate value holding your unsorted library, and every variant gets an **enrichment** for each gate:
its share of reads in that gate divided by its share in the input. A variant the gate did not collect
gets 0, and for the enrichment the read-count floor counts the variant's reads in the input.

The enrichment is computed for every gate the run covers, ordered or not. So it works both on gates that
only differ in what they select, and on gates that sit along a binding axis. An ordered run with an input
gets an enrichment per gate on top of its mean-bin scores.

## Nucleotide-Level Data

When the dataset carries nucleotide variants, the block scores each one and then rolls them up per protein.
A protein's score pools the reads of all its nucleotide variants. Beside each protein enrichment sits an
**error** in the same units: the larger of the read-count error and the disagreement between the
protein's nucleotide variants, together with how many variants it was measured on.

The two levels are shown as two tables, because they sit on different axes and have different row counts.

## Conditions

A run over N conditions emits every quantity N times, once per condition. A one-condition run is an ordinary
run. It gets the same columns, with the run's single condition on each, exactly as a two-condition run would
carry two.
