"""Many parents in one dataset.

The profiler takes a FASTA of parents and puts every parent's variants on one variant axis, so
a dataset may carry any number. Depths must be taken within a parent: pooling them scales every
variant of a parent by how well its whole scaffold sorted, and nothing about the result looks
wrong.

The fixture below is built so that scoping and pooling disagree by a wide margin, and so that
the scoped answer is a number computable by hand.
"""

from __future__ import annotations

import polars as pl
import pytest
from conftest import INPUT_GATE, reads_frame, variants_frame, write_tsv

import io_layer
import pipeline
import pooling
import scoring
from constants import COL_PARENT_ID, OUT_GATE_ENRICHMENT, OUT_GATE_RANK_MEAN

REL = 1e-12

# Two parents, two variants each, two ranked gates and an input.
#
#         | in  | g1  | g2
#   ------+-----+-----+-----
#   a1    |  50 |  10 |  40
#   a2    |  50 |  10 |  40
#   b1    |  50 |  80 |  10
#   b2    |  50 |  80 |  10
#   ------+-----+-----+-----
#   A     | 100 |  20 |  80
#   B     | 100 | 160 |  20
#   total | 200 | 180 | 100
#
# Within its own parent every variant is exactly half of it in every gate, so every scoped
# enrichment is 1.0 and every scoped gate rank mean is 1.5. The two parents sort in opposite
# directions, so pooling moves all four numbers a long way:
#
#   A's share of g2 is 0.80 against 0.50 of the input -> x1.6 on every A variant
#   B's share of g2 is 0.20 against 0.50 of the input -> x0.4 on every B variant
PARENTS = {"a1": "A", "a2": "A", "b1": "B", "b2": "B"}

ROWS = [
    (INPUT_GATE, "a1", 50), (INPUT_GATE, "a2", 50), (INPUT_GATE, "b1", 50), (INPUT_GATE, "b2", 50),
    ("g1", "a1", 10), ("g1", "a2", 10), ("g1", "b1", 80), ("g1", "b2", 80),
    ("g2", "a1", 40), ("g2", "a2", 40), ("g2", "b1", 10), ("g2", "b2", 10),
]

RANKS = {"g1": 1, "g2": 2}


def per_gate(parents: dict[str, str] | None):
    return scoring.per_gate_frequencies(reads_frame(ROWS, parents=parents), None)


def means_of(parents: dict[str, str] | None) -> dict[str, float]:
    ranked = per_gate(parents).filter(pl.col("gate") != INPUT_GATE)
    frame = scoring.gate_rank_means(ranked, RANKS)
    return dict(zip(frame["variantKey"].to_list(), frame[OUT_GATE_RANK_MEAN].to_list()))


def enrichments_of(parents: dict[str, str] | None) -> dict[tuple[str, str], float]:
    frame = per_gate(parents)
    ranked = frame.filter(pl.col("gate") != INPUT_GATE)
    scored = scoring.gate_rank_means(ranked, RANKS)
    rows = scoring.gate_enrichments(frame, scored, RANKS, INPUT_GATE)
    return {
        (gate, variant): value
        for variant, gate, value in zip(
            rows["variantKey"].to_list(), rows["gate"].to_list(), rows[OUT_GATE_ENRICHMENT].to_list()
        )
    }


# ---------------------------------------------------------------------------
# The fix.
# ---------------------------------------------------------------------------


def test_enrichment_is_taken_within_the_parent():
    """Every variant is half of its own parent in every gate, so every enrichment is exactly 1.0.

    It is the same 1.0 for a variant of the parent that sorted well and one of the parent that
    did not, which is the whole point: a variant's enrichment must not carry its scaffold's."""
    assert enrichments_of(PARENTS) == pytest.approx(
        {
            ("g1", "a1"): 1.0, ("g1", "a2"): 1.0, ("g1", "b1"): 1.0, ("g1", "b2"): 1.0,
            ("g2", "a1"): 1.0, ("g2", "a2"): 1.0, ("g2", "b1"): 1.0, ("g2", "b2"): 1.0,
        },
        rel=REL,
    )


