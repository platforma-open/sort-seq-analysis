"""Rolling nucleotide-level scores up to the protein.

Pooling a protein's nucleotide variants and scoring once must reproduce an amino-acid-grain
run exactly — it is algebraically the same operation, so any difference is a bug.

The other silent failure is the uncertainty: the counting error alone on a protein whose
variants disagree is a tight bound the data does not support.
"""

from __future__ import annotations

import math

import polars as pl
import pytest
from conftest import BASE_MEANS, BASE_ROWS, GATE_RANKS, means_as_dict, reads_frame

import rollup
import scoring
from constants import (
    COL_GATE,
    COL_PROTEIN,
    COL_VARIANT,
    OUT_GATE_ENRICHMENT,
    OUT_GATE_RANK_MEAN,
    OUT_NT_VARIANTS,
    OUT_UNCERTAINTY,
)

REL = 1e-12


def proteins_frame(mapping: dict[str, str]):
    """variantKey -> proteinKey, as the workflow supplies it from the `aaToNt` linker."""
    keys = sorted(mapping)
    return pl.DataFrame({COL_VARIANT: keys, COL_PROTEIN: [mapping[key] for key in keys]})


# The regression test: pooling must reproduce a protein-grain run exactly.


def test_pooling_reproduces_the_protein_grain_run_exactly():
    """Split every variant in two, roll back up, and the means must be the original numbers —
    the same arithmetic, not approximately. Splitting moved no reads between gates."""
    split_rows = []
    for gate, variant, reads in BASE_ROWS:
        split_rows.append((gate, f"{variant}_a", reads - reads // 2))
        split_rows.append((gate, f"{variant}_b", reads // 2))

    mapping = {f"{variant}_{half}": variant for variant in "PABC" for half in "ab"}
    pooled = rollup.pool_reads_by_protein(reads_frame(split_rows), proteins_frame(mapping))

    per_gate = scoring.per_gate_frequencies(pooled, None)
    means = means_as_dict(scoring.gate_rank_means(per_gate, GATE_RANKS))

    assert means == pytest.approx(BASE_MEANS, rel=REL)


def test_pooling_leaves_the_table_shape_unchanged():
    """The whole point: every function downstream reads the result without knowing it was
    pooled, so the rank mean, floor, bin score and distribution all become protein-level with
    no second implementation."""
    mapping = {variant: variant for _, variant, _ in BASE_ROWS}
    pooled = rollup.pool_reads_by_protein(reads_frame(BASE_ROWS), proteins_frame(mapping))

    assert pooled.columns == ["sampleId", "variantKey", "reads", "condition", "gate", "parentId"]


def test_a_variant_the_linker_does_not_place_is_dropped():
    """Its protein is unknown. Translating it would contradict the linker, and leaving it as its
    own protein would invent a singleton that dilutes every aggregate it lands in."""
    mapping = {variant: "P" for _, variant, _ in BASE_ROWS if variant != "C"}
    pooled = rollup.pool_reads_by_protein(reads_frame(BASE_ROWS), proteins_frame(mapping))

    assert "C" not in pooled[COL_VARIANT].to_list()


# ---------------------------------------------------------------------------
# The counting error on a pooled rank mean.
# ---------------------------------------------------------------------------


def test_a_variant_confined_to_one_gate_has_no_spread():
    """All its reads in one gate, so σ_gate is 0 and the mean is pinned by depth alone."""
    rows = [("g1", "X", 100), ("g2", "Y", 50), ("g3", "Y", 50)]
    per_gate = scoring.per_gate_frequencies(reads_frame(rows), None)
    means = scoring.gate_rank_means(per_gate, GATE_RANKS)

    errors = rollup.rank_mean_counting_error(per_gate, means, GATE_RANKS)
    by_variant = dict(zip(errors[COL_VARIANT].to_list(), errors[OUT_UNCERTAINTY].to_list()))

    assert by_variant["X"] == pytest.approx(0.0, abs=1e-12)
    assert by_variant["Y"] > 0.0


def test_spread_across_gates_costs_certainty_at_equal_depth():
    """Two variants, the same total reads, one concentrated and one split across the ladder.
    The spread one is less certain — which is the property the σ term exists to express."""
    rows = [
        ("g1", "tight", 0), ("g2", "tight", 100), ("g3", "tight", 0),
        ("g1", "wide", 50), ("g2", "wide", 0), ("g3", "wide", 50),
    ]
    per_gate = scoring.per_gate_frequencies(reads_frame(rows), None)
    means = scoring.gate_rank_means(per_gate, GATE_RANKS)

    errors = rollup.rank_mean_counting_error(per_gate, means, GATE_RANKS)
    by_variant = dict(zip(errors[COL_VARIANT].to_list(), errors[OUT_UNCERTAINTY].to_list()))

    assert by_variant["wide"] > by_variant["tight"]


# ---------------------------------------------------------------------------
# The replicate error.
# ---------------------------------------------------------------------------


def test_replicate_error_is_the_scatter_of_the_nt_variants():
    """Equal weights reduce it to SD / √n. Nucleotide variants at 1.0 and 3.0 have SD √2 over
    two of them."""
    values = pl.DataFrame(
        {COL_PROTEIN: ["P", "P"], OUT_GATE_RANK_MEAN: [1.0, 3.0], "w": [1.0, 1.0]},
    )
    result = rollup.replicate_error(values, OUT_GATE_RANK_MEAN, "w")

    assert result[OUT_NT_VARIANTS].to_list() == [2]
    assert result[OUT_UNCERTAINTY].to_list()[0] == pytest.approx(math.sqrt(2) / math.sqrt(2))


def test_one_nt_variant_has_no_replicate_estimate_and_is_null_not_zero():
    """Zero would claim the nucleotide variants agree perfectly when there is nothing to compare — and
    since the caller takes the larger of two errors, a zero would be silently discarded and the
    false claim would never surface."""
    values = pl.DataFrame({COL_PROTEIN: ["P"], OUT_GATE_RANK_MEAN: [2.0], "w": [1.0]})
    result = rollup.replicate_error(values, OUT_GATE_RANK_MEAN, "w")

    assert result[OUT_NT_VARIANTS].to_list() == [1]
    assert result[OUT_UNCERTAINTY].to_list() == [None]


def test_a_thin_outlier_barely_moves_the_replicate_error():
    """Two deep variants agree at 2.0 and a one-read variant sits at 1.0 — a single read lands on
    a gate. Unweighted, it would set the error at SD/√3 ≈ 0.33. Weighted by its share of the
    pooled mean, it is hand-computed below and two orders of magnitude smaller."""
    values = pl.DataFrame(
        {COL_PROTEIN: ["P"] * 3, OUT_GATE_RANK_MEAN: [2.0, 2.0, 1.0], "w": [1000.0, 1000.0, 1.0]},
    )
    result = rollup.replicate_error(values, OUT_GATE_RANK_MEAN, "w")

    centre = (2000 * 2.0 + 1.0) / 2001
    scatter = 2 * 1000**2 * (2.0 - centre) ** 2 + (1.0 - centre) ** 2
    expected = math.sqrt(3 / 2 * scatter) / 2001
    assert result[OUT_UNCERTAINTY].to_list()[0] == pytest.approx(expected, rel=REL)
    assert expected < 0.01


def test_the_counting_error_uses_the_effective_read_count():
    """X has 100 reads in each of two gates, but g1 is ten times deeper than g2, so a g1 read
    weighs a tenth as much. The mean rests on N_eff = (Σw)² / Σ(w²/k) ≈ 120 reads, not 200."""
    rows = [("g1", "X", 100), ("g2", "X", 100), ("g1", "Y", 900)]
    per_gate = scoring.per_gate_frequencies(reads_frame(rows), None)
    means = scoring.gate_rank_means(per_gate, GATE_RANKS)

    errors = rollup.rank_mean_counting_error(per_gate, means, GATE_RANKS)
    by_variant = dict(zip(errors[COL_VARIANT].to_list(), errors[OUT_UNCERTAINTY].to_list()))

    w1, w2 = 100 / 1000, 100 / 100
    mean = (w1 * 1 + w2 * 2) / (w1 + w2)
    sigma = math.sqrt((w1 * (1 - mean) ** 2 + w2 * (2 - mean) ** 2) / (w1 + w2))
    n_eff = (w1 + w2) ** 2 / (w1**2 / 100 + w2**2 / 100)
    assert n_eff == pytest.approx(119.8, abs=0.1)
    assert by_variant["X"] == pytest.approx(sigma / math.sqrt(n_eff), rel=REL)


def test_equal_depths_make_the_effective_count_the_total():
    """Every read weighs the same, so N_eff is the plain read total and nothing changes."""
    rows = [("g1", "X", 30), ("g2", "X", 70), ("g1", "Y", 70), ("g2", "Y", 30)]
    per_gate = scoring.per_gate_frequencies(reads_frame(rows), None)
    means = scoring.gate_rank_means(per_gate, GATE_RANKS)

    errors = rollup.rank_mean_counting_error(per_gate, means, GATE_RANKS)
    by_variant = dict(zip(errors[COL_VARIANT].to_list(), errors[OUT_UNCERTAINTY].to_list()))

    mean = (0.3 * 1 + 0.7 * 2) / 1.0
    sigma = math.sqrt(0.3 * (1 - mean) ** 2 + 0.7 * (2 - mean) ** 2)
    assert by_variant["X"] == pytest.approx(sigma / math.sqrt(100), rel=REL)


# ---------------------------------------------------------------------------
# Combining the two.
# ---------------------------------------------------------------------------


def test_the_larger_error_wins():
    """Never an average, and never the counting error alone: a protein whose nucleotide variants scatter is
    not made certain by having been read deeply."""
    counting = pl.DataFrame(
        {COL_VARIANT: ["big", "small"], OUT_UNCERTAINTY: [0.5, 0.01], "totalReads": [100, 100]}
    )
    replicate = pl.DataFrame(
        {COL_VARIANT: ["big", "small"], OUT_UNCERTAINTY: [0.1, 0.4], OUT_NT_VARIANTS: [2, 2]}
    )
    combined = rollup.combine_errors(counting, replicate)
    by_variant = dict(
        zip(combined[COL_VARIANT].to_list(), combined[OUT_UNCERTAINTY].to_list())
    )

    assert by_variant["big"] == pytest.approx(0.5)
    assert by_variant["small"] == pytest.approx(0.4)


def test_a_single_nt_variant_falls_back_to_the_counting_error():
    counting = pl.DataFrame(
        {COL_VARIANT: ["P"], OUT_UNCERTAINTY: [0.25], "totalReads": [100]}
    )
    replicate = pl.DataFrame({COL_VARIANT: ["P"], OUT_UNCERTAINTY: [None], OUT_NT_VARIANTS: [1]})
    combined = rollup.combine_errors(counting, replicate)

    assert combined[OUT_UNCERTAINTY].to_list() == [pytest.approx(0.25)]
    assert combined[OUT_NT_VARIANTS].to_list() == [1]


# ---------------------------------------------------------------------------
# Enrichment: pooled like the rank mean, with an error in the ratio's own units.
# ---------------------------------------------------------------------------

INPUT = "in"
RUNG = {"g1": 1}


def rolled_enrichment(rows, mapping, read_floor=None):
    """The pipeline's protein path for one condition: pool, score, attach the error."""
    proteins = proteins_frame(mapping)
    per_variant_gate = scoring.per_gate_frequencies(reads_frame(rows), None)
    per_variant = scoring.gate_enrichments(
        per_variant_gate,
        scoring.enrichment_members(per_variant_gate, INPUT, read_floor),
        RUNG,
        INPUT,
    )
    pooled_gate = scoring.per_gate_frequencies(
        rollup.pool_reads_by_protein(reads_frame(rows), proteins), None
    )
    pooled = scoring.gate_enrichments(
        pooled_gate, scoring.enrichment_members(pooled_gate, INPUT, read_floor), RUNG, INPUT
    )
    return rollup.enrichment_uncertainty(pooled, per_variant, proteins)


def row_for(frame, protein="P") -> dict:
    (row,) = frame.filter(pl.col(COL_VARIANT) == protein).to_dicts()
    return row


def test_protein_enrichment_is_the_ratio_of_pooled_reads():
    """P holds a, b and c. a and b are depleted to zero in g1 and c is enriched. Pooled, P has
    40 of g1's 1040 reads against 300 of the input's 1300: (40/1040) / (300/1300) = 1/6.

    Averaging per-variant ratios would have to drop the two zeros and report c's 0.5 alone —
    the protein would read three times as enriched as its reads say."""
    rows = [
        ("g1", "c", 40), ("g1", "z", 1000),
        ("in", "a", 100), ("in", "b", 100), ("in", "c", 100), ("in", "z", 1000),
    ]
    result = rolled_enrichment(rows, {"a": "P", "b": "P", "c": "P", "z": "Z"})
    row = row_for(result)

    assert row[OUT_GATE_ENRICHMENT] == pytest.approx((40 / 1040) / (300 / 1300), rel=REL)
    # The depleted variants' reads count in the totals.
    assert row["gateReads"] == 40
    assert row["inputReads"] == 300
    assert row[OUT_NT_VARIANTS] == 3


def test_counting_error_is_in_the_ratio_s_own_units():
    """40 gate reads against 100 input reads: SE = E·√(1/40 + 1/100). One variant, so there is
    no replicate estimate and the counting error stands."""
    rows = [("g1", "a", 40), ("g1", "z", 60), ("in", "a", 100), ("in", "z", 100)]
    row = row_for(rolled_enrichment(rows, {"a": "P", "z": "Z"}))

    expected = row[OUT_GATE_ENRICHMENT] * math.sqrt(1 / 40 + 1 / 100)
    assert row[OUT_UNCERTAINTY] == pytest.approx(expected, rel=REL)
    assert row[OUT_NT_VARIANTS] == 1


def test_a_protein_depleted_everywhere_is_a_zero_with_an_error():
    """A measured zero, not a missing row — and not a zero error either, which would claim
    certainty from no reads. The pseudocount stands in for the zero gate count: half a read of
    g1's 100 against 10 of the input's 110."""
    rows = [("g1", "z", 100), ("in", "a", 10), ("in", "z", 100)]
    row = row_for(rolled_enrichment(rows, {"a": "P", "z": "Z"}))

    half_read = (0.5 / 100) / (10 / 110)
    assert row[OUT_GATE_ENRICHMENT] == 0.0
    assert row[OUT_UNCERTAINTY] == pytest.approx(half_read * math.sqrt(1 / 0.5 + 1 / 10), rel=REL)


def test_replicate_error_is_the_linear_scatter_of_the_nt_variants():
    """a and b disagree widely at equal, deep counts, so the replicate term wins: the SD of their
    two enrichments over √2, on the ratio scale."""
    rows = [
        ("g1", "a", 100), ("g1", "b", 1600), ("g1", "z", 8300),
        ("in", "a", 1000), ("in", "b", 1000), ("in", "z", 8000),
    ]
    row = row_for(rolled_enrichment(rows, {"a": "P", "b": "P", "z": "Z"}))

    e_a = (100 / 10000) / (1000 / 10000)
    e_b = (1600 / 10000) / (1000 / 10000)
    sd = abs(e_a - e_b) / math.sqrt(2)
    assert row[OUT_UNCERTAINTY] == pytest.approx(sd / math.sqrt(2), rel=REL)
    assert row[OUT_NT_VARIANTS] == 2


def test_agreeing_deep_variants_keep_the_counting_error():
    """Two variants at the same enrichment have no scatter. The counting error must stand, not
    fall to zero."""
    rows = [
        ("g1", "a", 500), ("g1", "b", 500), ("g1", "z", 1000),
        ("in", "a", 500), ("in", "b", 500), ("in", "z", 1000),
    ]
    row = row_for(rolled_enrichment(rows, {"a": "P", "b": "P", "z": "Z"}))

    expected = row[OUT_GATE_ENRICHMENT] * math.sqrt(1 / 1000 + 1 / 1000)
    assert row[OUT_UNCERTAINTY] == pytest.approx(expected, rel=REL)


def test_the_replicate_error_reads_only_variants_that_passed_the_floor():
    """t has 2 input reads and falls below a floor of 10. Its wild ratio must not reach the
    protein's error, though its reads still count in the pooled value."""
    rows = [
        ("g1", "a", 100), ("g1", "b", 100), ("g1", "t", 50), ("g1", "z", 750),
        ("in", "a", 100), ("in", "b", 100), ("in", "t", 2), ("in", "z", 798),
    ]
    row = row_for(rolled_enrichment(rows, {"a": "P", "b": "P", "t": "P", "z": "Z"}, read_floor=10))

    assert row[OUT_NT_VARIANTS] == 2
    assert row["gateReads"] == 250


def test_pooling_carries_the_sort_fraction():
    """It is a property of the (condition, gate), so every pooled row keeps its gate's value.
    Dropping it crashed every sort-yield-corrected run at nucleotide grain."""
    mapping = {variant: "P" for _, variant, _ in BASE_ROWS}
    fractions = {"g1": 0.2, "g2": 0.3, "g3": 0.5}
    pooled = rollup.pool_reads_by_protein(
        reads_frame(BASE_ROWS, fractions=fractions), proteins_frame(mapping), "sortFraction"
    )

    by_gate = dict(zip(pooled[COL_GATE].to_list(), pooled["sortFraction"].to_list()))
    assert by_gate == fractions


def test_the_enrichment_replicate_error_is_weighted_by_input_reads():
    """t has 5 input reads and a wild ratio; a and b are deep and agree. Weighted by input reads,
    t barely moves the error, so the tight counting error of the pooled reads is not swamped."""
    rows = [
        ("g1", "a", 1000), ("g1", "b", 1000), ("g1", "t", 100), ("g1", "z", 7900),
        ("in", "a", 1000), ("in", "b", 1000), ("in", "t", 5), ("in", "z", 7995),
    ]
    row = row_for(rolled_enrichment(rows, {"a": "P", "b": "P", "t": "P", "z": "Z"}))

    unweighted = pl.Series([1.0, 1.0, 20.0]).std() / math.sqrt(3)
    assert row[OUT_NT_VARIANTS] == 3
    assert row[OUT_UNCERTAINTY] < unweighted / 10
