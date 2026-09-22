"""The entrypoint end to end: files on disk and the manifest that names them.

The manifest is the only thing the caller reads to know what to construct, so these tests
assert its fields rather than just that the run exited zero.
"""

from __future__ import annotations

import json

import polars as pl
import pytest
from conftest import (
    BASE_MEANS,
    BASE_MUTATION_COUNTS,
    BASE_ROWS,
    INPUT_GATE,
    SYNONYMOUS_BASELINE_LEVEL,
    SYNONYMOUS_BASELINE_SPREAD,
    SYNONYMOUS_ENRICHMENTS,
    SYNONYMOUS_GATE_RANKS,
    SYNONYMOUS_GATE_ROWS,
    SYNONYMOUS_INPUT_ROWS,
    SYNONYMOUS_MUTATION_COUNTS,
    SYNONYMOUS_ROWS,
    SYNONYMOUS_SEQUENCES,
    reads_frame,
    replicate_frame,
    variants_frame,
    write_params,
    write_tsv,
)

from constants import BASELINE_SYNONYMOUS, RUN_MODE_ENRICHMENT
from main import main

REL = 1e-12


def invoke(tmp_path, reads, variants=None, **param_kwargs):
    """Run the entrypoint the way the workflow does and return (exit code, out_dir, manifest)."""
    # Tests that invoke twice pass a subdirectory, so that the two runs cannot share files.
    tmp_path.mkdir(parents=True, exist_ok=True)
    reads_path = write_tsv(reads, tmp_path / "reads.tsv")
    params_path = write_params(tmp_path / "params.json", **param_kwargs)
    out_dir = tmp_path / "out"

    argv = ["--reads", str(reads_path), "--params", str(params_path), "--out-dir", str(out_dir)]
    if variants is not None:
        argv += ["--variants", str(write_tsv(variants, tmp_path / "variants.tsv"))]

    code = main(argv)
    manifest_path = out_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else None
    return code, out_dir, manifest


def read_scores(out_dir, name, column):
    frame = pl.read_csv(out_dir / name, separator="\t", schema_overrides={"variantKey": pl.String})
    return dict(zip(frame["variantKey"].to_list(), frame[column].to_list(), strict=True))


# ---------------------------------------------------------------------------
# One condition is an ordinary run.
# ---------------------------------------------------------------------------


def test_one_condition_emits_both_quantities(tmp_path):
    """A one-condition run carries its condition on each column exactly as a two-condition run
    carries two. No placeholder, no special case."""
    code, out_dir, manifest = invoke(tmp_path, reads_frame(BASE_ROWS), variants_frame(BASE_MUTATION_COUNTS))

    assert code == 0
    assert manifest["parentIdentified"] is True
    assert manifest["parentAbsenceReason"] is None
    assert len(manifest["conditions"]) == 1

    entry = manifest["conditions"][0]
    assert entry["condition"] == "pH7"
    assert entry["referenceMode"] == "referenced"
    assert entry["sortYieldCorrected"] is False
    assert entry["sortFractionSum"] is None
    assert entry["variantsScored"] == 4
    # Fewer variants than the display cut, so the view draws all of them and says so.
    assert entry["variantsPlotted"] == 4

    assert read_scores(out_dir, entry["gateRankMeanFile"], "gateRankMean") == pytest.approx(BASE_MEANS, rel=REL)
    bin_scores = read_scores(out_dir, entry["binScoreFile"], "binScore")
    assert bin_scores["P"] == pytest.approx(0.0, abs=1e-12)
    assert bin_scores["A"] == pytest.approx(1.9 - 2.6, rel=REL)


