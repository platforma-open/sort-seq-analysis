"""The two data-value refusals this side owns.

`validation-boundary` assigns exactly these to the computation, because both need the
column *values* rather than a picked column reference: whether a set of fractions sums to
1, and whether two samples share a gate, are properties of the project's data.

Every configuration rule — a required argument absent, an anchor resolving to nothing or
to more than one column, the three metadata roles not distinct, an incomplete gate order,
every condition excluded, a negative floor — is refused by the block model before the run
starts and is deliberately **not** re-checked here. Two implementations of one rule, in
two languages, either changeable alone, is a rule that will disagree; the failure mode is
specific and bad, a model-side check drifting looser so the settings pass and the run
fails anyway with a different message.

Both refusals name the offending values and are raised before any file is written, so
nothing partial is produced.
"""

from __future__ import annotations

import polars as pl
from constants import (
    COL_CONDITION,
    COL_GATE,
    COL_READS,
    COL_SAMPLE,
    SORT_FRACTION_MAX,
    SORT_FRACTION_MIN,
    SORT_FRACTION_SUM_TOLERANCE,
)
from errors import Refusal


def check_one_sample_per_group(reads: pl.DataFrame, retained_conditions: list[str]) -> None:
    """v1 admits at most one sample per condition-and-gate group.

    Two samples in a group **fail the run**. Their reads are not pooled and neither sample
    is preferred: summing them would move every depth, frequency and weighted mean in the
    run, which is exactly the shape of failure `input-defaults` bars — output of ordinary
    length and plausible content, with nothing saying an aggregation was chosen.

    Replicate support is a v2 addition, and what v2 must supply is an aggregation rule for
    the reads plus an agreement rule for the per-sample values the group then has more
    than one of. Until it does, refusing is the only honest option.

    No sample for a pair is **not** an error — that gate was not collected at that
    condition, which clauses 1 and 2 already accommodate.

    Only retained conditions are checked; an excluded value is not part of the run.
    """
    offenders = (
        reads.filter(pl.col(COL_CONDITION).is_in(retained_conditions))
        .group_by(COL_CONDITION, COL_GATE)
        .agg(pl.col(COL_SAMPLE).unique().sort().alias("samples"))
        .filter(pl.col("samples").list.len() > 1)
        .sort(COL_CONDITION, COL_GATE)
    )
    if offenders.height == 0:
        return

    detail = "; ".join(
        f"condition {row[COL_CONDITION]!r} gate {row[COL_GATE]!r}: samples {', '.join(row['samples'])}"
        for row in offenders.iter_rows(named=True)
    )
    raise Refusal(
        f"more than one sample in a condition-and-gate group, which v1 does not support "
        f"(reads are not pooled): {detail}"
    )


def check_sort_fractions(reads: pl.DataFrame, column: str, retained_conditions: list[str]) -> None:
    """The three requirements of `sort-fraction-values`.

    1. **Present** — no null on any sample carrying reads.
    2. **In [0, 1].**
    3. **Not over-summing** — within each condition, the supplied fractions sum to no more
       than 1.0 + 1e-3.

    Requirement 3 is deliberately **one-sided**. A two-sided sum-to-1 test is what the
    sibling block implements, and it is only correct there because its bins are all
    collected. Here a declared gate may legitimately yield no sample, its fraction then
    reaches the block through no channel, and — with renormalization barred — a two-sided
    test would refuse a valid run and leave it no path at all. A shortfall is what a
    partially-collected condition correctly looks like; the manifest reports every
    condition's sum, so it is visible rather than silent.

    What the one-sided test still catches is what actually goes wrong: percentages,
    absolute counts, and duplicated values, all of which over-sum.

    Nothing is renormalized to fit. An over-summing set is evidence the wrong quantity was
    supplied, and scaling it would turn wrong data into a plausible number. Nor does a
    violation fall back to the uncorrected mode: that would discard an input the user
    deliberately supplied while declaring `sortYieldCorrected: "false"` — technically true,
    and read as "this run had no sort fractions" when in fact it had unusable ones.
    """
    if column not in reads.columns:
        raise Refusal(
            f"sortFractionColumn names {column!r}, which the reads table does not carry "
            f"(it has: {', '.join(reads.columns)})"
        )

    in_run = reads.filter(pl.col(COL_CONDITION).is_in(retained_conditions))

    # One supplied value per sample: the sort fraction is per-sample metadata, repeated
    # across the sample's variant rows.
    per_sample = in_run.group_by(COL_SAMPLE, COL_CONDITION, COL_GATE).agg(
        pl.col(column).first().alias("fraction"),
        pl.col(COL_READS).sum().alias("sample_reads"),
    )

    _check_present(per_sample)
    _check_range(per_sample)
    _check_sum_per_condition(per_sample)


def _check_present(per_sample: pl.DataFrame) -> None:
    missing = per_sample.filter(pl.col("fraction").is_null() & (pl.col("sample_reads") > 0)).sort(COL_SAMPLE)
    if missing.height == 0:
        return
    detail = ", ".join(
        f"{row[COL_SAMPLE]!r} (condition {row[COL_CONDITION]!r}, gate {row[COL_GATE]!r})"
        for row in missing.iter_rows(named=True)
    )
    raise Refusal(f"sort fraction is null on sample(s) carrying reads: {detail}")


def _check_range(per_sample: pl.DataFrame) -> None:
    out_of_range = per_sample.filter(
        pl.col("fraction").is_not_null()
        & ((pl.col("fraction") < SORT_FRACTION_MIN) | (pl.col("fraction") > SORT_FRACTION_MAX))
    ).sort(COL_SAMPLE)
    if out_of_range.height == 0:
        return
    detail = ", ".join(
        f"{row[COL_SAMPLE]!r}: {row['fraction']}" for row in out_of_range.iter_rows(named=True)
    )
    raise Refusal(
        f"sort fraction outside [{SORT_FRACTION_MIN}, {SORT_FRACTION_MAX}] — normalized fractions are "
        f"expected, not percentages or absolute cell counts: {detail}"
    )


def _check_sum_per_condition(per_sample: pl.DataFrame) -> None:
    limit = SORT_FRACTION_MAX + SORT_FRACTION_SUM_TOLERANCE
    sums = (
        per_sample.group_by(COL_CONDITION)
        .agg(pl.col("fraction").sum().alias("total"))
        .filter(pl.col("total") > limit)
        .sort(COL_CONDITION)
    )
    if sums.height == 0:
        return
    detail = ", ".join(f"{row[COL_CONDITION]!r}: {row['total']}" for row in sums.iter_rows(named=True))
    raise Refusal(
        f"supplied sort fractions sum to more than {limit} within a condition, and are not renormalized: {detail}"
    )
