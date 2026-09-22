"""The codon facts, from the genetic code up. Two silent failures shape the suite:

* reachability read off the residue instead of the codon — under NNK a parent TTC is
  reachable and a parent TTT is not, so one codon per residue passes either way;
* the scheme inferred from errors — counting distinct variants instead of reads lets thin
  errors outvote the designed set and marks unreachable positions reachable.
"""

from __future__ import annotations

import polars as pl
import pytest

import codons
from constants import (
    CODON_ABSENT_NO_SEQUENCE,
    CODON_ABSENT_NO_SINGLE_CODON_VARIANTS,
    CODON_ABSENT_NOT_DEGENERATE,
    CODON_ABSENT_PARENT_OUT_OF_FRAME,
    CODON_ABSENT_PARENT_UNIDENTIFIED,
    POSITION_ALIGN_LENGTH_MISMATCH,
    POSITION_ALIGN_MULTIPLE_PARENTS,
    POSITION_ALIGN_NON_NUMERIC,
    POSITION_ALIGN_RESIDUE_MISMATCH,
)

NNK = [a + b + c for a in "ACGT" for b in "ACGT" for c in "GT"]


# ---------------------------------------------------------------------------
# The genetic code. Spot-checked rather than trusted, because the table is written compactly.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("codon", "expected"),
    [
        ("ATG", "M"),  # start / Met, the only Met codon
        ("TGG", "W"),  # the only Trp codon
        ("TTT", "F"),
        ("TTC", "F"),  # the Phe pair the reachability rule turns on
        ("TAA", "*"),
        ("TAG", "*"),  # amber, which NNK contains
        ("TGA", "*"),
        ("GGG", "G"),
        ("CTG", "L"),
        ("AGT", "S"),  # Ser reached from the AGN box, not the TCN one
    ],
)
def test_genetic_code_spot_checks(codon, expected):
    assert codons.residue(codon) == expected


def test_the_table_is_complete_and_has_three_stops():
    assert len(codons.CODON_TABLE) == 64
    assert sum(1 for value in codons.CODON_TABLE.values() if value == "*") == 3


def test_a_non_codon_has_no_residue():
    """None rather than a placeholder: an N is not a residue, and a placeholder would compare
    equal to itself and make two unknowns look synonymous."""
    assert codons.residue("NNN") is None
    assert codons.residue("AT") is None


# ---------------------------------------------------------------------------
# Splitting and the frame guard.
# ---------------------------------------------------------------------------


def test_split_codons():
    assert codons.split_codons("ATGTTTTGG") == ["ATG", "TTT", "TGG"]


def test_a_sequence_that_is_not_whole_codons_is_refused():
    """The frame guard. Read one base out, every codon after the offset is nonsense — so a bad
    length produces no codon facts rather than confident wrong ones."""
    assert codons.split_codons("ATGTTTTG") is None
    assert codons.split_codons("") is None


def test_translates_cleanly_catches_an_out_of_frame_parent():
    """A length that is a multiple of three can still be the wrong frame. An internal stop is
    what gives that away, and it is what `split_codons` alone cannot catch."""
    assert codons.translates_cleanly(["ATG", "TTT", "TGG"])
    # A trailing stop is ordinary — it is the end of the coding sequence.
    assert codons.translates_cleanly(["ATG", "TTT", "TAA"])
    assert not codons.translates_cleanly(["ATG", "TAA", "TTT"])
    assert not codons.translates_cleanly(["ATG", "NNN", "TTT"])


# ---------------------------------------------------------------------------
# Which codon a variant changed.
# ---------------------------------------------------------------------------


def test_one_changed_codon_is_reported():
    parent = ["ATG", "TTC", "TGG"]
    assert codons.changed_codon(parent, ["ATG", "TTT", "TGG"]) == 1


def test_the_parent_itself_changed_nothing():
    parent = ["ATG", "TTC", "TGG"]
    assert codons.changed_codon(parent, parent) is None


def test_more_than_one_changed_codon_is_not_a_designed_variant():
    """A site-saturation variant changes exactly one codon. Two or more is dominated by
    sequencing and PCR error, so it says nothing about the library and is excluded from the
    inference — which is the strongest error filter available here."""
    parent = ["ATG", "TTC", "TGG"]
    assert codons.changed_codon(parent, ["ATG", "TTT", "TGT"]) is None


def test_a_different_length_is_not_comparable():
    assert codons.changed_codon(["ATG", "TTC"], ["ATG"]) is None


# ---------------------------------------------------------------------------
# Inferring the scheme.
# ---------------------------------------------------------------------------


def nnk_observations(reads: int = 1000, position: int = 0):
    """One observation per NNK codon, evenly weighted. All at one position unless told
    otherwise; cross-position weighting is `test_one_deep_position_cannot_decide_the_scheme`."""
    return [(position, codon, reads) for codon in NNK]