def test_gates_collected_reports_pre_floor_depths(tmp_path):
    """The depths are the number needed to choose a floor at all, so they are taken before it
    — a floor of 10 excludes C but must not shrink any gate's reported depth."""
    code, _, manifest = invoke(
        tmp_path, reads_frame(BASE_ROWS), variants_frame(BASE_MUTATION_COUNTS), read_floor=10
    )

    assert code == 0
    entry = manifest["conditions"][0]
    assert entry["variantsScored"] == 3
    assert entry["gatesCollected"] == [
        {"gate": "g1", "depth": 100},
        {"gate": "g2", "depth": 100},
        {"gate": "g3", "depth": 100},
    ]


def test_gates_collected_is_ordered_by_declared_rank(tmp_path):
    """So the run summary reads along the binding axis rather than alphabetically."""
    _, _, manifest = invoke(
        tmp_path,
        reads_frame(BASE_ROWS),
        variants_frame(BASE_MUTATION_COUNTS),
        gate_ranks={"g1": 3, "g2": 2, "g3": 1},
    )
    assert [gate["gate"] for gate in manifest["conditions"][0]["gatesCollected"]] == ["g3", "g2", "g1"]


# ---------------------------------------------------------------------------
# Two conditions, scored independently.
# ---------------------------------------------------------------------------


def two_condition_reads():
    return pl.concat([reads_frame(BASE_ROWS, condition="pH7"), reads_frame(BASE_ROWS, condition="pH5")])


def test_two_conditions_each_get_their_own_files(tmp_path):
    code, out_dir, manifest = invoke(tmp_path, two_condition_reads(), variants_frame(BASE_MUTATION_COUNTS))

    assert code == 0
    assert [entry["condition"] for entry in manifest["conditions"]] == ["pH5", "pH7"]

    names = {entry["gateRankMeanFile"] for entry in manifest["conditions"]}
    assert len(names) == 2
    for entry in manifest["conditions"]:
        assert (out_dir / entry["gateRankMeanFile"]).exists()
        assert (out_dir / entry["binScoreFile"]).exists()
        assert (out_dir / entry["readDistributionFile"]).exists()
        # Identical reads at both arms, so identical scores — the conditions are scored
        # independently and nothing pairs or relates them.
        assert read_scores(out_dir, entry["gateRankMeanFile"], "gateRankMean") == pytest.approx(BASE_MEANS, rel=REL)


def test_excluded_condition_yields_no_output_at_all(tmp_path):
    """An excluded value yields no per-condition output, rather than an empty one."""
    code, _, manifest = invoke(
        tmp_path, two_condition_reads(), variants_frame(BASE_MUTATION_COUNTS), excluded=["pH5"]
    )

    assert code == 0
    assert [entry["condition"] for entry in manifest["conditions"]] == ["pH7"]


def test_condition_value_is_emitted_verbatim(tmp_path):
    """The value lands in a domain key a consumer matches on, so a trailing zero must survive:
    type inference renders `7.50` back as `7.5`, matching nothing in the source column."""
    reads = pl.concat([reads_frame(BASE_ROWS, condition="7.50"), reads_frame(BASE_ROWS, condition="7.5")])

    code, _, manifest = invoke(tmp_path, reads, variants_frame(BASE_MUTATION_COUNTS))

    assert code == 0
    assert sorted(entry["condition"] for entry in manifest["conditions"]) == ["7.5", "7.50"]


# The gate ladder is a selection: a gate-column value absent from `gateRanks` takes no part.
# Real runs routinely carry non-rung values (input, specificity, stability arms).


# One extra gate, deliberately the heaviest thing in the table: an unsorted input sample
# with a depth that dwarfs every real gate and a variant spread that inverts the ladder.
# If any of it reached the arithmetic, no score below would survive.
INPUT_GATE_ROWS = [
    ("input", "P", 1),
    ("input", "A", 999),
    ("input", "B", 1000),
    ("input", "C", 1000),
]