def test_pooling_the_parents_scales_every_variant_by_its_scaffold():
    """What the fix prevents, stated as a number. Drop the parents and the same four variants
    that are all genuinely unchanged come back at 1.6 and 0.4 — the two parents' own
    enrichments in that gate."""
    pooled = enrichments_of(None)

    assert pooled[("g2", "a1")] == pytest.approx(1.6, rel=REL)
    assert pooled[("g2", "b1")] == pytest.approx(0.4, rel=REL)
    # The distortion is exactly the parent's share of the gate over its share of the input.
    assert pooled[("g2", "a1")] / 1.0 == pytest.approx((80 / 100) / (100 / 200), rel=REL)


def test_gate_rank_mean_is_taken_within_the_parent():
    """Both parents' variants sit half in each gate, so every scoped mean is 1.5 — the midpoint
    of a two-gate ladder."""
    assert means_of(PARENTS) == pytest.approx({"a1": 1.5, "a2": 1.5, "b1": 1.5, "b2": 1.5}, rel=REL)


def test_pooling_the_parents_moves_the_gate_rank_mean():
    """The same four variants, pooled: A's are dragged up and B's down, by a whole third of the
    ladder, with nothing in the output saying so."""
    pooled = means_of(None)

    assert pooled["a1"] == pytest.approx((1 * 10 / 180 + 2 * 40 / 100) / (10 / 180 + 40 / 100), rel=REL)
    assert pooled["b1"] == pytest.approx((1 * 80 / 180 + 2 * 10 / 100) / (80 / 180 + 10 / 100), rel=REL)
    assert pooled["a1"] > 1.8
    assert pooled["b1"] < 1.2


# ---------------------------------------------------------------------------
# The single-parent run is unchanged.
# ---------------------------------------------------------------------------


def test_one_parent_scores_exactly_as_no_parent_table():
    """The group-by is degenerate with one parent, so a dataset that names its single parent and
    one that names none must agree to the bit."""
    one = {variant: "only" for variant in PARENTS}
    assert means_of(one) == pytest.approx(means_of(None), rel=0)
    assert enrichments_of(one) == pytest.approx(enrichments_of(None), rel=0)


# ---------------------------------------------------------------------------
# Attaching the parent.
# ---------------------------------------------------------------------------


def parents_frame(mapping: dict[str, str]) -> pl.DataFrame:
    keys = sorted(mapping)
    return pl.DataFrame({"variantKey": keys, COL_PARENT_ID: [mapping[key] for key in keys]})


def test_a_variant_the_table_does_not_place_gets_its_own_group():
    """Unplaced variants are not folded into someone else's depths. They are scored among
    themselves, and the manifest reports them under a null parent id."""
    reads = reads_frame(ROWS).drop(COL_PARENT_ID)
    attached = pipeline.attach_parents(reads, parents_frame({"a1": "A", "a2": "A"}))

    by_variant = dict(zip(attached["variantKey"].to_list(), attached[COL_PARENT_ID].to_list()))
    assert by_variant["a1"] == "A"
    assert by_variant["b1"] == ""


def test_no_parents_table_puts_every_row_in_one_group():
    reads = reads_frame(ROWS).drop(COL_PARENT_ID)
    attached = pipeline.attach_parents(reads, None)

    assert attached[COL_PARENT_ID].unique().to_list() == [""]


def test_the_manifest_reports_every_parent_with_what_it_contributed():
    report = pipeline._parent_report(reads_frame(ROWS, parents=PARENTS), {})

    assert [(e["parentId"], e["variants"], e["reads"]) for e in report] == [
        ("A", 2, 200),
        ("B", 2, 280),
    ]


def test_an_unplaced_group_reports_a_null_id():
    report = pipeline._parent_report(reads_frame(ROWS), {})
    assert [entry["parentId"] for entry in report] == [None]


# ---------------------------------------------------------------------------
# Reading the table.
# ---------------------------------------------------------------------------


def test_a_variant_listed_under_two_parents_is_dropped(tmp_path):
    """The aligner assigns a sequence to one parent, so two rows mean two profiler runs reached
    one bundle. Keeping either would scope that variant's depths to a library it is not part
    of, and the choice would be made by row order."""
    path = tmp_path / "parents.tsv"
    pl.DataFrame(
        {"variantKey": ["a1", "a1", "a2"], COL_PARENT_ID: ["A", "B", "A"]}
    ).write_csv(path, separator="\t")

    mapping = io_layer.read_parents(path)

    assert mapping["variantKey"].to_list() == ["a2"]


