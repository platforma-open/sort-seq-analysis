"""The sort-fraction refusal — the one data-value refusal.

Each case asserts the refusal fires **and** that its message names the offending values —
the message is the whole of what the user gets, since nothing partial is produced.
"""

from __future__ import annotations

import polars as pl
import pytest
from conftest import BASE_ROWS, reads_frame

from errors import Refusal
from validate import check_sort_fractions

RETAINED = ["pH7"]


# ---------------------------------------------------------------------------
# Sort fractions.
# ---------------------------------------------------------------------------


def test_valid_fractions_pass():
    frame = reads_frame(BASE_ROWS, fractions={"g1": 0.5, "g2": 0.3, "g3": 0.2})
    check_sort_fractions(frame, "sortFraction", RETAINED)


def test_sum_short_of_one_is_legitimate():
    """It is what a condition that collected only some of the declared gates correctly looks
    like. Imputing the remainder is barred, and the manifest reports the sum so the shortfall
    is visible rather than silent."""
    frame = reads_frame(BASE_ROWS, fractions={"g1": 0.3, "g2": 0.2, "g3": 0.1})
    check_sort_fractions(frame, "sortFraction", RETAINED)


def test_over_summing_refuses_and_names_the_condition():
    """Percentages, absolute counts and duplicated values all over-sum — which is what the
    one-sided test exists to catch. Nothing is renormalized to fit."""
    frame = reads_frame(BASE_ROWS, fractions={"g1": 0.5, "g2": 0.5, "g3": 0.5})

    with pytest.raises(Refusal) as excinfo:
        check_sort_fractions(frame, "sortFraction", RETAINED)

    message = str(excinfo.value)
    assert "'pH7'" in message
    assert "1.5" in message
    assert "not renormalized" in message


def test_sum_within_tolerance_passes():
    """1e-3 is the right order for fractions rounded to three decimals on a sorter report."""
    frame = reads_frame(BASE_ROWS, fractions={"g1": 0.334, "g2": 0.333, "g3": 0.333})
    check_sort_fractions(frame, "sortFraction", RETAINED)


def test_out_of_range_refuses():
    frame = reads_frame(BASE_ROWS, fractions={"g1": 50.0, "g2": 30.0, "g3": 20.0})

    with pytest.raises(Refusal) as excinfo:
        check_sort_fractions(frame, "sortFraction", RETAINED)

    assert "outside [0.0, 1.0]" in str(excinfo.value)


def test_null_on_a_sample_carrying_reads_refuses():
    frame = reads_frame(BASE_ROWS, fractions={"g1": 0.5, "g2": 0.3, "g3": 0.2}).with_columns(
        pl.when(pl.col("gate") == "g2").then(None).otherwise(pl.col("sortFraction")).alias("sortFraction")
    )

    with pytest.raises(Refusal) as excinfo:
        check_sort_fractions(frame, "sortFraction", RETAINED)

    message = str(excinfo.value)
    assert "s_pH7_g2" in message
    assert "null" in message


def test_naming_a_column_the_table_does_not_carry_fails_the_run():
    frame = reads_frame(BASE_ROWS)

    with pytest.raises(Refusal) as excinfo:
        check_sort_fractions(frame, "notThere", RETAINED)

    assert "notThere" in str(excinfo.value)
