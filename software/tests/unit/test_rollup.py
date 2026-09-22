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
    OUT_UNCERTAINTY,
    OUT_NT_VARIANTS,
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

    assert pooled.columns == ["sampleId", "variantKey", "reads", "condition", "gate"]


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
    """SD / √n, hand-computed. Nucleotide variants at 1.0 and 3.0 have SD √2 over two of them."""
    values = pl.DataFrame(
        {COL_PROTEIN: ["P", "P"], OUT_GATE_RANK_MEAN: [1.0, 3.0]},
    )
    result = rollup.replicate_error(values, OUT_GATE_RANK_MEAN)

    assert result[OUT_NT_VARIANTS].to_list() == [2]
    assert result[OUT_UNCERTAINTY].to_list()[0] == pytest.approx(math.sqrt(2) / math.sqrt(2))


def test_one_nt_variant_has_no_replicate_estimate_and_is_null_not_zero():
    """Zero would claim the nucleotide variants agree perfectly when there is nothing to compare — and
    since the caller takes the larger of two errors, a zero would be silently discarded and the
    false claim would never surface."""
    values = pl.DataFrame({COL_PROTEIN: ["P"], OUT_GATE_RANK_MEAN: [2.0]})
    result = rollup.replicate_error(values, OUT_GATE_RANK_MEAN)

    assert result[OUT_NT_VARIANTS].to_list() == [1]
    assert result[OUT_UNCERTAINTY].to_list() == [None]


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
# Enrichment, which rolls up differently.
# ---------------------------------------------------------------------------


def enrichment_frame(rows):
    """(variant, gate, enrichment, gateReads, inputReads)."""
    return pl.DataFrame(
        {
            COL_VARIANT: [r[0] for r in rows],
            COL_GATE: [r[1] for r in rows],
            OUT_GATE_ENRICHMENT: [r[2] for r in rows],
            "gateReads": [r[3] for r in rows],
            "inputReads": [r[4] for r in rows],
        },
        schema_overrides={"gateReads": pl.Int64, "inputReads": pl.Int64},
    )


def test_enrichment_averages_in_log_space_not_linear():
    """Two variants at 1/4 and 4, equally weighted: the log mean is 1, so they cancel. A linear
    mean reports 2.125 and calls the protein enriched while its twin says the opposite."""
    rows = [("a", "g1", 0.25, 100, 100), ("b", "g1", 4.0, 100, 100)]
    result = rollup.rollup_enrichment(
        enrichment_frame(rows), proteins_frame({"a": "P", "b": "P"})
    )

    assert result[OUT_GATE_ENRICHMENT].to_list()[0] == pytest.approx(1.0, rel=1e-12)
    assert result[OUT_NT_VARIANTS].to_list() == [2]


def test_a_deeply_read_nt_variant_outweighs_a_thin_one():
    """Inverse-variance weighting with var = 1/k_gate + 1/k_input. Four reads and four thousand
    are not equal evidence, and the result must sit nearer the deep one."""
    rows = [("thin", "g1", 4.0, 4, 4), ("deep", "g1", 1.0, 4000, 4000)]
    result = rollup.rollup_enrichment(
        enrichment_frame(rows), proteins_frame({"thin": "P", "deep": "P"})
    )
    value = result[OUT_GATE_ENRICHMENT].to_list()[0]

    # The unweighted log mean would be exp((ln4 + ln1)/2) = 2.0.
    assert value < 1.1
    assert value > 1.0


def test_a_depleted_nt_variant_cannot_enter_a_log_average():
    """An enrichment of 0 is log −∞ with no finite variance. It is dropped from the average and
    its absence is visible in the nucleotide-variant count, which is what says the average rests on less
    than the protein's read total suggests."""
    rows = [("a", "g1", 0.0, 0, 100), ("b", "g1", 2.0, 200, 100)]
    result = rollup.rollup_enrichment(
        enrichment_frame(rows), proteins_frame({"a": "P", "b": "P"})
    )

    assert result[OUT_NT_VARIANTS].to_list() == [1]
    assert result[OUT_GATE_ENRICHMENT].to_list()[0] == pytest.approx(2.0, rel=1e-12)


def test_enrichment_uncertainty_takes_the_larger_of_the_two():
    """Nucleotide variants that disagree widely must not report the tight counting error their depth alone
    would give."""
    agree = [("a", "g1", 2.0, 500, 500), ("b", "g1", 2.0, 500, 500)]
    disagree = [("a", "g1", 0.5, 500, 500), ("b", "g1", 8.0, 500, 500)]

    mapping = proteins_frame({"a": "P", "b": "P"})
    tight = rollup.rollup_enrichment(enrichment_frame(agree), mapping)
    loose = rollup.rollup_enrichment(enrichment_frame(disagree), mapping)

    assert loose[OUT_UNCERTAINTY].to_list()[0] > tight[OUT_UNCERTAINTY].to_list()[0]


def test_enrichment_rolls_up_per_gate_independently():
    rows = [
        ("a", "g1", 2.0, 100, 100), ("b", "g1", 2.0, 100, 100),
        ("a", "g2", 0.5, 100, 100), ("b", "g2", 0.5, 100, 100),
    ]
    result = rollup.rollup_enrichment(
        enrichment_frame(rows), proteins_frame({"a": "P", "b": "P"})
    )

    by_gate = dict(zip(result[COL_GATE].to_list(), result[OUT_GATE_ENRICHMENT].to_list()))
    assert by_gate["g1"] == pytest.approx(2.0, rel=1e-9)
    assert by_gate["g2"] == pytest.approx(0.5, rel=1e-9)