def test_a_repeated_identical_row_is_not_ambiguous(tmp_path):
    """The linker is distinct per (parent, variant), but a duplicate row names one parent and
    must not cost the variant its placement."""
    path = tmp_path / "parents.tsv"
    pl.DataFrame({"variantKey": ["a1", "a1"], COL_PARENT_ID: ["A", "A"]}).write_csv(
        path, separator="\t"
    )

    mapping = io_layer.read_parents(path)

    assert mapping.to_dicts() == [{"variantKey": "a1", COL_PARENT_ID: "A"}]


def test_an_override_naming_an_absent_column_does_not_rename_a_real_one(tmp_path):
    """`schema_overrides` as a dict is applied BY POSITION when its length happens to equal the
    file's column count, so naming a column the file lacks silently renamed the last real one —
    here `parentId` became the sort-fraction column, all null.

    The reads loader narrows its overrides to columns the file actually has."""
    path = tmp_path / "reads.tsv"
    write_tsv(reads_frame(ROWS), path)

    frame = io_layer.read_reads(path, sort_fraction_column="notInTheFile")

    assert COL_PARENT_ID in frame.columns
    assert "notInTheFile" not in frame.columns


def test_replicates_do_not_smear_one_variant_s_parent_across_the_gate():
    """`pool_replicates` resolves every column it does not know per (condition, gate), so the
    parent must be attached AFTER it. Attached first, one variant's parent is taken as the
    whole gate's and every depth is scoped to the wrong library.

    Two samples for g1, two parents, and each variant must come out under its own.
    """
    first = reads_frame([("g1", "a1", 10), ("g1", "b1", 80)]).drop(COL_PARENT_ID)
    second = reads_frame([("g1", "a1", 10), ("g1", "b1", 80)]).drop(COL_PARENT_ID).with_columns(
        pl.lit("s_second").alias("sampleId")
    )
    pooled, _ = pooling.pool_replicates(pl.concat([first, second]), None, ["pH7"])

    attached = pipeline.attach_parents(pooled, parents_frame({"a1": "A", "b1": "B"}))
    by_variant = dict(zip(attached["variantKey"].to_list(), attached[COL_PARENT_ID].to_list()))

    assert by_variant == {"a1": "A", "b1": "B"}
    # And the reads really were pooled, so this is the post-pooling frame.
    assert attached.filter(pl.col("variantKey") == "a1")["reads"].to_list() == [20]


# ---------------------------------------------------------------------------
# Each parent resolves its own parent row, and each variant references it.
#
# Parent A            Parent B
#   P_A  g1 50 g2 50    P_B  g1 100 g2   0
#   a1   g1  0 g2 100   b1   g1   0 g2 100
#
# A's depths are g1 50, g2 150; B's are g1 100, g2 100. Within A:
#   P_A freq 1.000, 0.333 -> mean (1(1) + 2(1/3)) / (1 + 1/3) = 1.25
#   a1  freq 0.000, 0.667 -> mean 2.00        so binScore a1 = 0.75
# Within B both are pinned to one gate: P_B mean 1.0, b1 mean 2.0, binScore b1 = 1.0.
# ---------------------------------------------------------------------------

REF_ROWS = [
    ("g1", "P_A", 50), ("g2", "P_A", 50), ("g2", "a1", 100),
    ("g1", "P_B", 100), ("g2", "b1", 100),
]
REF_PARENTS = {"P_A": "A", "a1": "A", "P_B": "B", "b1": "B"}


def scopes_and_mapping(counts: dict[str, int]):
    """Build the per-parent scopes the pipeline builds, for `counts` as the variants table."""
    reads = reads_frame(REF_ROWS, parents=REF_PARENTS)
    variants = variants_frame(counts)
    parents = parents_frame(REF_PARENTS)
    scopes = pipeline._parent_scopes(variants, parents, reads, None, params_for())
    return reads, scopes, pipeline._variant_parent(variants, parents)


def params_for():
    from params import Params

    return Params(
        gate_ranks=RANKS, excluded_conditions=[], read_floor=None, sort_fraction_column=None,
        gates_ordered=True, input_gate=None, baseline=None, baseline_sequence=None,
    )


def bin_scores_for(counts: dict[str, int]):
    reads, scopes, mapping = scopes_and_mapping(counts)
    per_gate = scoring.per_gate_frequencies(reads, None)
    scored = scoring.gate_rank_means(per_gate, RANKS)
    frame, mode = scoring.bin_scores(scored, {k: s.parent for k, s in scopes.items()}, mapping)
    values = None if frame is None else dict(
        zip(frame["variantKey"].to_list(), frame["binScore"].to_list())
    )
    return values, mode


