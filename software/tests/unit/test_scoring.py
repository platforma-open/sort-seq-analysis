"""The arithmetic, clause by clause.

Each test names the clause of `../dms-analysis#bin-score-formula` it pins. The three that
matter most are the ones whose wrong implementation produces output of ordinary shape and
plausible content: clause 1 (zero-depth gate), clause 2 (denominator over collected gates
only) and clause 3 (floor after depths).
"""

from __future__ import annotations

import pytest
from conftest import (
    BASE_MEANS,
    BASE_MUTATION_COUNTS,
    BASE_ROWS,
    BASE_TOTAL_READS,
    GATE_RANKS,
    means_as_dict,
    reads_frame,
    scores_as_dict,
    variants_frame,
)

import scoring
from constants import (
    DISTRIBUTION_TOP_N,
    MODE_CANCELLED,
    MODE_REFERENCED,
    PARENT_ABSENT_MULTIPLE_ZERO,
    PARENT_ABSENT_NO_ZERO,
)

REL = 1e-12


def means_for(rows, gate_ranks=None, sort_fraction_column=None, fractions=None):
    frame = reads_frame(rows, fractions=fractions)
    per_gate = scoring.per_gate_frequencies(frame, sort_fraction_column)
    return scoring.gate_rank_means(per_gate, gate_ranks or GATE_RANKS)


# ---------------------------------------------------------------------------
# The weighted mean itself, uncorrected.
# ---------------------------------------------------------------------------


def test_weighted_mean_uncorrected():
    """gateRankMean = Σ_b (b · freq_vcb) / Σ_b freq_vcb, in gate-rank units on [1, G]."""
    means = means_as_dict(means_for(BASE_ROWS))

    assert means == pytest.approx(BASE_MEANS, rel=REL)
    # Every value sits inside the formula's stated range for G = 3.
    assert all(1.0 <= value <= 3.0 for value in means.values())


def test_total_reads_is_summed_over_collected_gates():
    """The quantity clause 3 compares against the floor."""
    frame = means_for(BASE_ROWS)
    totals = dict(zip(frame["variantKey"].to_list(), frame[scoring.TOTAL_READS].to_list(), strict=True))
    assert totals == BASE_TOTAL_READS


# ---------------------------------------------------------------------------
# Clause 3 — the floor is a membership decision and moves no surviving score.
#
# This is the case the suite exists for. `input-defaults` makes the floor optional, and its
# whole argument rests on this property; it says outright that if it ever stopped holding,
# the floor would have to become required.
# ---------------------------------------------------------------------------


def test_floor_changes_membership_and_no_surviving_score():
    unfloored = scoring.apply_read_floor(means_for(BASE_ROWS), None)
    floored = scoring.apply_read_floor(means_for(BASE_ROWS), 10)

    unfloored_means = means_as_dict(unfloored)
    floored_means = means_as_dict(floored)

    # The variants present differ: C holds 2 reads and falls below a floor of 10.
    assert set(unfloored_means) == {"P", "A", "B", "C"}
    assert set(floored_means) == {"P", "A", "B"}

    # And every surviving variant's value is identical. A floor applied *before* the depths
    # were taken would drop C's single read from g1 and g2, making both depths 99 and moving
    # B's mean off 1.5 — so this assertion is what discriminates the two orderings.
    for variant in floored_means:
        assert floored_means[variant] == pytest.approx(unfloored_means[variant], rel=REL)
    assert floored_means["B"] == pytest.approx(1.5, rel=REL)


def test_no_floor_scores_every_variant_holding_reads():
    """`input-defaults`: unset, no floor is applied — every variant with reads in at least
    one collected gate is scored."""
    rows = BASE_ROWS + [("g1", "Z", 0), ("g2", "Z", 0), ("g3", "Z", 0)]
    means = means_as_dict(scoring.apply_read_floor(means_for(rows), None))

    assert set(means) == {"P", "A", "B", "C"}
    # Z holds no reads in any gate, so its denominator is zero and it has no key at all —
    # `unscorable-is-absent`: no NA row, no sentinel.
    assert "Z" not in means


