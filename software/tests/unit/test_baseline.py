"""Choosing the baseline set, and summarising it per gate. Expected numbers come from `conftest`.

Two silent failures the tests exist for: the parent sequence left inside the synonymous set
(W1 at 0.125 against a median of 1.5), and the spread reported as a standard error.
"""

from __future__ import annotations

import polars as pl
import pytest
from conftest import (
    BASE_MUTATION_COUNTS,
    BASE_ROWS,
    INPUT_GATE,
    INPUT_ROWS,
    SYNONYMOUS_BASELINE_LEVEL,
    SYNONYMOUS_BASELINE_SPREAD,
    SYNONYMOUS_ENRICHMENTS,
    SYNONYMOUS_GATE_RANKS,
    SYNONYMOUS_MUTATION_COUNTS,
    SYNONYMOUS_ROWS,
    SYNONYMOUS_SEQUENCES,
    SYNONYMOUS_SILENT_KEYS,
    reads_frame,
    variants_frame,
)

import codons
import scoring
from constants import (
    OUT_BIN_SCORE,
    BASELINE_ABSENT_NEEDS_NUCLEOTIDE,
    BASELINE_ABSENT_NO_MUTATION_COUNT,
    BASELINE_ABSENT_NO_SYNONYMOUS,
    BASELINE_ABSENT_PARENT_UNIDENTIFIED,
    BASELINE_ABSENT_SEQUENCE_UNKNOWN,
    BASELINE_SEQUENCE,
    BASELINE_SYNONYMOUS,
    BASELINE_WILD_TYPE,
    COL_GATE,
    COL_VARIANT,
    OUT_GATE_ENRICHMENT,
)

REL = 1e-12


def nucleotide_variants():
    return variants_frame(SYNONYMOUS_MUTATION_COUNTS, SYNONYMOUS_SEQUENCES)


def resolve(option, *, variants=False, sequence=None, rows=None):
    """Resolve a baseline the way the pipeline does — parent first, then the option.

    The `variants` default is a sentinel rather than None, because None is itself under test.
    """
    table = nucleotide_variants() if variants is False else variants
    reads = reads_frame(rows if rows is not None else SYNONYMOUS_ROWS)
    parent = scoring.resolve_parent(table)
    # The codon facts are what the synonymous option now reads its set from, so the helper
    # assembles them exactly as the pipeline does rather than stubbing them.
    facts = codons.analyse(table, reads, parent.variant_key)
    return scoring.resolve_baseline(table, reads, option, sequence, parent, facts)


def synonymous_enrichments():
    """The per-gate enrichment frame for the nucleotide-grain fixture."""
    per_gate = scoring.per_gate_frequencies(reads_frame(SYNONYMOUS_ROWS), None)
    ranked = per_gate.filter(pl.col(COL_GATE) != INPUT_GATE)
    scored = scoring.gate_rank_means(ranked, SYNONYMOUS_GATE_RANKS)
    return scoring.gate_enrichments(per_gate, scored, SYNONYMOUS_GATE_RANKS, INPUT_GATE)


# ---------------------------------------------------------------------------
# The fixture's own arithmetic, pinned before anything is summarised over it.
# ---------------------------------------------------------------------------


def test_fixture_enrichments_are_the_hand_computed_ones():
    frame = synonymous_enrichments()
    values = dict(
        zip(frame[COL_VARIANT].to_list(), frame[OUT_GATE_ENRICHMENT].to_list(), strict=True)
    )

    assert values == pytest.approx(SYNONYMOUS_ENRICHMENTS, rel=REL)


# ---------------------------------------------------------------------------
# Choosing the set.
# ---------------------------------------------------------------------------


def test_no_option_is_no_baseline_and_not_a_failure():
    """Null is an answer — a run may want the enrichment values alone — so there is no
    absence reason to report."""
    baseline = resolve(None)

    assert baseline.option is None
    assert not baseline.identified
    assert baseline.absence_reason is None


def test_wild_type_is_the_parent_row():
    baseline = resolve(BASELINE_WILD_TYPE)

    assert baseline.variant_keys == ("W1",)
    assert baseline.absence_reason is None