def test_each_parent_identifies_its_own_row():
    """Two parents each carry a variant with a mutation count of zero. That is two zeros in the
    table and it is NOT ambiguous — it is one parent row each."""
    _, scopes, _ = scopes_and_mapping({"P_A": 0, "a1": 1, "P_B": 0, "b1": 1})

    assert sorted(scopes) == ["A", "B"]
    assert scopes["A"].parent.identified and scopes["A"].parent.variant_key == "P_A"
    assert scopes["B"].parent.identified and scopes["B"].parent.variant_key == "P_B"


def test_every_variant_is_referenced_to_its_own_parent():
    values, mode = bin_scores_for({"P_A": 0, "a1": 1, "P_B": 0, "b1": 1})

    assert mode == "referenced"
    assert values == pytest.approx({"P_A": 0.0, "a1": 0.75, "P_B": 0.0, "b1": 1.0}, rel=REL)


def test_a_variant_whose_parent_was_not_identified_gets_no_row():
    """B has no zero-count row, so its variants have nothing to reference. They are absent
    rather than carrying the cancelled form, which would put two meanings in one column."""
    values, mode = bin_scores_for({"P_A": 0, "a1": 1, "P_B": 3, "b1": 1})

    assert mode == "referenced"
    assert set(values) == {"P_A", "a1"}
    assert values == pytest.approx({"P_A": 0.0, "a1": 0.75}, rel=REL)


def test_no_parent_identified_falls_back_to_the_cancelled_form():
    """Unchanged from a one-parent run: with nothing to reference anywhere, the column is the
    gate rank mean and the mode says so."""
    values, mode = bin_scores_for({"P_A": 2, "a1": 1, "P_B": 3, "b1": 1})

    assert mode == "cancelled"
    assert set(values) == {"P_A", "a1", "P_B", "b1"}
    assert values["P_A"] == pytest.approx(1.25, rel=REL)


def test_the_header_probe_does_not_infer_types(tmp_path):
    """`read_reads` names the file's columns before choosing overrides. That probe must not
    infer types: a `condition` column holding 5.5 and 7.5 infers as float from the first chunk
    and then refuses the input arm's `NA`, which is the ordinary shape of a real run.

    Sized past the inference window on purpose — a short file sees the `NA` while inferring and
    passes either way.
    """
    path = tmp_path / "reads.tsv"
    lines = ["sampleId\tvariantKey\treads\tcondition\tgate"]
    lines += [f"s_num\tv{i}\t{i}\t5.5\tg1" for i in range(3000)]
    lines += [f"s_na\tw{i}\t{i}\tNA\tin" for i in range(100)]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    frame = io_layer.read_reads(path, sort_fraction_column=None)

    assert frame["condition"].dtype == pl.String
    assert set(frame["condition"].unique().to_list()) == {"5.5", "NA"}


# ---------------------------------------------------------------------------
# The same reference at protein grain.
# ---------------------------------------------------------------------------


def test_the_parent_is_re_keyed_onto_its_own_protein():
    """The parent is found as a nucleotide variant. Pooled to protein grain its score lives
    under its protein key, so the reference has to be named the same way."""
    _, scopes, _ = scopes_and_mapping({"P_A": 0, "a1": 1, "P_B": 0, "b1": 1})
    proteins = pl.DataFrame(
        {"variantKey": ["P_A", "a1", "P_B", "b1"], "proteinKey": ["pA", "pA", "pB", "pB"]}
    )

    at_protein = pipeline._parents_at_protein_grain(scopes, proteins)

    assert at_protein["A"].variant_key == "pA"
    assert at_protein["B"].variant_key == "pB"
    assert at_protein["A"].identified and at_protein["B"].identified


def test_a_parent_the_linker_does_not_place_is_unidentified_at_protein_grain():
    """It has no protein to reference, so its proteins get no row — the same rule the
    nucleotide level uses for a parent that was never found."""
    _, scopes, _ = scopes_and_mapping({"P_A": 0, "a1": 1, "P_B": 0, "b1": 1})
    partial = pl.DataFrame({"variantKey": ["P_A", "a1"], "proteinKey": ["pA", "pA"]})

    at_protein = pipeline._parents_at_protein_grain(scopes, partial)

    assert at_protein["A"].identified is True
    assert at_protein["B"].identified is False
    assert at_protein["B"].variant_key is None