def test_floor_of_zero_still_excludes_a_variant_with_no_reads():
    rows = BASE_ROWS + [("g1", "Z", 0), ("g2", "Z", 0), ("g3", "Z", 0)]
    means = means_as_dict(scoring.apply_read_floor(means_for(rows), 0))
    assert "Z" not in means


# ---------------------------------------------------------------------------
# Clause 1 — a gate with depth 0 contributes to neither numerator nor denominator.
# ---------------------------------------------------------------------------


def test_zero_depth_gate_contributes_to_neither_sum():
    """Adding a collected-but-empty fourth gate must not move a single score."""
    ranks = {**GATE_RANKS, "g4": 4}
    rows = BASE_ROWS + [("g4", variant, 0) for variant in ("P", "A", "B", "C")]

    with_empty_gate = means_as_dict(means_for(rows, gate_ranks=ranks))

    assert with_empty_gate == pytest.approx(BASE_MEANS, rel=REL)


# ---------------------------------------------------------------------------
# Clause 2 — the denominator runs over the collected gates only, and the uncollected
# fraction is not imputed.
# ---------------------------------------------------------------------------


def test_denominator_over_collected_gates_only():
    """A condition that collected g1 and g2 but not g3.

      gate |  P |  A | depth
      -----+----+----+------
      g1   | 10 | 90 |  100
      g2   | 40 | 60 |  100

      P: freq .10 .40  den .50  num 1(.10)+2(.40) =  .90  mean 1.8
      A: freq .90 .60  den 1.50 num 1(.90)+2(.60) = 2.10  mean 1.4

    Nothing reconstructs what g3 would have held: the waste fraction stays un-imputed, and
    g3 is simply not a gate this condition collected.
    """
    rows = [("g1", "P", 10), ("g1", "A", 90), ("g2", "P", 40), ("g2", "A", 60)]
    means = means_as_dict(means_for(rows))

    assert means == pytest.approx({"P": 1.8, "A": 1.4}, rel=REL)


def test_unranked_gate_raises_rather_than_dropping_its_reads():
    """An incomplete gate order is refused by the block model before the run, so this is an
    internal invariant guarding a direct CLI caller — not a second check of that rule."""
    rows = BASE_ROWS + [("gX", "P", 5)]
    with pytest.raises(Exception):
        means_for(rows)


# ---------------------------------------------------------------------------
# The sort-yield correction (Adams eq. A3): w = freq · frac.
# ---------------------------------------------------------------------------


def test_sort_yield_correction_reweights_by_gate_fraction():
    """Fractions g1 .5, g2 .3, g3 .2 — summing to 1.0.

      P: w = .10(.5)=.05  .20(.3)=.06  .70(.2)=.14
         num = 1(.05) + 2(.06) + 3(.14) = .59   den = .25   mean = .59/.25 = 2.36
      A: w = .30(.5)=.15  .50(.3)=.15  .20(.2)=.04
         num = 1(.15) + 2(.15) + 3(.04) = .57   den = .34   mean = .57/.34
    """
    fractions = {"g1": 0.5, "g2": 0.3, "g3": 0.2}
    means = means_as_dict(means_for(BASE_ROWS, sort_fraction_column="sortFraction", fractions=fractions))

    assert means["P"] == pytest.approx(2.36, rel=REL)
    assert means["A"] == pytest.approx(0.57 / 0.34, rel=REL)
    # And the correction genuinely changes the answer — otherwise the test proves nothing.
    assert means["P"] != pytest.approx(BASE_MEANS["P"], rel=1e-6)


# ---------------------------------------------------------------------------
# The parent subtraction, and the three states of binScore.
# ---------------------------------------------------------------------------