def test_an_unselected_gate_changes_no_score(tmp_path):
    """The same reads with and without an unranked gate score identically. Depths are per
    gate, so what an unselected gate would move is the weighted mean, not the frequencies."""
    code, out_dir, manifest = invoke(
        tmp_path,
        reads_frame(BASE_ROWS + INPUT_GATE_ROWS),
        variants_frame(BASE_MUTATION_COUNTS),
    )

    assert code == 0
    entry = manifest["conditions"][0]
    assert read_scores(out_dir, entry["gateRankMeanFile"], "gateRankMean") == pytest.approx(BASE_MEANS, rel=REL)
    # And the run summary reads as the ladder actually used — no rung with a depth of 3000
    # sitting beside the real gates.
    assert entry["gatesCollected"] == [
        {"gate": "g1", "depth": 100},
        {"gate": "g2", "depth": 100},
        {"gate": "g3", "depth": 100},
    ]


def test_a_narrowed_ladder_ranks_contiguously_from_one(tmp_path):
    """Selecting g1 and g2 makes them ranks 1 and 2; g3's reads leave the arithmetic entirely.

    Hand-computed on the base table, where every gate's depth is 100:

        P: freq .10 .20   den .30   num 1(.10)+2(.20) = .50   mean .50/.30
        A: freq .30 .50   den .80   num 1(.30)+2(.50) = 1.30  mean 1.30/.80 = 1.625
        B: freq .59 .29   den .88   num 1(.59)+2(.29) = 1.17  mean 1.17/.88
        C: freq .01 .01   den .02   num 1(.01)+2(.01) = .03   mean 1.5

    Every mean falls in [1, 2] — the range of the ladder the run declared, not of the column.
    """
    code, out_dir, manifest = invoke(
        tmp_path,
        reads_frame(BASE_ROWS),
        variants_frame(BASE_MUTATION_COUNTS),
        gate_ranks={"g1": 1, "g2": 2},
    )

    assert code == 0
    entry = manifest["conditions"][0]
    assert entry["gatesCollected"] == [{"gate": "g1", "depth": 100}, {"gate": "g2", "depth": 100}]
    assert read_scores(out_dir, entry["gateRankMeanFile"], "gateRankMean") == pytest.approx(
        {"P": 0.50 / 0.30, "A": 1.625, "B": 1.17 / 0.88, "C": 1.5}, rel=REL
    )


def test_a_condition_with_no_selected_gate_drops_out_of_the_run(tmp_path):
    """Scoped out as an excluded value is, not scored to an empty file. The real shape: the
    input sample carries no pH, so it gets a condition of its own with nothing to score."""
    reads = pl.concat(
        [
            reads_frame(BASE_ROWS, condition="pH7"),
            reads_frame(INPUT_GATE_ROWS, condition="NA"),
        ]
    )
    code, _, manifest = invoke(tmp_path, reads, variants_frame(BASE_MUTATION_COUNTS))

    assert code == 0
    assert [entry["condition"] for entry in manifest["conditions"]] == ["pH7"]


def test_sort_fractions_of_an_unselected_gate_are_neither_required_nor_summed(tmp_path):
    """An unselected gate's fraction is not part of the sum, and a null on it is not missing.
    Summed in, the 0.6 below over-sums the condition; demanded, the null refuses the run."""
    reads = reads_frame(BASE_ROWS + INPUT_GATE_ROWS).with_columns(
        pl.col("gate")
        .replace_strict({"g1": 0.5, "g2": 0.3, "g3": 0.2, "input": None}, return_dtype=pl.Float64)
        .alias("sortFraction")
    )
    code, out_dir, manifest = invoke(
        tmp_path, reads, variants_frame(BASE_MUTATION_COUNTS), sort_fraction_column="sortFraction"
    )

    assert code == 0
    entry = manifest["conditions"][0]
    assert entry["sortYieldCorrected"] is True
    assert entry["sortFractionSum"] == pytest.approx(1.0, rel=REL)
    # The corrected score of the selected ladder, unchanged by the unselected gate.
    assert read_scores(out_dir, entry["gateRankMeanFile"], "gateRankMean")["P"] == pytest.approx(2.36, rel=REL)


