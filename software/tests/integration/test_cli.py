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
    reads_frame,
    variants_frame,
    write_params,
    write_tsv,
)

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
    """`single-condition-run`: both quantities, with the run's single condition on each
    column exactly as a two-condition run would carry two. No placeholder, no special case."""
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
    """`condition-source` bars relabelling, and the value lands in a domain key a consumer
    matches on. A trailing zero must survive: type inference would render `7.50` back as
    `7.5` and the domain value would then match nothing in the source metadata column."""
    reads = pl.concat([reads_frame(BASE_ROWS, condition="7.50"), reads_frame(BASE_ROWS, condition="7.5")])

    code, _, manifest = invoke(tmp_path, reads, variants_frame(BASE_MUTATION_COUNTS))

    assert code == 0
    assert sorted(entry["condition"] for entry in manifest["conditions"]) == ["7.5", "7.50"]


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
    # Diagnostics go to stdout — the workflow layer does not capture stderr.
    assert "REFUSED" in capsys.readouterr().out


def test_replicate_samples_exit_non_zero_and_write_nothing(tmp_path, capsys):
    reads = pl.concat(
        [
            reads_frame(BASE_ROWS),
            pl.DataFrame(
                {
                    "sampleId": ["replicate"],
                    "variantKey": ["P"],
                    "reads": [5],
                    "condition": ["pH7"],
                    "gate": ["g1"],
                },
                schema_overrides={"reads": pl.Int64},
            ),
        ]
    )
    code, out_dir, manifest = invoke(tmp_path, reads, variants_frame(BASE_MUTATION_COUNTS))

    assert code == 1
    assert manifest is None
    assert not out_dir.exists()
    assert "replicate" in capsys.readouterr().out


def test_sort_fraction_column_missing_from_the_reads_table_fails(tmp_path, capsys):
    code, out_dir, _ = invoke(
        tmp_path, reads_frame(BASE_ROWS), variants_frame(BASE_MUTATION_COUNTS), sort_fraction_column="absent"
    )

    assert code == 1
    assert not out_dir.exists()
    assert "absent" in capsys.readouterr().out


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