def test_synonymous_excludes_the_exact_parent_dna_sequence():
    """W2..W6 and not W1. This is the load-bearing exclusion, not a refinement: W1 holds
    40% of the input here, and its enrichment is nothing like the set's."""
    baseline = resolve(BASELINE_SYNONYMOUS)

    assert baseline.variant_keys == ("W2", "W3", "W4", "W5", "W6")
    assert "W1" not in baseline.variant_keys


def test_synonymous_excludes_protein_changing_variants():
    baseline = resolve(BASELINE_SYNONYMOUS)

    assert "M1" not in baseline.variant_keys


def test_the_set_is_decided_by_the_residue_not_by_the_mutation_count():
    """W2 is CTG -> TTA: two nucleotide changes, still silent. A `mutationCount == 1` filter
    would drop it and shrink the baseline by a fifth with nothing saying so."""
    assert SYNONYMOUS_MUTATION_COUNTS["W2"] == 2

    baseline = resolve(BASELINE_SYNONYMOUS)

    assert "W2" in baseline.variant_keys
    assert baseline.variant_keys == SYNONYMOUS_SILENT_KEYS


def test_a_variant_changing_two_codons_is_not_in_the_set():
    """Silent at both codons and still excluded: a two-codon variant is error-derived, and the
    per-position grouping has no single position to file it under."""
    # A Leu-Leu-Trp parent, so two codons can both change silently.
    variants = variants_frame(
        {"P": 0, "D": 4, "S": 1},
        {
            "P": "CTGCTGTGG",  # Leu Leu Trp
            "D": "TTACTTTGG",  # both Leu codons changed, both still Leu
            "S": "TTGCTGTGG",  # one Leu codon changed, still Leu
        },
    )
    reads = reads_frame([("g1", "P", 10), ("g1", "D", 10), ("g1", "S", 10)])
    parent_row = scoring.resolve_parent(variants)
    facts = codons.analyse(variants, reads, parent_row.variant_key)

    # S changed one Leu codon silently and is in; D changed two and is out.
    assert facts.silent_variants == ("S",)
    assert "D" not in facts.changes


def test_named_sequence_is_taken_when_the_reads_carry_it():
    baseline = resolve(BASELINE_SEQUENCE, sequence="W4")

    assert baseline.variant_keys == ("W4",)
    assert baseline.absence_reason is None


def test_named_sequence_needs_no_mutation_count_table():
    """A named sequence is a key, not a count — so this option works on a run where the
    mutation-count predicate resolved to nothing."""
    baseline = resolve(BASELINE_SEQUENCE, variants=None, sequence="W4")

    assert baseline.variant_keys == ("W4",)


# The four ways it has nothing to choose; each names a different thing to fix.


def test_synonymous_at_protein_grain_says_which_grain_would_have_it():
    """At the amino-acid grain the synonymous variants have already been merged into the
    wild type, so there is nothing to select — and the caller has to change the dataset,
    not the option."""
    baseline = resolve(
        BASELINE_SYNONYMOUS,
        variants=variants_frame(BASE_MUTATION_COUNTS),
        rows=BASE_ROWS + INPUT_ROWS,
    )

    assert not baseline.identified
    assert baseline.absence_reason == BASELINE_ABSENT_NEEDS_NUCLEOTIDE


def test_synonymous_with_no_silent_variants_is_its_own_reason():
    """Readable sequences, no silent variant — distinct from having no sequences at all.
    M1's changed codon turns Leu into Val."""
    variants = variants_frame({"W1": 0, "M1": 1}, {"W1": "ATGCTGTGG", "M1": "ATGGTGTGG"})
    baseline = resolve(BASELINE_SYNONYMOUS, variants=variants)

    assert baseline.absence_reason == BASELINE_ABSENT_NO_SYNONYMOUS


def test_wild_type_without_an_identifiable_parent():
    """Two zero-count rows: the parent is unidentifiable, so there is no wild-type row to
    take."""
    variants = variants_frame({"W1": 0, "W2": 0, "M1": 1})
    baseline = resolve(BASELINE_WILD_TYPE, variants=variants)

    assert baseline.absence_reason == BASELINE_ABSENT_PARENT_UNIDENTIFIED