def test_nnk_is_inferred_from_nnk_observations():
    scheme = codons.infer_scheme(nnk_observations())

    assert scheme is not None
    assert scheme.label() == "NNK"
    assert scheme.codons == frozenset(NNK)
    assert len(scheme.codons) == 32


def test_rare_error_codons_do_not_widen_the_scheme():
    """Errors outnumber designed observations fifty to one and still lose, carrying 1 read
    each against 1000. Counted by distinct variant, NNK would be inferred as NNN."""
    observations = nnk_observations(reads=1000)
    # Each off-scheme codon seen once at each of 50 positions, one read apiece.
    errors = [
        (0, a + b + c, 1) for a in "ACGT" for b in "ACGT" for c in "AC" for _ in range(50)
    ]
    assert len(errors) > 50 * len(observations) / 2

    scheme = codons.infer_scheme(observations + errors)

    assert scheme is not None
    assert scheme.label() == "NNK"
    assert scheme.bases[2] == frozenset("GT")


def test_the_reported_frequencies_are_what_a_human_checks():
    """Roughly 50/46/2/2 at the third offset is the separation that makes the threshold safe.
    The frequencies travel so a narrow separation is visible rather than assumed away."""
    observations = nnk_observations(reads=1000)
    observations += [(0, a + b + c, 40) for a in "ACGT" for b in "ACGT" for c in "AC"]

    scheme = codons.infer_scheme(observations)

    third = scheme.frequencies[2]
    assert third["G"] == pytest.approx(0.4808, abs=1e-3)
    assert third["T"] == pytest.approx(0.4808, abs=1e-3)
    assert third["A"] == pytest.approx(0.0192, abs=1e-3)
    assert third["C"] == pytest.approx(0.0192, abs=1e-3)


def test_nnn_and_nns_are_inferred_too():
    """The inference is not hardcoded to NNK — it reads whatever the library used."""
    nnn = [a + b + c for a in "ACGT" for b in "ACGT" for c in "ACGT"]
    nns = [a + b + c for a in "ACGT" for b in "ACGT" for c in "CG"]

    assert codons.infer_scheme([(0, c, 100) for c in nnn]).label() == "NNN"
    assert codons.infer_scheme([(0, c, 100) for c in nns]).label() == "NNS"


def test_nothing_to_infer_from():
    assert codons.infer_scheme([]) is None
    assert codons.infer_scheme([(0, "ATG", 0)]) is None


def test_a_single_sequence_is_not_a_library():
    """Every offset admitting one base means no position varies, so every reachability answer
    would be false. Refused as "not a library" rather than emitted as a confident nothing."""
    assert codons.infer_scheme([(0, "ATG", 1000)]) is None


# ---------------------------------------------------------------------------
# Reachability — the case that turns on the codon rather than the residue.
# ---------------------------------------------------------------------------


def nnk_scheme():
    return codons.infer_scheme(nnk_observations())


def test_phe_is_reachable_from_ttc_and_not_from_ttt():
    """The whole point, in one test. NNK's only Phe codon is TTT, so a parent TTC has a
    synonymous change available and a parent TTT does not — same residue, opposite answers."""
    answers = codons.reachable_positions(["TTC", "TTT"], nnk_scheme())

    assert answers[0] is True
    assert answers[1] is False


@pytest.mark.parametrize("parent_codon", ["ATG", "TGG"])
def test_met_and_trp_are_never_reachable(parent_codon):
    """One codon each in the entire genetic code, so no scheme can produce a synonym."""
    assert codons.reachable_positions([parent_codon], nnk_scheme())[0] is False


@pytest.mark.parametrize("parent_codon", ["CTG", "CGG", "TCG", "GCG", "GGG", "CCG", "ACG", "GTG"])
def test_the_eight_multi_codon_residues_are_always_reachable(parent_codon):
    """Leu, Arg, Ser, Ala, Gly, Pro, Thr and Val hold two or more NNK codons each, so one is
    always available that differs from the parent's — whatever the parent's codon is."""
    assert codons.reachable_positions([parent_codon], nnk_scheme())[0] is True


@pytest.mark.parametrize(
    ("reachable_codon", "unreachable_codon"),
    [
        ("TGC", "TGT"),  # Cys
        ("GAC", "GAT"),  # Asp
        ("GAA", "GAG"),  # Glu
        ("CAC", "CAT"),  # His
        ("ATC", "ATT"),  # Ile
        ("AAA", "AAG"),  # Lys
        ("AAC", "AAT"),  # Asn
        ("CAA", "CAG"),  # Gln
        ("TAC", "TAT"),  # Tyr
    ],
)
def test_the_ten_conditional_residues_turn_on_the_parent_codon(reachable_codon, unreachable_codon):
    """Each of these residues has exactly one NNK codon. The parent using the other one is
    reachable; the parent already using the NNK one is not."""
    scheme = nnk_scheme()
    assert codons.reachable_positions([reachable_codon], scheme)[0] is True
    assert codons.reachable_positions([unreachable_codon], scheme)[0] is False


