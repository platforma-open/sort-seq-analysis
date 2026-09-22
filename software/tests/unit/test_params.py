"""The parameter document, and the line between "absent" and "unspecified".

A null `readFloor` or `sortFractionColumn` is an answer, not a gap. A malformed document
raises: the workflow writes this file itself.
"""

from __future__ import annotations

import json

import pytest
from conftest import GATE_RANKS, INPUT_GATE, write_params

from constants import (
    BASELINE_SEQUENCE,
    BASELINE_SYNONYMOUS,
    RUN_MODE_ENRICHMENT,
    RUN_MODE_GATE_RANKING,
)
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
    # No mode: the gate-ranking run, which is also every document written before
    # enrichment existed.
    assert params.mode == RUN_MODE_GATE_RANKING
    assert params.scores_enrichment is False
    assert params.input_gate is None
    assert params.baseline is None
    assert params.baseline_sequence is None


def test_absent_optional_keys_mean_the_same_as_explicit_nulls(tmp_path):
    """The document the workflow actually writes for a default run: Tengo has no JSON null
    literal, so it omits `readFloor` and `sortFractionColumn` rather than nulling them."""
    path = tmp_path / "params.json"
    path.write_text(json.dumps({"gateRanks": GATE_RANKS}), encoding="utf-8")

    params = load_params(path)

    assert params.gate_ranks == GATE_RANKS
    assert params.excluded_conditions == frozenset()
    assert params.read_floor is None
    assert params.sort_fraction_column is None
    assert params.sort_yield_corrected is False
    assert params.mode == RUN_MODE_GATE_RANKING
    assert params.input_gate is None
    assert params.baseline is None


# ---------------------------------------------------------------------------
# Mode, input and baseline.
# ---------------------------------------------------------------------------


def test_enrichment_mode_reads_its_input_and_baseline(tmp_path):
    params = load_params(
        write_params(
            tmp_path / "params.json",
            mode=RUN_MODE_ENRICHMENT,
            input_gate=INPUT_GATE,
            baseline=BASELINE_SYNONYMOUS,
        )
    )

    assert params.mode == RUN_MODE_ENRICHMENT
    assert params.scores_enrichment is True
    assert params.input_gate == INPUT_GATE
    assert params.baseline == BASELINE_SYNONYMOUS


def test_enrichment_mode_requires_an_input_gate(tmp_path):
    """Enrichment with nothing to enrich against is a caller bug: the block model refuses
    it before the run, so reaching here means the two sides disagree."""
    with pytest.raises(ValueError, match="requires inputGate"):
        load_params(write_params(tmp_path / "params.json", mode=RUN_MODE_ENRICHMENT))


def test_the_input_gate_cannot_also_be_a_rung(tmp_path):
    """It would enter its own denominator and every enrichment in that gate would be
    exactly 1 — output of ordinary shape carrying no measurement at all."""
    with pytest.raises(ValueError, match="cannot be a rung"):
        load_params(
            write_params(tmp_path / "params.json", mode=RUN_MODE_ENRICHMENT, input_gate="g2")
        )


def test_an_input_gate_outside_enrichment_mode_is_refused_not_ignored(tmp_path):
    """Naming an input in a gate-ranking run means the caller believes one is in use.
    Dropping it silently would score against nothing while the settings said otherwise."""
    with pytest.raises(ValueError, match="meaningful only in"):
        load_params(write_params(tmp_path / "params.json", input_gate=INPUT_GATE))


def test_unknown_mode_is_refused(tmp_path):
    with pytest.raises(ValueError, match="mode must be one of"):
        load_params(write_params(tmp_path / "params.json", mode="enrichment-v2"))


def test_unknown_baseline_is_refused(tmp_path):
    with pytest.raises(ValueError, match="baseline must be one of"):
        load_params(write_params(tmp_path / "params.json", baseline="parent"))


def test_the_sequence_baseline_requires_a_sequence(tmp_path):
    with pytest.raises(ValueError, match="requires baselineSequence"):
        load_params(write_params(tmp_path / "params.json", baseline=BASELINE_SEQUENCE))


def test_a_sequence_without_the_sequence_baseline_is_refused(tmp_path):
    with pytest.raises(ValueError, match="meaningful only with"):
        load_params(
            write_params(
                tmp_path / "params.json", baseline=BASELINE_SYNONYMOUS, baseline_sequence="W4"
            )
        )


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