def test_wild_type_without_a_mutation_count_table():
    baseline = resolve(BASELINE_WILD_TYPE, variants=None)

    assert baseline.absence_reason == BASELINE_ABSENT_NO_MUTATION_COUNT


def test_named_sequence_the_dataset_does_not_carry():
    """A typo reaches here as a key matching nothing, and is reported rather than producing
    an empty baseline nobody asked about."""
    baseline = resolve(BASELINE_SEQUENCE, sequence="W9")

    assert not baseline.identified
    assert baseline.absence_reason == BASELINE_ABSENT_SEQUENCE_UNKNOWN


# ---------------------------------------------------------------------------
# Summarising it per gate.
# ---------------------------------------------------------------------------


def test_level_is_the_median_of_the_synonymous_values():
    """[0.5, 1.0, 1.5, 2.0, 2.5] — the median is 1.5."""
    summary = scoring.baseline_summary(
        synonymous_enrichments(), resolve(BASELINE_SYNONYMOUS), SYNONYMOUS_GATE_RANKS
    )

    assert summary["g1"]["level"] == pytest.approx(SYNONYMOUS_BASELINE_LEVEL, rel=REL)


def test_spread_is_percentiles_and_carries_no_standard_error():
    """The four percentiles, hand-computed with linear interpolation over five values.

    The second assertion is the point: no mean and no SE are emitted, not even alongside."""
    summary = scoring.baseline_summary(
        synonymous_enrichments(), resolve(BASELINE_SYNONYMOUS), SYNONYMOUS_GATE_RANKS
    )
    entry = summary["g1"]

    assert entry["spread"] == pytest.approx(SYNONYMOUS_BASELINE_SPREAD, rel=REL)
    assert set(entry) == {"level", "spread", "variants"}
    assert set(entry["spread"]) == {"p5", "p25", "p75", "p95"}


def test_the_count_says_how_many_variants_back_the_number():
    summary = scoring.baseline_summary(
        synonymous_enrichments(), resolve(BASELINE_SYNONYMOUS), SYNONYMOUS_GATE_RANKS
    )

    assert summary["g1"]["variants"] == 5


def test_including_the_parent_dna_would_move_the_level():
    """Not a test of the code but of the fixture: it pins that the exclusion is observable,
    so `test_synonymous_excludes_the_exact_parent_dna_sequence` cannot pass vacuously."""
    with_parent = ("W1", "W2", "W3", "W4", "W5", "W6")
    baseline = scoring.Baseline(BASELINE_SYNONYMOUS, with_parent, None)
    summary = scoring.baseline_summary(synonymous_enrichments(), baseline, SYNONYMOUS_GATE_RANKS)

    # Six values: [0.125, 0.5, 1.0, 1.5, 2.0, 2.5], median (1.0 + 1.5) / 2 = 1.25.
    assert summary["g1"]["level"] == pytest.approx(1.25, rel=REL)
    assert summary["g1"]["level"] != pytest.approx(SYNONYMOUS_BASELINE_LEVEL, rel=REL)


def test_a_single_variant_baseline_has_a_degenerate_spread():
    """Wild type and a named sequence are one variant each, so every percentile is that
    variant's own value. Honest rather than suppressed — the count says why."""
    summary = scoring.baseline_summary(
        synonymous_enrichments(), resolve(BASELINE_WILD_TYPE), SYNONYMOUS_GATE_RANKS
    )
    entry = summary["g1"]

    assert entry["variants"] == 1
    assert entry["level"] == pytest.approx(SYNONYMOUS_ENRICHMENTS["W1"], rel=REL)
    assert all(
        value == pytest.approx(SYNONYMOUS_ENRICHMENTS["W1"], rel=REL)
        for value in entry["spread"].values()
    )


def test_no_baseline_summarises_to_nothing():
    summary = scoring.baseline_summary(
        synonymous_enrichments(), resolve(None), SYNONYMOUS_GATE_RANKS
    )

    assert summary == {}


def test_a_baseline_whose_variants_were_all_floored_out_summarises_to_nothing():
    """Absent, not a level of zero: a zero level would be a measured baseline sitting at
    complete depletion."""
    enrichments = synonymous_enrichments().filter(~pl.col(COL_VARIANT).str.starts_with("W"))
    summary = scoring.baseline_summary(
        enrichments, resolve(BASELINE_SYNONYMOUS), SYNONYMOUS_GATE_RANKS
    )

    assert summary == {}


