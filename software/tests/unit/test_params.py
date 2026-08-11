"""The parameter document.

The point of these tests is the line between "absent" and "unspecified". A null `readFloor`
and a null `sortFractionColumn` are answers `input-defaults` states, not gaps — so they
parse cleanly and mean something definite. A malformed document is a caller bug and raises,
because the workflow writes this file itself: a bad shape means the two sides disagree about
their own interface.
"""

from __future__ import annotations

import json

import pytest
from conftest import GATE_RANKS, write_params

from params import load_params


def test_defaults_are_answers_not_gaps(tmp_path):
    params = load_params(write_params(tmp_path / "params.json"))

    assert params.gate_ranks == GATE_RANKS
    assert params.excluded_conditions == frozenset()
    # No floor: score every variant holding reads in at least one collected gate.
    assert params.read_floor is None
    # No column: the run is uncorrected and says so on every value it emits.
    assert params.sort_fraction_column is None
    assert params.sort_yield_corrected is False


def test_absent_optional_keys_mean_the_same_as_explicit_nulls(tmp_path):
    """The document the workflow actually writes for a default run.

    Tengo has no JSON null literal, so the template omits `readFloor` and
    `sortFractionColumn` rather than nulling them. A reader that demanded all four keys
    rejected every uncorrected, unfloored run — which is the normal first run — and the block
    died inside the entrypoint with "missing required field(s)".
    """
    path = tmp_path / "params.json"
    path.write_text(json.dumps({"gateRanks": GATE_RANKS}), encoding="utf-8")

    params = load_params(path)

    assert params.gate_ranks == GATE_RANKS
    assert params.excluded_conditions == frozenset()
    assert params.read_floor is None
    assert params.sort_fraction_column is None
    assert params.sort_yield_corrected is False


def test_sort_fraction_column_sets_the_corrected_mode(tmp_path):
    params = load_params(write_params(tmp_path / "params.json", sort_fraction_column="sortFraction"))
    assert params.sort_fraction_column == "sortFraction"
    assert params.sort_yield_corrected is True


def test_read_floor_of_zero_is_distinct_from_no_floor(tmp_path):
    assert load_params(write_params(tmp_path / "a.json", read_floor=0)).read_floor == 0
    assert load_params(write_params(tmp_path / "b.json", read_floor=None)).read_floor is None


@pytest.mark.parametrize(
    ("document", "fragment"),
    [
        # Only gateRanks is required; the other three default to their stated absence.
        ({"excludedConditions": [], "readFloor": None, "sortFractionColumn": None}, "missing required field"),
        (
            {
                "gateRanks": GATE_RANKS,
                "excludedConditions": [],
                "readFloor": None,
                "sortFractionColumn": None,
                "extra": 1,
            },
            "unknown field",
        ),
        (
            {"gateRanks": {}, "excludedConditions": [], "readFloor": None, "sortFractionColumn": None},
            "non-empty object",
        ),
        (
            {"gateRanks": {"g1": "1"}, "excludedConditions": [], "readFloor": None, "sortFractionColumn": None},
            "must be an integer",
        ),
        (
            {"gateRanks": GATE_RANKS, "excludedConditions": [], "readFloor": -1, "sortFractionColumn": None},
            "non-negative",
        ),
        (
            {"gateRanks": GATE_RANKS, "excludedConditions": "pH7", "readFloor": None, "sortFractionColumn": None},
            "list of strings",
        ),
        (
            {"gateRanks": GATE_RANKS, "excludedConditions": [], "readFloor": None, "sortFractionColumn": ""},
            "non-empty string",
        ),
    ],
)
def test_malformed_document_raises(tmp_path, document, fragment):
    path = tmp_path / "params.json"
    path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(ValueError, match=fragment):
        load_params(path)


def test_boolean_is_not_accepted_as_a_rank_or_a_floor(tmp_path):
    """bool subclasses int in Python, so an unguarded isinstance check would rank a gate
    True and read it as 1."""
    path = tmp_path / "params.json"
    document = {
        "gateRanks": {"g1": True},
        "excludedConditions": [],
        "readFloor": None,
        "sortFractionColumn": None,
    }
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ValueError, match="must be an integer"):
        load_params(path)
