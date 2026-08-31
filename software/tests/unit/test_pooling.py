"""Pooling replicate samples that share a condition-and-gate group.

Every case asserts a hand-computed number or an expected absence, per
`computation-test-suite`.
"""

from __future__ import annotations

import polars as pl
import pytest
from conftest import BASE_MEANS, BASE_ROWS, GATE_RANKS, means_as_dict, reads_frame, replicate_frame

import scoring
import validate
from pooling import pool_replicates

FRACTIONS = {"g1": 0.5, "g2": 0.3, "g3": 0.2}
RETAINED = ["pH7"]


# ---------------------------------------------------------------------------
# The no-replicate case: pooling must not move anything.
# ---------------------------------------------------------------------------


def test_a_run_with_no_replicates_is_unchanged():
    """Only the row order differs, which nothing reads — every emitted file sorts by its own
    keys."""
    frame = reads_frame(BASE_ROWS, fractions=FRACTIONS)
    pooled, report = pool_replicates(frame, "sortFraction", RETAINED)

    assert report == []
    key = ["condition", "gate", "variantKey"]
    assert pooled.sort(key).equals(frame.select(pooled.columns).sort(key))


# ---------------------------------------------------------------------------
# Pooling the reads.
# ---------------------------------------------------------------------------


def test_pooling_an_exact_duplicate_of_a_gate_leaves_every_score_unchanged():
    """Replicating g1 with its own read counts doubles its depth (100 -> 200) and every
    variant's reads in it, so every frequency in g1 — and every weighted mean — is unchanged.
    Pooling merges depth without tilting the profile.
    """
    g1_rows = [row for row in BASE_ROWS if row[0] == "g1"]
    frame = pl.concat([reads_frame(BASE_ROWS), replicate_frame(g1_rows, "rep_g1")])

    pooled, _ = pool_replicates(frame, None, RETAINED)
    means = scoring.gate_rank_means(scoring.per_gate_frequencies(pooled, None), GATE_RANKS)

    assert means_as_dict(means) == pytest.approx(BASE_MEANS, rel=1e-12)


def test_pooled_reads_are_summed_and_the_weighted_mean_follows():
    """Two gates, two samples in g1, hand-computed end to end.

        g1  base P 20 A 30   replicate P 30 A 20   pooled P 50 A 50   depth 100
        g2       P 80 A 20                                            depth 100

        freq   P: g1 .5  g2 .8      A: g1 .5  g2 .2
        P: den .5 + .8 = 1.3   num 1(.5) + 2(.8) = 2.1   mean 21/13
        A: den .5 + .2 =  .7   num 1(.5) + 2(.2) =  .9   mean  9/7
    """
    ranks = {"g1": 1, "g2": 2}
    base = reads_frame([("g1", "P", 20), ("g1", "A", 30), ("g2", "P", 80), ("g2", "A", 20)])
    replicate = replicate_frame([("g1", "P", 30), ("g1", "A", 20)], "rep_g1")

    pooled, report = pool_replicates(pl.concat([base, replicate]), None, RETAINED)

    assert pooled.filter((pl.col("gate") == "g1") & (pl.col("variantKey") == "P")).item(0, "reads") == 50
    assert pooled.filter((pl.col("gate") == "g1") & (pl.col("variantKey") == "A")).item(0, "reads") == 50
    assert [entry["gate"] for entry in report] == ["g1"]

    means = means_as_dict(scoring.gate_rank_means(scoring.per_gate_frequencies(pooled, None), ranks))
    assert means["P"] == 21 / 13
    assert means["A"] == 9 / 7


def test_a_gate_collected_once_keeps_one_row_per_variant():
    """One row per (condition, gate, variant), replicated gate or not — the grain
    `read_distribution` and `check_sort_fractions` rely on."""
    g1_rows = [row for row in BASE_ROWS if row[0] == "g1"]
    frame = pl.concat([reads_frame(BASE_ROWS), replicate_frame(g1_rows, "rep_g1")])

    pooled, _ = pool_replicates(frame, None, RETAINED)

    duplicates = pooled.group_by("condition", "gate", "variantKey").len().filter(pl.col("len") > 1)
    assert duplicates.height == 0


def test_conditions_are_pooled_independently():
    """A sample id repeated across conditions is two groups, not one."""
    frame = pl.concat(
        [
            reads_frame([("g1", "P", 10)], condition="pH7"),
            reads_frame([("g1", "P", 40)], condition="pH5"),
        ]
    )
    pooled, report = pool_replicates(frame, None, ["pH5", "pH7"])

    assert report == []
    reads = dict(zip(pooled["condition"].to_list(), pooled["reads"].to_list(), strict=True))
    assert reads == {"pH7": 10, "pH5": 40}


# ---------------------------------------------------------------------------
# The pooled label.
# ---------------------------------------------------------------------------


def test_the_pooled_label_joins_the_sample_ids_and_is_the_same_on_every_variant():
    """One label per (condition, gate), not per variant: a variant missing from one replicate
    would otherwise give its gate a shorter label, and `check_sort_fractions` groups by
    sample."""
    base = reads_frame([("g1", "P", 10), ("g1", "A", 20)])
    # The replicate detected P and not A, which is the case that splits the label.
    replicate = replicate_frame([("g1", "P", 5)], "rep_g1")

    pooled, _ = pool_replicates(pl.concat([base, replicate]), None, RETAINED)

    labels = set(pooled["sampleId"].to_list())
    assert labels == {"rep_g1+s_pH7_g1"}


# ---------------------------------------------------------------------------
# The sort fraction. This is where dropping the refusal alone goes wrong.
# ---------------------------------------------------------------------------