def test_a_stop_parent_codon_is_not_reachable():
    """No synonymous *change* is meaningful at a stop."""
    assert codons.reachable_positions(["TAA"], nnk_scheme())[0] is False


def test_the_71_of_91_decomposition():
    """6 Met/Trp positions are unreachable under any scheme (91 - 85). 14 more carry a
    conditional residue and already use its NNK codon, taking 85 down to 71."""
    parent = (
        ["ATG"] * 3  # Met
        + ["TGG"] * 3  # Trp        -> 6 unreachable under any scheme
        + ["TTT", "TGT", "GAT", "GAG", "CAT", "ATT", "AAG"]
        + ["AAT", "CAG", "TAT", "TTT", "GAT", "CAG", "TAT"]  # 14 already-NNK codons
        + ["CTG"] * 71  # Leu, always reachable
    )
    assert len(parent) == 91

    answers = codons.reachable_positions(parent, nnk_scheme())
    reachable = sum(1 for value in answers.values() if value)

    assert reachable == 71


# ---------------------------------------------------------------------------
# The frame-level entry point.
# ---------------------------------------------------------------------------

PARENT_SEQ = "ATGTTCTGGCTG"  # Met Phe Trp Leu


def variants_with_sequences(rows: dict[str, str]):
    keys = sorted(rows)
    return pl.DataFrame(
        {
            "variantKey": keys,
            "mutationCount": [0 if key == "P" else 1 for key in keys],
            "sequence": [rows[key] for key in keys],
        },
        schema_overrides={"mutationCount": pl.Int64},
    )


def reads_for(rows: dict[str, int]):
    keys = sorted(rows)
    return pl.DataFrame(
        {
            "sampleId": ["s1"] * len(keys),
            "variantKey": keys,
            "reads": [rows[key] for key in keys],
            "condition": ["pH7"] * len(keys),
            "gate": ["g1"] * len(keys),
        },
        schema_overrides={"reads": pl.Int64},
    )


def test_analyse_end_to_end():
    """Every variant changes codon 1 (Phe) to a different NNK codon. The scheme cannot be
    inferred from one offset's worth of variety, so this pins the plumbing rather than the
    inference: the parent is split, each variant's changed codon is found, and the reads follow."""
    sequences = {"P": PARENT_SEQ}
    reads = {"P": 500}
    for index, codon in enumerate(NNK):
        key = f"v{index}"
        sequences[key] = "ATG" + codon + "TGGCTG"
        reads[key] = 100

    facts = codons.analyse(variants_with_sequences(sequences), reads_for(reads), "P")

    assert facts.identified
    assert facts.scheme.label() == "NNK"
    assert facts.parent_codons == ["ATG", "TTC", "TGG", "CTG"]
    # Met unreachable, Phe reachable from TTC, Trp unreachable, Leu reachable.
    assert facts.reachable == {0: False, 1: True, 2: False, 3: True}
    assert facts.unreachable_positions == [0, 2]
    assert facts.reachable_count == 2
    # Every variant changed codon 1, and the parent is not in the map.
    assert set(c.position for c in facts.changes.values()) == {1}
    assert "P" not in facts.changes


def test_analyse_without_a_sequence_column():
    """The ordinary amino-acid-grain run: no sequence, no codon facts, and a reason saying so."""
    variants = pl.DataFrame(
        {"variantKey": ["P"], "mutationCount": [0]}, schema_overrides={"mutationCount": pl.Int64}
    )
    facts = codons.analyse(variants, reads_for({"P": 10}), "P")

    assert not facts.identified
    assert facts.absence_reason == CODON_ABSENT_NO_SEQUENCE


def test_analyse_without_a_parent():
    facts = codons.analyse(variants_with_sequences({"P": PARENT_SEQ}), reads_for({"P": 10}), None)

    assert facts.absence_reason == CODON_ABSENT_PARENT_UNIDENTIFIED


def test_analyse_with_an_out_of_frame_parent():
    """A parent that translates with an internal stop is not in frame, so every codon read from
    it would be nonsense."""
    facts = codons.analyse(
        variants_with_sequences({"P": "ATGTAACTG"}), reads_for({"P": 10}), "P"
    )

    assert facts.absence_reason == CODON_ABSENT_PARENT_OUT_OF_FRAME


def test_analyse_with_only_multi_codon_variants():
    """Nothing in the run is a designed single-codon variant, so there is nothing to infer from."""
    facts = codons.analyse(
        variants_with_sequences({"P": PARENT_SEQ, "v": "ATGTTTTGTCTG"}),
        reads_for({"P": 100, "v": 100}),
        "P",
    )

    assert facts.absence_reason == CODON_ABSENT_NO_SINGLE_CODON_VARIANTS


