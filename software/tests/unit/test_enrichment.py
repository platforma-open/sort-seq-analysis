"""The per-gate enrichment, case by case. Expected numbers are hand-computed from `conftest`.

Three cases carry the weight, because each fails with output of plausible shape:

* zero numerator — a measured 0, not a missing row, or depletion looks like absence;
* zero denominator — a missing row, not an infinity or a 0;
* the input must not be a rung, or every gate-rank mean shifts toward it silently.
"""

from __future__ import annotations

import polars as pl
import pytest
from conftest import (
    BASE_ENRICHMENTS,
    BASE_MEANS,
    BASE_ROWS,
    GATE_RANKS,
    INPUT_GATE,
    INPUT_ROWS,
    means_as_dict,
    reads_frame,
)

import scoring
from constants import (
    COL_GATE,
    COL_VARIANT,
    OUT_GATE_ENRICHMENT,
    OUT_GATE_FREQUENCY,
    OUT_GATE_READS,
    OUT_INPUT_READS,
)

REL = 1e-12

RANKED_ONLY = pl.col(COL_GATE) != INPUT_GATE


def enrichments_for(rows, gate_ranks=None, input_gate=INPUT_GATE, read_floor=None):
    """Run the whole per-condition path a caller would, and hand back the long frame."""
    ranks = gate_ranks or GATE_RANKS
    per_gate = scoring.per_gate_frequencies(reads_frame(rows), None)
    members = scoring.enrichment_members(per_gate, input_gate, read_floor)
    return scoring.gate_enrichments(per_gate, members, ranks, input_gate)


def cell(frame, variant: str, gate: str) -> list[dict]:
    """The rows for one (variant, gate) pair — a list, so a test can assert it is empty."""
    return frame.filter((pl.col(COL_VARIANT) == variant) & (pl.col(COL_GATE) == gate)).to_dicts()


def as_cells(frame) -> dict[tuple[str, str], float]:
    """{(gate, variant): enrichment}. Flat because `pytest.approx` refuses a nested mapping."""
    return {
        (row[COL_GATE], row[COL_VARIANT]): row[OUT_GATE_ENRICHMENT]
        for row in frame.iter_rows(named=True)
    }


def expected_cells(gates=("g1", "g2", "g3"), variants=("P", "A", "B", "C")):
    """The hand-computed table, flattened and optionally narrowed to some gates/variants."""
    return {
        (gate, variant): BASE_ENRICHMENTS[gate][variant]
        for gate in gates
        for variant in variants
    }


# ---------------------------------------------------------------------------
# The ratio itself.
# ---------------------------------------------------------------------------


def test_enrichment_is_gate_frequency_over_input_frequency():
    """gateEnrichment = freq_vcb / freq_vc,input, over every scored variant and every
    collected gate."""
    enrichments = enrichments_for(BASE_ROWS + INPUT_ROWS)

    assert as_cells(enrichments) == pytest.approx(expected_cells(), rel=REL)


def test_every_scored_variant_and_gate_gets_a_row():
    """The grid is complete: four variants across three ranked gates, and the input gate is
    not one of them."""
    enrichments = enrichments_for(BASE_ROWS + INPUT_ROWS)

    assert enrichments.height == 12
    assert set(enrichments[COL_GATE].to_list()) == {"g1", "g2", "g3"}
    assert INPUT_GATE not in enrichments[COL_GATE].to_list()


def test_both_read_counts_travel_with_the_ratio():
    """The ratio alone cannot be weighted or thresholded; the depths behind it say whether
    to trust it, and are what a log-space roll-up needs to choose a pseudo-count."""
    row = cell(enrichments_for(BASE_ROWS + INPUT_ROWS), "B", "g1")[0]

    assert row[OUT_GATE_READS] == 59
    assert row[OUT_INPUT_READS] == 40


# ---------------------------------------------------------------------------
# The two zero cases, which are deliberately asymmetric.
# ---------------------------------------------------------------------------


def test_absent_from_the_gate_is_a_measured_zero():
    """C has reads in the input and none in g3: the row is present, the ratio is 0, and the
    read count says how. Omitting it would make depletion look like absence."""
    rows = cell(enrichments_for(BASE_ROWS + INPUT_ROWS), "C", "g3")

    assert len(rows) == 1
    assert rows[0][OUT_GATE_ENRICHMENT] == 0.0
    assert rows[0][OUT_GATE_READS] == 0
    assert rows[0][OUT_INPUT_READS] == 10


def test_absent_from_the_input_gets_no_row_at_any_gate():
    """D is in every ranked gate and not in the input, so there is no reference to enrich
    against: no key, no NA row, no sentinel, and in particular no infinity."""
    rows = BASE_ROWS + INPUT_ROWS + [("g1", "D", 5), ("g2", "D", 5), ("g3", "D", 5)]
    enrichments = enrichments_for(rows)

    assert "D" not in enrichments[COL_VARIANT].to_list()
    # And it is still a scored variant — it has a gate-rank mean. Only the enrichment is
    # unavailable, which is a fact about the reference and not about the variant.
    ranked = scoring.per_gate_frequencies(reads_frame(rows), None).filter(RANKED_ONLY)
    assert "D" in scoring.gate_rank_means(ranked, GATE_RANKS)[COL_VARIANT].to_list()