def test_replicates_in_an_unselected_gate_do_not_fail_the_run(tmp_path):
    """The one-sample-per-group rule is about the groups the run has. Two samples sharing a
    gate nobody ranked are not a group of this run, and refusing on them would block a
    project whose input or NSB arm was simply sequenced twice."""
    reads = pl.concat(
        [
            reads_frame(BASE_ROWS + INPUT_GATE_ROWS),
            pl.DataFrame(
                {
                    "sampleId": ["input_replicate"],
                    "variantKey": ["P"],
                    "reads": [5],
                    "condition": ["pH7"],
                    "gate": ["input"],
                },
                schema_overrides={"reads": pl.Int64},
            ),
        ]
    )
    code, out_dir, manifest = invoke(tmp_path, reads, variants_frame(BASE_MUTATION_COUNTS))

    assert code == 0
    assert read_scores(out_dir, manifest["conditions"][0]["gateRankMeanFile"], "gateRankMean") == pytest.approx(
        BASE_MEANS, rel=REL
    )


# ---------------------------------------------------------------------------
# The three states of binScore.
# ---------------------------------------------------------------------------


def test_no_variants_table_produces_bin_score_at_no_condition(tmp_path):
    code, out_dir, manifest = invoke(tmp_path, two_condition_reads(), variants=None)

    assert code == 0
    assert manifest["parentIdentified"] is False
    assert manifest["parentAbsenceReason"] is None
    for entry in manifest["conditions"]:
        assert entry["binScoreFile"] is None
        assert entry["referenceMode"] is None
        # gateRankMean is unaffected.
        assert (out_dir / entry["gateRankMeanFile"]).exists()


def test_cancelled_mode_still_emits_bin_score(tmp_path):
    """Numerically identical to gateRankMean; the mode in the domain is what tells a consumer
    which situation it is reading, and the two columns remain distinct addresses."""
    code, out_dir, manifest = invoke(
        tmp_path, reads_frame(BASE_ROWS), variants_frame({"P": 4, "A": 1, "B": 2, "C": 3})
    )

    assert code == 0
    assert manifest["parentAbsenceReason"] == "no-variant-with-zero-mutation-count"
    entry = manifest["conditions"][0]
    assert entry["referenceMode"] == "cancelled"
    assert read_scores(out_dir, entry["binScoreFile"], "binScore") == pytest.approx(BASE_MEANS, rel=REL)


def test_bin_score_column_absent_where_the_parent_went_unscored(tmp_path):
    """Clause 5, and the file is absent rather than present-and-empty: a present column with
    no keys would claim every variant was unscorable here."""
    rows = [
        ("g1", "P", 1),
        ("g1", "A", 40),
        ("g1", "B", 59),
        ("g2", "P", 1),
        ("g2", "A", 60),
        ("g2", "B", 39),
    ]
    code, out_dir, manifest = invoke(
        tmp_path,
        reads_frame(rows),
        variants_frame({"P": 0, "A": 1, "B": 2}),
        gate_ranks={"g1": 1, "g2": 2},
        read_floor=10,
    )

    assert code == 0
    entry = manifest["conditions"][0]
    assert entry["binScoreFile"] is None
    assert entry["referenceMode"] is None
    # And it did not silently fall back to the cancelled form.
    assert manifest["parentIdentified"] is True
    assert set(read_scores(out_dir, entry["gateRankMeanFile"], "gateRankMean")) == {"A", "B"}


# ---------------------------------------------------------------------------
# The sort-yield correction, reported as applied.
# ---------------------------------------------------------------------------


def test_correction_is_reported_as_applied_with_its_fraction_sum(tmp_path):
    reads = reads_frame(BASE_ROWS, fractions={"g1": 0.5, "g2": 0.3, "g3": 0.2})
    code, out_dir, manifest = invoke(
        tmp_path, reads, variants_frame(BASE_MUTATION_COUNTS), sort_fraction_column="sortFraction"
    )

    assert code == 0
    entry = manifest["conditions"][0]
    assert entry["sortYieldCorrected"] is True
    assert entry["sortFractionSum"] == pytest.approx(1.0, rel=REL)
    # Adams eq. A3 reweighting actually happened.
    assert read_scores(out_dir, entry["gateRankMeanFile"], "gateRankMean")["P"] == pytest.approx(2.36, rel=REL)