def test_analyse_with_no_variety_is_not_a_library():
    facts = codons.analyse(
        variants_with_sequences({"P": PARENT_SEQ, "v": "ATGTTTTGGCTG"}),
        reads_for({"P": 100, "v": 100}),
        "P",
    )

    assert facts.absence_reason == CODON_ABSENT_NOT_DEGENERATE


# Matching codon offsets to the profiler's position labels. Every refusal below is the safe
# outcome; assuming the numberings agree puts every value on the wrong residue.

ALIGN_PARENT = ["ATG", "CTG", "TGG"]  # Met Leu Trp


def test_labels_are_ordered_numerically_not_lexically():
    """A lexical sort puts position 10 before position 2, which would shift every residue after
    the ninth. The parent here is long enough for that to bite."""
    parent = ["ATG"] * 9 + ["CTG"] * 2  # 11 positions: M x9, L x2
    labels = [str(i) for i in range(1, 12)]
    residues = ["M"] * 9 + ["L"] * 2

    result = codons.align_positions(parent, ["p"] * 11, labels, residues)

    assert result.verified
    assert result.labels[9:] == ("10", "11")


def test_a_residue_disagreement_refuses():
    """The check that makes the mapping a fact. The parent's second codon is Leu; the profiler
    saying Val there means the two numberings are not describing the same positions."""
    result = codons.align_positions(
        ALIGN_PARENT, ["p"] * 3, ["1", "2", "3"], ["M", "V", "W"]
    )

    assert not result.verified
    assert result.reason == POSITION_ALIGN_RESIDUE_MISMATCH


def test_an_off_by_one_numbering_is_caught():
    """The exact failure this exists for: the profiler's labels shifted by one against the
    codons. Nothing about the shapes is wrong — only the residues give it away."""
    parent = ["ATG", "CTG", "TGG"]
    # Residues shifted: the labels describe positions 0,1,2 but carry 1,2,3's residues.
    result = codons.align_positions(parent, ["p"] * 3, ["1", "2", "3"], ["L", "W", "M"])

    assert not result.verified
    assert result.reason == POSITION_ALIGN_RESIDUE_MISMATCH


def test_a_length_mismatch_refuses():
    result = codons.align_positions(ALIGN_PARENT, ["p"] * 2, ["1", "2"], ["M", "L"])

    assert result.reason == POSITION_ALIGN_LENGTH_MISMATCH


def test_non_numeric_labels_refuse():
    """An IMGT-style or otherwise non-numeric numbering is one this code cannot order, and
    guessing at it is the whole failure being prevented."""
    result = codons.align_positions(
        ALIGN_PARENT, ["p"] * 3, ["1", "2A", "3"], ["M", "L", "W"]
    )

    assert result.reason == POSITION_ALIGN_NON_NUMERIC


def test_more_than_one_parent_refuses():
    """The rest of the block assumes one parent — `resolve_parent` takes the single
    zero-mutation row — so a multi-parent table is out of scope rather than mishandled."""
    result = codons.align_positions(
        ALIGN_PARENT, ["p", "q", "p"], ["1", "2", "3"], ["M", "L", "W"]
    )

    assert result.reason == POSITION_ALIGN_MULTIPLE_PARENTS


def test_a_verified_alignment_carries_the_parent_and_the_labels():
    result = codons.align_positions(
        ALIGN_PARENT, ["vh"] * 3, ["1", "2", "3"], ["M", "L", "W"]
    )

    assert result.verified
    assert result.parent_id == "vh"
    assert result.labels == ("1", "2", "3")
    assert result.reason is None


def test_one_deep_position_cannot_decide_the_scheme():
    """Ten ordinary NNK positions against one carrying GAA at thirty times the depth. The
    answer must still be NNK: each position votes once, whatever its depth.

    Read-weighting across positions instead returns NND."""
    observations = []
    for position in range(10):
        observations += nnk_observations(reads=1000, position=position)
    observations += [(99, "GAA", 300_000)]

    scheme = codons.infer_scheme(observations)

    assert scheme is not None
    assert scheme.label() == "NNK"
    assert scheme.bases[2] == frozenset("GT")


def test_reads_still_decide_within_a_position():
    """The other half of the rule, and why it is not simply "count distinct codons". Within one
    position a thin error must still lose to the designed codons — it is only *across* positions
    that depth stops counting."""
    observations = nnk_observations(reads=1000, position=0)
    observations += [(0, a + b + "C", 1) for a in "ACGT" for b in "ACGT"]

    scheme = codons.infer_scheme(observations)

    assert scheme.bases[2] == frozenset("GT")