# The per-position split. The mask fails silently: let an off-scheme silent variant through
# and an invariable position acquires a baseline built from sequencing error.


def nnk_library(parent: str, extra: dict[str, str] | None = None):
    """A parent plus a full NNK spread at codon 0. `extra` adds off-scheme or second-position
    variants, each with few reads as a real error would have."""
    codons_nnk = [a + b + c for a in "ACGT" for b in "ACGT" for c in "GT"]
    parent_codons = [parent[i : i + 3] for i in range(0, len(parent), 3)]

    sequences = {"P": parent}
    reads = {"P": 5000}
    for index, codon in enumerate(codons_nnk):
        if codon == parent_codons[0]:
            continue
        sequences[f"n{index}"] = codon + parent[3:]
        reads[f"n{index}"] = 1000
    for key, sequence in (extra or {}).items():
        sequences[key] = sequence
        reads[key] = 5

    counts = {
        key: sum(1 for a, b in zip(parent, sequence, strict=True) if a != b)
        for key, sequence in sequences.items()
    }
    variants = variants_frame(counts, sequences)
    rows = [("in", key, count) for key, count in reads.items()]
    rows += [("g1", key, max(1, count // 2)) for key, count in reads.items()]
    return variants, reads_frame(rows)


def positions_for(variants, reads):
    """Run the per-condition path and hand back the per-position frames."""
    parent = scoring.resolve_parent(variants)
    facts = codons.analyse(variants, reads, parent.variant_key)
    baseline = scoring.resolve_baseline(
        variants, reads, BASELINE_SYNONYMOUS, None, parent, facts
    )
    per_gate = scoring.per_gate_frequencies(reads, None)
    ranked = per_gate.filter(pl.col(COL_GATE) != INPUT_GATE)
    scored = scoring.gate_rank_means(ranked, {"g1": 1})
    enrichments = scoring.gate_enrichments(per_gate, scored, {"g1": 1}, INPUT_GATE)
    return facts, baseline, scoring.baseline_by_position(enrichments, baseline, facts, {"g1": 1})


def test_positions_are_grouped_by_the_changed_codon():
    """A Leu-Leu-Trp parent with the NNK spread at codon 0. NNK holds three Leu codons — CTG,
    CTT, TTG — so a CTG parent has exactly two synonyms, both at position 0."""
    variants, reads = nnk_library("CTGCTGTGG")
    facts, baseline, positions = positions_for(variants, reads)

    assert facts.scheme.label() == "NNK"
    assert set(positions) == {"g1"}

    frame = positions["g1"]
    assert frame["position"].to_list() == [0]
    assert frame["baselineVariants"].to_list() == [2]


def test_an_off_scheme_silent_variant_is_masked_out():
    """CTC is silent Leu but not an NNK codon, so it is a sequencing error at a codon where
    nothing else varies. Without the mask, position 1 gets a baseline of one error value."""
    variants, reads = nnk_library("CTGCTGTGG", extra={"err": "CTGCTCTGG"})
    facts, baseline, positions = positions_for(variants, reads)

    assert facts.changes["err"].silent is True
    assert facts.changes["err"].codon == "CTC"
    assert "CTC" not in facts.scheme.codons

    # Excluded from the set, so position 1 never appears.
    assert "err" not in baseline.variant_keys
    assert positions["g1"]["position"].to_list() == [0]


def test_an_unreachable_position_gets_no_row():
    """Trp has one codon in the whole genetic code, so codon 2 can carry no silent change and
    no amount of coverage would give it a baseline."""
    variants, reads = nnk_library("CTGCTGTGG")
    facts, _, positions = positions_for(variants, reads)

    assert facts.reachable[2] is False
    assert 2 not in positions["g1"]["position"].to_list()


def test_only_the_synonymous_option_is_split_by_position():
    """Wild type and a named sequence are single variants, so a per-position split of them is
    one number repeated — nothing the per-gate summary does not already say."""
    variants, reads = nnk_library("CTGCTGTGG")
    parent = scoring.resolve_parent(variants)
    facts = codons.analyse(variants, reads, parent.variant_key)
    per_gate = scoring.per_gate_frequencies(reads, None)
    ranked = per_gate.filter(pl.col(COL_GATE) != INPUT_GATE)
    scored = scoring.gate_rank_means(ranked, {"g1": 1})
    enrichments = scoring.gate_enrichments(per_gate, scored, {"g1": 1}, INPUT_GATE)

    for option in (BASELINE_WILD_TYPE, BASELINE_SEQUENCE, None):
        baseline = scoring.resolve_baseline(variants, reads, option, "P", parent, facts)
        assert scoring.baseline_by_position(enrichments, baseline, facts, {"g1": 1}) == {}


def test_the_split_carries_the_same_shape_as_the_per_gate_summary():
    """Level, the four percentiles and a count — one shape for a consumer to learn."""
    variants, reads = nnk_library("CTGCTGTGG")
    _, _, positions = positions_for(variants, reads)

    assert positions["g1"].columns == [
        "position",
        "baselineLevel",
        "baselineP5",
        "baselineP25",
        "baselineP75",
        "baselineP95",
        "baselineVariants",
    ]


# ---------------------------------------------------------------------------
# The baseline as a reference the consumer can read directly.
# ---------------------------------------------------------------------------


def test_enrichment_vs_baseline_divides_rather_than_subtracts():
    """The synonymous set is W2..W6 with enrichments 0.5, 1.0, 1.5, 2.0, 2.5, so the level is
    the median 1.5.

    M1 enriches at 2.0. Against the baseline that is 2.0 / 1.5 = 4/3 — a third above no change.
    Subtracting would give 0.5, which is not comparable to any other gate's 0.5.
    """
    level = 1.5
    assert 2.0 / level == pytest.approx(4 / 3, rel=REL)
    # W4 sits exactly on the level, so it reads as 1.0 — a variant of no effect.
    assert 1.5 / level == pytest.approx(1.0, rel=REL)


def test_the_bin_score_baseline_is_one_number_per_condition():
    """`binScore` is per variant, not per gate, so its baseline is one level and one band for
    the whole condition — unlike the enrichment baseline, which is one per gate."""
    values = pl.DataFrame(
        {COL_VARIANT: ["W2", "W3", "W4", "W5", "W6"], OUT_BIN_SCORE: [-0.2, -0.1, 0.0, 0.1, 0.3]}
    )
    baseline = scoring.Baseline(BASELINE_SYNONYMOUS, ("W2", "W3", "W4", "W5", "W6"), None)

    summary = scoring.value_baseline(values, OUT_BIN_SCORE, baseline)

    assert summary["variants"] == 5
    assert summary["level"] == pytest.approx(0.0, abs=1e-12)
    # Linear interpolation over five values: p5 sits at index 0.2, p95 at index 3.8.
    assert summary["spread"]["p5"] == pytest.approx(-0.2 + 0.2 * 0.1, rel=REL)
    assert summary["spread"]["p95"] == pytest.approx(0.1 + 0.8 * 0.2, rel=REL)


def test_the_bin_score_baseline_level_flags_an_atypical_parent():
    """The level should read near zero, because binScore already subtracts the parent. A level
    far from zero says the parent sequence is not typical of its own synonymous family, and
    every vs-parent value on the run is shifted by that much."""
    shifted = pl.DataFrame(
        {COL_VARIANT: ["W2", "W3", "W4"], OUT_BIN_SCORE: [0.38, 0.40, 0.44]}
    )
    baseline = scoring.Baseline(BASELINE_SYNONYMOUS, ("W2", "W3", "W4"), None)

    summary = scoring.value_baseline(shifted, OUT_BIN_SCORE, baseline)

    assert summary["level"] == pytest.approx(0.40, rel=REL)
    assert abs(summary["level"]) > 0.2


def test_no_baseline_means_no_summary():
    """Absent, not a zero: a level of 0 would be a measured baseline sitting at no change."""
    values = pl.DataFrame({COL_VARIANT: ["W2"], OUT_BIN_SCORE: [0.1]})
    assert scoring.value_baseline(values, OUT_BIN_SCORE, scoring.Baseline(None, (), None)) is None
