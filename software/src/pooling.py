"""Pool replicate samples that share a condition-and-gate group.

Pooling here, once, before anything else reads the table keeps the rest of the package on its
one-row-per-(gate, variant) grain. Two places break silently otherwise:
`scoring.read_distribution` emits duplicate (variantKey, gate) keys, and
`check_sort_fractions` counts a twice-collected gate's fraction twice and over-sums.

Temporary. Whether replicates should be pooled at all rather than scored separately is open,
as is what to do when they disagree on the sort fraction (here: averaged and flagged).
"""

from __future__ import annotations

import polars as pl
from constants import (
    COL_CONDITION,
    COL_GATE,
    COL_READS,
    COL_SAMPLE,
    COL_VARIANT,
)

# A single-sample group keeps its bare sample id, so pooling is a no-op there.
_LABEL_SEPARATOR = "+"

_SAMPLES = "_samples"
_FRACTION_VALUES = "_fractionValues"


def pool_replicates(
    reads: pl.DataFrame, sort_fraction_column: str | None, retained_conditions: list[str]
) -> tuple[pl.DataFrame, list[dict]]:
    """Collapse to one row per (condition, gate, variant): reads summed, sort fraction the mean
    of the group's non-null values, other metadata the first in sample-id order, sample ids
    joined. Returns the pooled table and the groups that held more than one sample.

    Metadata resolves per (condition, gate), not per variant: a variant missing from one
    replicate would give its gate a shorter label, and `check_sort_fractions` groups by sample
    and would then see that gate twice.

    A `sort_fraction_column` the table does not carry is left for `check_sort_fractions` to
    refuse, rather than pre-empted here with a polars traceback.

    Only retained conditions are reported. Excluded rows are still pooled; nothing reads them.
    """
    fraction = sort_fraction_column if sort_fraction_column in reads.columns else None

    # Read off the frame rather than listed: the workflow decides which metadata columns the
    # reads table carries, and one named here but not there would vanish from the run.
    fixed = {COL_CONDITION, COL_GATE, COL_VARIANT, COL_SAMPLE, COL_READS}
    passthrough = [name for name in reads.columns if name not in fixed and name != fraction]

    # Deduplicated to one row per sample first: metadata repeats across the sample's variant
    # rows, so aggregating the raw rows would weight a sample by how many variants it detected.
    metadata_columns = [COL_CONDITION, COL_GATE, COL_SAMPLE, *passthrough]
    if fraction is not None:
        metadata_columns.append(fraction)

    by_sample = pl.col(COL_SAMPLE).sort()
    meta_aggs = [pl.col(COL_SAMPLE).unique().sort().alias(_SAMPLES)]
    if fraction is not None:
        meta_aggs.append(pl.col(fraction).alias(_FRACTION_VALUES))
    # Sample-id order, so the pick is deterministic rather than row-order dependent.
    meta_aggs += [pl.col(name).sort_by(by_sample).first().alias(name) for name in passthrough]

    group_meta = (
        reads.select(metadata_columns)
        .unique()
        .group_by(COL_CONDITION, COL_GATE)
        .agg(*meta_aggs)
        .sort(COL_CONDITION, COL_GATE)
    )

    report = _report(group_meta, fraction, retained_conditions)

    resolved = [pl.col(_SAMPLES).list.join(_LABEL_SEPARATOR).alias(COL_SAMPLE), *passthrough]
    if fraction is not None:
        resolved.append(pl.col(_FRACTION_VALUES).list.drop_nulls().list.mean().alias(fraction))
    resolved_meta = group_meta.select(COL_CONDITION, COL_GATE, *resolved)

    pooled = (
        reads.group_by(COL_CONDITION, COL_GATE, COL_VARIANT)
        .agg(pl.col(COL_READS).sum().alias(COL_READS))
        .join(resolved_meta, on=[COL_CONDITION, COL_GATE], how="left")
        .select(reads.columns)
        .sort(COL_CONDITION, COL_GATE, COL_VARIANT)
    )
    return pooled, report


def _report(
    group_meta: pl.DataFrame, sort_fraction_column: str | None, retained_conditions: list[str]
) -> list[dict]:
    """The replicated groups of retained conditions, in condition-and-gate order.

    `sortFractionsDiffer` means the group's replicates supplied different fractions, which is
    either two separate sorts or wrong metadata — the fraction is a property of the gate.
    """
    replicated = group_meta.filter(
        (pl.col(_SAMPLES).list.len() > 1)
        & pl.col(COL_CONDITION).is_in(retained_conditions)
    )
    if replicated.height == 0:
        return []

    entries = []
    for row in replicated.iter_rows(named=True):
        entry = {
            "condition": row[COL_CONDITION],
            "gate": row[COL_GATE],
            "samples": list(row[_SAMPLES]),
        }
        if sort_fraction_column is not None:
            supplied = [value for value in row[_FRACTION_VALUES] if value is not None]
            entry["sortFractionsDiffer"] = len(set(supplied)) > 1
        entries.append(entry)
    return entries