def test_parent_subtraction_referenced():
    """binScore = gateRankMean − gateRankMean(parent). Zero means "behaves like the parent"."""
    scored = scoring.apply_read_floor(means_for(BASE_ROWS), None)
    parent = scoring.resolve_parent(variants_frame(BASE_MUTATION_COUNTS))

    assert parent.identified
    assert parent.reference_mode == MODE_REFERENCED

    scores = scores_as_dict(scoring.bin_scores(scored, parent), "binScore")
    assert scores == pytest.approx({"P": 0.0, "A": 1.9 - 2.6, "B": 1.5 - 2.6, "C": 1.5 - 2.6}, rel=REL)


def test_cancelled_form_where_no_variant_has_zero_mutation_count():
    """binScore is numerically identical to gateRankMean, still emitted, mode "cancelled"."""
    scored = scoring.apply_read_floor(means_for(BASE_ROWS), None)
    parent = scoring.resolve_parent(variants_frame({"A": 1, "B": 2, "C": 3, "P": 4}))

    assert not parent.identified
    assert parent.absence_reason == PARENT_ABSENT_NO_ZERO
    assert parent.reference_mode == MODE_CANCELLED

    scores = scores_as_dict(scoring.bin_scores(scored, parent), "binScore")
    assert scores == pytest.approx(BASE_MEANS, rel=REL)


def test_cancelled_form_where_more_than_one_variant_has_zero_mutation_count():
    parent = scoring.resolve_parent(variants_frame({"P": 0, "A": 0, "B": 2, "C": 3}))

    assert not parent.identified
    assert parent.absence_reason == PARENT_ABSENT_MULTIPLE_ZERO
    assert parent.reference_mode == MODE_CANCELLED


def test_no_mutation_count_table_produces_bin_score_nowhere():
    """Distinct from the cancelled form: with no table there is no reference to cancel
    against, so no reference mode is claimed either."""
    scored = scoring.apply_read_floor(means_for(BASE_ROWS), None)
    parent = scoring.resolve_parent(None)

    assert not parent.produce_bin_score
    assert parent.absence_reason is None
    assert parent.reference_mode is None
    assert scoring.bin_scores(scored, parent) is None


def test_bin_score_absent_where_parent_is_identifiable_but_unscored():
    """Clause 5. The parent falling below the floor makes every variant's binScore absent at
    that condition, and it does **not** fall back to the cancelled form — the fallback is
    triggered by the parent being unidentifiable, never by its score being missing.

    gateRankMean is unaffected and is still emitted.
    """
    # P holds 2 reads; a floor of 10 excludes it while A and B survive.
    rows = [
        ("g1", "P", 1),
        ("g1", "A", 40),
        ("g1", "B", 59),
        ("g2", "P", 1),
        ("g2", "A", 60),
        ("g2", "B", 39),
    ]
    scored = scoring.apply_read_floor(means_for(rows), 10)
    parent = scoring.resolve_parent(variants_frame({"P": 0, "A": 1, "B": 2}))

    assert parent.identified
    assert "P" not in means_as_dict(scored)
    assert scoring.bin_scores(scored, parent) is None
    # gateRankMean is still there for everything that cleared the floor.
    assert set(means_as_dict(scored)) == {"A", "B"}


# ---------------------------------------------------------------------------
# The read distribution.
# ---------------------------------------------------------------------------