def test_two_runs_two_modes_are_distinguishable(tmp_path):
    """`correction-mode-parity`: a single run satisfies "declares its mode" trivially, so the
    pair is the assertion."""
    reads = reads_frame(BASE_ROWS, fractions={"g1": 0.5, "g2": 0.3, "g3": 0.2})

    _, _, uncorrected = invoke(tmp_path / "a", reads, variants_frame(BASE_MUTATION_COUNTS))
    _, _, corrected = invoke(
        tmp_path / "b", reads, variants_frame(BASE_MUTATION_COUNTS), sort_fraction_column="sortFraction"
    )

    assert uncorrected["conditions"][0]["sortYieldCorrected"] is False
    assert corrected["conditions"][0]["sortYieldCorrected"] is True
    assert uncorrected["conditions"][0]["sortFractionSum"] is None
    assert corrected["conditions"][0]["sortFractionSum"] == pytest.approx(1.0, rel=REL)


# ---------------------------------------------------------------------------
# The refusals: exit non-zero, name the values, write no file.
# ---------------------------------------------------------------------------


def test_over_summing_fractions_exits_non_zero_and_writes_nothing(tmp_path, capsys):
    reads = reads_frame(BASE_ROWS, fractions={"g1": 0.5, "g2": 0.5, "g3": 0.5})
    code, out_dir, manifest = invoke(
        tmp_path, reads, variants_frame(BASE_MUTATION_COUNTS), sort_fraction_column="sortFraction"
    )

    assert code == 1
    assert manifest is None
    assert not out_dir.exists()
    # Both streams, and both are pinned. Stdout is the run's record; stderr is the only
    # stream the platform quotes back in the error it shows the user, so a refusal that
    # reaches stdout alone is reported as a blank non-zero exit.
    captured = capsys.readouterr()
    assert "REFUSED" in captured.out
    assert "REFUSED" in captured.err


def test_a_run_with_no_replicates_reports_no_pooling(tmp_path):
    """The empty list is the statement: one sample per gate."""
    _, _, manifest = invoke(tmp_path, reads_frame(BASE_ROWS), variants_frame(BASE_MUTATION_COUNTS))

    assert manifest["pooledGroups"] == []


def test_replicate_samples_are_pooled_and_the_pooling_is_reported(tmp_path, capsys):
    """g1 is replicated with its own read counts, so its depth doubles (100 -> 200) along with
    every read count in it — leaving every frequency and every weighted mean unchanged.
    """
    g1_rows = [row for row in BASE_ROWS if row[0] == "g1"]
    reads = pl.concat([reads_frame(BASE_ROWS), replicate_frame(g1_rows, "replicate_of_g1")])

    code, out_dir, manifest = invoke(tmp_path, reads, variants_frame(BASE_MUTATION_COUNTS))

    assert code == 0
    assert manifest["pooledGroups"] == [
        {"condition": "pH7", "gate": "g1", "samples": ["replicate_of_g1", "s_pH7_g1"]}
    ]

    entry = manifest["conditions"][0]
    # The pooled depth: the number the arithmetic used, which is what a read floor is set against.
    depths = {gate["gate"]: gate["depth"] for gate in entry["gatesCollected"]}
    assert depths == {"g1": 200, "g2": 100, "g3": 100}
    assert read_scores(out_dir, entry["gateRankMeanFile"], "gateRankMean") == pytest.approx(BASE_MEANS, rel=REL)

    captured = capsys.readouterr()
    assert "Pooled condition 'pH7' gate 'g1'" in captured.out
    assert "replicate_of_g1" in captured.out