def test_zero_reads_in_the_input_is_the_same_as_absent():
    """A variant the input lists with zero reads has a zero frequency, which is the same
    missing reference as no row at all. One case, not two."""
    rows = BASE_ROWS + INPUT_ROWS + [
        ("g1", "D", 5),
        ("g2", "D", 5),
        ("g3", "D", 5),
        (INPUT_GATE, "D", 0),
    ]
    enrichments = enrichments_for(rows)

    assert "D" not in enrichments[COL_VARIANT].to_list()


# ---------------------------------------------------------------------------
# Gates and inputs that collected nothing.
# ---------------------------------------------------------------------------


def test_a_gate_that_collected_nothing_is_dropped_whole():
    """g3 has a sample and no reads. Its depth is 0, so nothing was measured there — and a
    column of zeros would say instead that every variant was depleted, which is a different
    and false statement."""
    rows = [row for row in BASE_ROWS if row[0] != "g3"]
    rows += [("g3", "P", 0), ("g3", "A", 0), ("g3", "B", 0), ("g3", "C", 0)]
    enrichments = enrichments_for(rows + INPUT_ROWS)

    assert set(enrichments[COL_GATE].to_list()) == {"g1", "g2"}
    assert as_cells(enrichments) == pytest.approx(expected_cells(gates=("g1", "g2")), rel=REL)


def test_no_input_rows_produces_no_enrichment_at_all():
    """The column is absent at this condition, not present-and-empty — the same distinction
    `bin_scores` draws when the parent goes unscored."""
    assert enrichments_for(BASE_ROWS) is None


def test_an_input_that_collected_nothing_produces_no_enrichment():
    """Every denominator would be zero, so there is no reference for any variant."""
    empty_input = [(INPUT_GATE, variant, 0) for _, variant, _ in INPUT_ROWS]

    assert enrichments_for(BASE_ROWS + empty_input) is None


def test_every_ranked_gate_empty_produces_no_enrichment():
    """A reference exists and there is nothing to compare against it."""
    rows = [(gate, variant, 0) for gate, variant, _ in BASE_ROWS]

    assert enrichments_for(rows + INPUT_ROWS) is None


# The input is a reference, never a rung. Wrong here, every number stays plausible.


def test_the_input_does_not_enter_the_gate_rank_mean():
    """Scoring the same rows with and without the input present must give the identical
    weighted mean. The input is in scope only so its frequencies can be computed."""
    ranked = scoring.per_gate_frequencies(reads_frame(BASE_ROWS + INPUT_ROWS), None).filter(
        RANKED_ONLY
    )
    alone = scoring.per_gate_frequencies(reads_frame(BASE_ROWS), None)

    assert means_as_dict(scoring.gate_rank_means(ranked, GATE_RANKS)) == pytest.approx(
        means_as_dict(scoring.gate_rank_means(alone, GATE_RANKS)), rel=REL
    )
    # And that is the number the gate-ranking mode already produced, unchanged.
    assert means_as_dict(scoring.gate_rank_means(ranked, GATE_RANKS)) == pytest.approx(
        BASE_MEANS, rel=REL
    )


def test_the_input_does_not_change_any_gates_depth():
    """A depth is summed over one gate's own rows, which is what makes admitting the input
    to the frequency table free. If it were not, every frequency would move."""
    with_input = scoring.per_gate_frequencies(reads_frame(BASE_ROWS + INPUT_ROWS), None)
    alone = scoring.per_gate_frequencies(reads_frame(BASE_ROWS), None)

    ranked = with_input.filter(RANKED_ONLY).sort(COL_VARIANT, COL_GATE)
    expected = alone.sort(COL_VARIANT, COL_GATE)

    assert ranked[OUT_GATE_FREQUENCY].to_list() == pytest.approx(
        expected[OUT_GATE_FREQUENCY].to_list(), rel=REL
    )


# ---------------------------------------------------------------------------
# The floor reaches the enrichment by membership, as it reaches everything else.
# ---------------------------------------------------------------------------


def test_the_floor_removes_variants_and_moves_no_enrichment():
    """C holds 10 input reads and falls below a floor of 11. Every surviving enrichment is the
    number the unfloored run produced: the floor is a membership decision and the depths stay
    pre-floor."""
    cells = as_cells(enrichments_for(BASE_ROWS + INPUT_ROWS, read_floor=11))

    assert "C" not in {variant for _, variant in cells}
    assert cells == pytest.approx(expected_cells(variants=("P", "A", "B")), rel=REL)


def test_the_floor_reads_the_input_not_the_sorted_gates():
    """C has 2 sorted reads but 10 in the input, so a floor of 10 keeps it. The input count is
    the denominator every ratio of C rests on, and so the evidence the floor weighs."""
    cells = as_cells(enrichments_for(BASE_ROWS + INPUT_ROWS, read_floor=10))

    assert cells == pytest.approx(expected_cells(), rel=REL)


def test_a_variant_depleted_from_every_gate_is_a_measured_zero_at_each():
    """D is in the input and in no sorted gate — what a stop codon looks like. It has no rank
    mean, but its enrichment is 0 at every gate, not a missing row."""
    rows = BASE_ROWS + INPUT_ROWS + [(INPUT_GATE, "D", 50)]
    frame = enrichments_for(rows)

    for gate in ("g1", "g2", "g3"):
        (row,) = cell(frame, "D", gate)
        assert row[OUT_GATE_ENRICHMENT] == 0.0
        assert row[OUT_GATE_READS] == 0
        assert row[OUT_INPUT_READS] == 50