def test_read_distribution_covers_scored_variants_across_collected_gates():
    frame = reads_frame(BASE_ROWS)
    per_gate = scoring.per_gate_frequencies(frame, None)
    scored = scoring.apply_read_floor(scoring.gate_rank_means(per_gate, GATE_RANKS), 10)

    distribution = scoring.read_distribution(per_gate, scored, GATE_RANKS, DISTRIBUTION_TOP_N)

    # Three scored variants x three collected gates. C fell below the floor and is absent:
    # the row set is the variants actually scored, so the view's rows match the results table.
    assert distribution.height == 9
    assert set(distribution["variantKey"].to_list()) == {"P", "A", "B"}

    by_key = {
        (row["variantKey"], row["gate"]): (row["gateFrequency"], row["gateReads"])
        for row in distribution.iter_rows(named=True)
    }
    assert by_key[("P", "g1")] == pytest.approx((0.10, 10), rel=REL)
    assert by_key[("P", "g3")] == pytest.approx((0.70, 70), rel=REL)
    assert by_key[("B", "g2")] == pytest.approx((0.29, 29), rel=REL)


def test_read_distribution_draws_only_the_top_n_by_gate_rank_mean():
    """The view is one series per variant, so it is cut to the highest-scoring few.

    Cut on `gateRankMean` descending, which is the direction the score's own
    `rankingOrder` annotation declares.
    """
    frame = reads_frame(BASE_ROWS)
    per_gate = scoring.per_gate_frequencies(frame, None)
    scored = scoring.apply_read_floor(scoring.gate_rank_means(per_gate, GATE_RANKS), None)

    distribution = scoring.read_distribution(per_gate, scored, GATE_RANKS, 2)

    # P at 2.6 and A at 1.9 are the two highest of {P: 2.6, A: 1.9, B: 1.5, C: 1.5}.
    assert set(distribution["variantKey"].to_list()) == {"P", "A"}
    # Two variants x three collected gates, so the grid is still complete for those drawn.
    assert distribution.height == 6
    # The scored set itself is untouched — the cut is the view's, not the run's.
    assert scored.height == 4


def test_top_scoring_variants_breaks_ties_on_the_variant_key():
    """B and C both score 1.5, so which one is drawn must not depend on row order.

    Two runs over identical inputs emitting different variant sets would make the file
    non-deterministic, which pure-template dedup cannot tolerate.
    """
    frame = reads_frame(BASE_ROWS)
    per_gate = scoring.per_gate_frequencies(frame, None)
    scored = scoring.apply_read_floor(scoring.gate_rank_means(per_gate, GATE_RANKS), None)

    top = scoring.top_scoring_variants(scored, 3)["variantKey"].to_list()

    # B before C on the tie, by key ascending.
    assert top == ["P", "A", "B"]
    # And the same answer from a reversed input.
    reversed_scored = scored.reverse()
    assert scoring.top_scoring_variants(reversed_scored, 3)["variantKey"].to_list() == top


def test_read_distribution_keeps_every_variant_when_fewer_than_the_cut():
    """The ordinary small-library case: nothing is dropped and no padding is invented."""
    frame = reads_frame(BASE_ROWS)
    per_gate = scoring.per_gate_frequencies(frame, None)
    scored = scoring.apply_read_floor(scoring.gate_rank_means(per_gate, GATE_RANKS), None)

    distribution = scoring.read_distribution(per_gate, scored, GATE_RANKS, DISTRIBUTION_TOP_N)

    assert set(distribution["variantKey"].to_list()) == {"P", "A", "B", "C"}
    assert distribution.height == 12


def test_read_distribution_emits_a_zero_point_for_a_gate_the_variant_missed():
    """Every collected gate appears for every scored variant. A missing point would read as
    a gap in the sort rather than as a variant absent from that gate."""
    frame = reads_frame(BASE_ROWS)
    per_gate = scoring.per_gate_frequencies(frame, None)
    scored = scoring.apply_read_floor(scoring.gate_rank_means(per_gate, GATE_RANKS), None)

    distribution = scoring.read_distribution(per_gate, scored, GATE_RANKS, DISTRIBUTION_TOP_N)
    row = distribution.filter(
        (distribution["variantKey"] == "C") & (distribution["gate"] == "g3")
    ).to_dicts()[0]

    assert row["gateReads"] == 0
    assert row["gateFrequency"] == pytest.approx(0.0, rel=REL)