def test_replicates_disagreeing_on_the_sort_fraction_warn_rather_than_refuse(tmp_path, capsys):
    """0.5 and 0.3 average to 0.4, so the condition sums to 0.9 and the run proceeds."""
    fractions = {"g1": 0.5, "g2": 0.3, "g3": 0.2}
    g1_rows = [row for row in BASE_ROWS if row[0] == "g1"]
    reads = pl.concat(
        [
            reads_frame(BASE_ROWS, fractions=fractions),
            replicate_frame(g1_rows, "replicate_of_g1", fractions={**fractions, "g1": 0.3}),
        ]
    )

    code, _, manifest = invoke(
        tmp_path, reads, variants_frame(BASE_MUTATION_COUNTS), sort_fraction_column="sortFraction"
    )

    assert code == 0
    assert manifest["pooledGroups"][0]["sortFractionsDiffer"] is True
    assert manifest["conditions"][0]["sortFractionSum"] == pytest.approx(0.9, rel=REL)
    assert "different sort fractions" in capsys.readouterr().out


def test_excluded_conditions_are_not_reported_as_pooled(tmp_path):
    """A factor column with three values, one selected: only that one's groups are the run's."""
    g1_rows = [row for row in BASE_ROWS if row[0] == "g1"]
    reads = pl.concat(
        [
            reads_frame(BASE_ROWS, condition=condition)
            for condition in ("specificity", "affinity", "polyspecificity")
        ]
        + [
            replicate_frame(g1_rows, f"rep_{condition}", condition=condition)
            for condition in ("specificity", "affinity", "polyspecificity")
        ]
    )

    code, _, manifest = invoke(
        tmp_path,
        reads,
        variants_frame(BASE_MUTATION_COUNTS),
        excluded=["affinity", "polyspecificity"],
    )

    assert code == 0
    assert [entry["condition"] for entry in manifest["conditions"]] == ["specificity"]
    assert [entry["condition"] for entry in manifest["pooledGroups"]] == ["specificity"]


def test_a_replicate_in_an_unselected_gate_is_not_pooled(tmp_path):
    """A gate the run does not rank is dropped whole, replicate included, rather than merged."""
    reads = pl.concat(
        [
            reads_frame(BASE_ROWS),
            reads_frame([("unsorted", "P", 40)]),
            replicate_frame([("unsorted", "P", 40)], "replicate_of_unsorted"),
        ]
    )

    code, _, manifest = invoke(tmp_path, reads, variants_frame(BASE_MUTATION_COUNTS))

    assert code == 0
    assert manifest["pooledGroups"] == []
    assert [gate["gate"] for gate in manifest["conditions"][0]["gatesCollected"]] == ["g1", "g2", "g3"]


def test_sort_fraction_column_missing_from_the_reads_table_fails(tmp_path, capsys):
    code, out_dir, _ = invoke(
        tmp_path, reads_frame(BASE_ROWS), variants_frame(BASE_MUTATION_COUNTS), sort_fraction_column="absent"
    )

    assert code == 1
    assert not out_dir.exists()
    captured = capsys.readouterr()
    assert "absent" in captured.out
    assert "absent" in captured.err


# ---------------------------------------------------------------------------
# Determinism — the workflow's pure-template dedup depends on it.
# ---------------------------------------------------------------------------


def test_two_runs_of_the_same_inputs_produce_identical_bytes(tmp_path):
    reads = two_condition_reads()
    variants = variants_frame(BASE_MUTATION_COUNTS)

    _, first, _ = invoke(tmp_path / "one", reads, variants)
    _, second, _ = invoke(tmp_path / "two", reads, variants)

    first_files = sorted(path.name for path in first.iterdir())
    assert first_files == sorted(path.name for path in second.iterdir())
    for name in first_files:
        assert (first / name).read_bytes() == (second / name).read_bytes()