def test_a_valid_two_replicate_run_is_no_longer_refused_for_over_summing():
    """`check_sort_fractions` sums one value per sample, so g1 collected twice would contribute
    0.5 twice and over-sum to 1.5. Pooled, g1 supplies one value and the sum is 1.0."""
    g1_rows = [row for row in BASE_ROWS if row[0] == "g1"]
    frame = pl.concat(
        [
            reads_frame(BASE_ROWS, fractions=FRACTIONS),
            replicate_frame(g1_rows, "rep_g1", fractions=FRACTIONS),
        ]
    )

    pooled, report = pool_replicates(frame, "sortFraction", RETAINED)

    assert report[0]["sortFractionsDiffer"] is False
    fractions = pooled.group_by("gate").agg(pl.col("sortFraction").first())
    assert fractions["sortFraction"].sum() == 1.0
    # No refusal.
    validate.check_sort_fractions(pooled, "sortFraction", ["pH7"])


def test_replicates_disagreeing_on_the_fraction_are_averaged_and_flagged():
    """0.5 and 0.3 average to 0.4, and the disagreement is reported rather than resolved."""
    g1_rows = [row for row in BASE_ROWS if row[0] == "g1"]
    frame = pl.concat(
        [
            reads_frame(BASE_ROWS, fractions=FRACTIONS),
            replicate_frame(g1_rows, "rep_g1", fractions={**FRACTIONS, "g1": 0.3}),
        ]
    )

    pooled, report = pool_replicates(frame, "sortFraction", RETAINED)

    assert report[0]["gate"] == "g1"
    assert report[0]["sortFractionsDiffer"] is True
    g1 = pooled.filter(pl.col("gate") == "g1")
    assert g1["sortFraction"].unique().to_list() == [0.4]


def test_a_null_fraction_on_one_replicate_does_not_hide_a_value_on_the_other():
    """The mean is over the non-null values, so a group that supplied a fraction keeps it.
    All-null still averages to null, so the presence refusal can still fire."""
    g1_rows = [row for row in BASE_ROWS if row[0] == "g1"]
    replicate = replicate_frame(g1_rows, "rep_g1", fractions=FRACTIONS).with_columns(
        pl.lit(None, dtype=pl.Float64).alias("sortFraction")
    )
    frame = pl.concat([reads_frame(BASE_ROWS, fractions=FRACTIONS), replicate])

    pooled, _ = pool_replicates(frame, "sortFraction", RETAINED)

    assert pooled.filter(pl.col("gate") == "g1")["sortFraction"].unique().to_list() == [0.5]


def test_a_group_null_on_every_replicate_stays_null():
    frame = pl.concat(
        [
            reads_frame([("g1", "P", 10)], fractions=FRACTIONS),
            replicate_frame([("g1", "P", 10)], "rep_g1", fractions=FRACTIONS),
        ]
    ).with_columns(pl.lit(None, dtype=pl.Float64).alias("sortFraction"))

    pooled, _ = pool_replicates(frame, "sortFraction", RETAINED)

    assert pooled["sortFraction"].to_list() == [None]


# ---------------------------------------------------------------------------
# The distribution file. The second thing dropping the refusal alone breaks.
# ---------------------------------------------------------------------------


def test_the_distribution_carries_one_row_per_variant_and_gate():
    """`read_distribution` joins `per_gate` onto a variant x gate grid, so unpooled a
    replicated gate matches twice. The workflow imports this file as a p-column keyed on
    exactly those two axes."""
    g1_rows = [row for row in BASE_ROWS if row[0] == "g1"]
    frame = pl.concat([reads_frame(BASE_ROWS), replicate_frame(g1_rows, "rep_g1")])

    pooled, _ = pool_replicates(frame, None, RETAINED)
    per_gate = scoring.per_gate_frequencies(pooled, None)
    scored = scoring.gate_rank_means(per_gate, GATE_RANKS)
    distribution = scoring.read_distribution(per_gate, scored, GATE_RANKS, 20)

    duplicates = distribution.group_by("variantKey", "gate").len().filter(pl.col("len") > 1)
    assert duplicates.height == 0
    # g1's pooled reads for P: 10 + 10.
    p_g1 = distribution.filter((pl.col("variantKey") == "P") & (pl.col("gate") == "g1"))
    assert p_g1.item(0, "gateReads") == 20


# ---------------------------------------------------------------------------
# The report is confined to the run.
# ---------------------------------------------------------------------------


def test_a_replicated_group_in_an_excluded_condition_is_not_reported():
    """An excluded condition is not part of the run. Its rows are still pooled; nothing reads
    them."""
    g1_rows = [row for row in BASE_ROWS if row[0] == "g1"]
    frame = pl.concat(
        [
            reads_frame(BASE_ROWS, condition="specificity"),
            replicate_frame(g1_rows, "rep_specificity", condition="specificity"),
            reads_frame(BASE_ROWS, condition="affinity"),
            replicate_frame(g1_rows, "rep_affinity", condition="affinity"),
        ]
    )

    _, report = pool_replicates(frame, None, ["specificity"])

    assert [(entry["condition"], entry["gate"]) for entry in report] == [("specificity", "g1")]


def test_every_retained_condition_is_reported():
    """The filter is the exclusion list, not "one condition"."""
    g1_rows = [row for row in BASE_ROWS if row[0] == "g1"]
    frame = pl.concat(
        [
            reads_frame(BASE_ROWS, condition="specificity"),
            replicate_frame(g1_rows, "rep_specificity", condition="specificity"),
            reads_frame(BASE_ROWS, condition="affinity"),
            replicate_frame(g1_rows, "rep_affinity", condition="affinity"),
        ]
    )

    _, report = pool_replicates(frame, None, ["affinity", "specificity"])

    assert [entry["condition"] for entry in report] == ["affinity", "specificity"]