# ---------------------------------------------------------------------------
# Enrichment mode, end to end.
# ---------------------------------------------------------------------------


def test_enrichment_run_emits_one_file_per_gate_with_its_baseline(tmp_path):
    """The whole Stage 1 + 3a path: an input that is not a rung, one enrichment file per
    collected gate, and a per-gate baseline over the synonymous variants."""
    code, out_dir, manifest = invoke(
        tmp_path,
        reads_frame(SYNONYMOUS_ROWS),
        variants_frame(SYNONYMOUS_MUTATION_COUNTS, SYNONYMOUS_SEQUENCES),
        gate_ranks=SYNONYMOUS_GATE_RANKS,
        mode=RUN_MODE_ENRICHMENT,
        input_gate=INPUT_GATE,
        baseline=BASELINE_SYNONYMOUS,
    )

    assert code == 0
    assert manifest["mode"] == RUN_MODE_ENRICHMENT
    assert manifest["baselineOption"] == BASELINE_SYNONYMOUS
    assert manifest["baselineIdentified"] is True
    assert manifest["baselineVariants"] == 5

    entry = manifest["conditions"][0]
    # The reference's own depth, reported for the same reason the rungs' depths are.
    assert entry["inputDepth"] == 1000
    assert len(entry["gateEnrichments"]) == 1

    gate = entry["gateEnrichments"][0]
    assert gate["gate"] == "g1"
    assert gate["rank"] == 1
    assert gate["variantsEnriched"] == 7

    assert gate["baseline"]["level"] == pytest.approx(SYNONYMOUS_BASELINE_LEVEL, rel=REL)
    assert gate["baseline"]["spread"] == pytest.approx(SYNONYMOUS_BASELINE_SPREAD, rel=REL)
    assert gate["baseline"]["variants"] == 5

    values = read_scores(out_dir, gate["file"], "gateEnrichment")
    assert values == pytest.approx(SYNONYMOUS_ENRICHMENTS, rel=REL)


def test_the_enrichment_file_carries_both_read_counts(tmp_path):
    _, out_dir, manifest = invoke(
        tmp_path,
        reads_frame(SYNONYMOUS_ROWS),
        variants_frame(SYNONYMOUS_MUTATION_COUNTS, SYNONYMOUS_SEQUENCES),
        gate_ranks=SYNONYMOUS_GATE_RANKS,
        mode=RUN_MODE_ENRICHMENT,
        input_gate=INPUT_GATE,
        baseline=BASELINE_SYNONYMOUS,
    )

    name = manifest["conditions"][0]["gateEnrichments"][0]["file"]
    frame = pl.read_csv(out_dir / name, separator="\t", schema_overrides={"variantKey": pl.String})

    assert frame.columns == ["variantKey", "gateEnrichment", "gateReads", "inputReads"]
    row = frame.filter(pl.col("variantKey") == "W5").to_dicts()[0]
    assert (row["gateReads"], row["inputReads"]) == (200, 100)


def test_enrichment_mode_does_not_emit_bin_score(tmp_path):
    """Open decision 3. The baseline references the enrichment scale; binScore referencing
    the parent on the rank scale would be a second, disagreeing reference on one run."""
    _, _, manifest = invoke(
        tmp_path,
        reads_frame(SYNONYMOUS_ROWS),
        variants_frame(SYNONYMOUS_MUTATION_COUNTS, SYNONYMOUS_SEQUENCES),
        gate_ranks=SYNONYMOUS_GATE_RANKS,
        mode=RUN_MODE_ENRICHMENT,
        input_gate=INPUT_GATE,
        baseline=BASELINE_SYNONYMOUS,
    )

    entry = manifest["conditions"][0]
    assert entry["binScoreFile"] is None
    assert entry["referenceMode"] is None
    # Open decision 1: the rank still runs alongside, so the run is not made poorer.
    assert entry["gateRankMeanFile"] is not None


def test_the_input_is_not_reported_as_a_collected_gate(tmp_path):
    """It is in scope so its frequencies can be computed, and is not a rung on the ladder —
    so the run summary reads as the ladder the run actually used."""
    _, _, manifest = invoke(
        tmp_path,
        reads_frame(SYNONYMOUS_ROWS),
        variants_frame(SYNONYMOUS_MUTATION_COUNTS, SYNONYMOUS_SEQUENCES),
        gate_ranks=SYNONYMOUS_GATE_RANKS,
        mode=RUN_MODE_ENRICHMENT,
        input_gate=INPUT_GATE,
        baseline=BASELINE_SYNONYMOUS,
    )

    gates = [gate["gate"] for gate in manifest["conditions"][0]["gatesCollected"]]
    assert gates == ["g1"]


def test_a_condition_whose_input_collected_nothing_still_scores_its_rank(tmp_path):
    """No reference means no enrichment, and says so with a depth of 0 — but the ladder is
    unaffected, so the gate-rank mean is still produced."""
    rows = SYNONYMOUS_GATE_ROWS + [(INPUT_GATE, variant, 0) for _, variant, _ in SYNONYMOUS_INPUT_ROWS]
    _, _, manifest = invoke(
        tmp_path,
        reads_frame(rows),
        variants_frame(SYNONYMOUS_MUTATION_COUNTS, SYNONYMOUS_SEQUENCES),
        gate_ranks=SYNONYMOUS_GATE_RANKS,
        mode=RUN_MODE_ENRICHMENT,
        input_gate=INPUT_GATE,
        baseline=BASELINE_SYNONYMOUS,
    )

    entry = manifest["conditions"][0]
    assert entry["inputDepth"] == 0
    assert entry["gateEnrichments"] == []
    assert entry["gateRankMeanFile"] is not None


def test_gate_ranking_mode_reports_no_enrichment_fields(tmp_path):
    """The default run is untouched: null input depth, no gate entries, binScore as before."""
    _, _, manifest = invoke(tmp_path, reads_frame(BASE_ROWS), variants_frame(BASE_MUTATION_COUNTS))

    entry = manifest["conditions"][0]
    assert manifest["mode"] == "gate-ranking"
    assert manifest["baselineOption"] is None
    assert entry["inputDepth"] is None
    assert entry["gateEnrichments"] == []
    assert entry["binScoreFile"] is not None


def test_an_input_collected_twice_is_pooled_like_any_other_gate(tmp_path):
    """Two input samples, each with half the reads. Pooling groups on (condition, gate) and
    never looks up a rank, so the reference sums like any rung's replicates. Left unpooled,
    each half is its own depth and every denominator is wrong while looking ordinary."""
    halves = [(gate, variant, reads // 2) for gate, variant, reads in SYNONYMOUS_INPUT_ROWS]
    reads = pl.concat(
        [
            reads_frame(SYNONYMOUS_GATE_ROWS + halves),
            replicate_frame(halves, sample="s_input_replicate"),
        ]
    )

    code, out_dir, manifest = invoke(
        tmp_path,
        reads,
        variants_frame(SYNONYMOUS_MUTATION_COUNTS, SYNONYMOUS_SEQUENCES),
        gate_ranks=SYNONYMOUS_GATE_RANKS,
        mode=RUN_MODE_ENRICHMENT,
        input_gate=INPUT_GATE,
        baseline=BASELINE_SYNONYMOUS,
    )

    assert code == 0
    assert [group["gate"] for group in manifest["pooledGroups"]] == [INPUT_GATE]

    entry = manifest["conditions"][0]
    assert entry["inputDepth"] == 1000
    gate = entry["gateEnrichments"][0]
    assert read_scores(out_dir, gate["file"], "gateEnrichment") == pytest.approx(
        SYNONYMOUS_ENRICHMENTS, rel=REL
    )
    assert gate["baseline"]["level"] == pytest.approx(SYNONYMOUS_BASELINE_LEVEL, rel=REL)
