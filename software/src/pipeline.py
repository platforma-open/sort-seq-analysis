"""One run: refuse what must be refused, score each condition independently, write the manifest.

Two structural properties, both required rather than incidental:

**Conditions are never paired, ordered or related.** Each is scored on its own
(`single-condition-run`). A one-condition run is an ordinary run and takes no distinct
code path — it is the same loop over one element, with the run's single condition on each
column exactly as a two-condition run would carry two. There is no placeholder condition
and no special case.

**The manifest is the whole of what the caller learns.** Whether `binScore` is produced at
a condition, in which reference mode, and whether the correction was applied are held only
here — the caller cannot re-derive them, and `workflow-structure` forbids it from trying.
So every value the workflow will declare on a column is reported by this file, taken from
where the decision was actually made.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import scoring
from constants import (
    COL_CONDITION,
    COL_GATE,
    COL_READS,
    COL_VARIANT,
    DISTRIBUTION_TOP_N,
    OUT_BIN_SCORE,
    OUT_GATE_RANK_MEAN,
)
from io_layer import distribution_file_name, score_file_name, write_manifest, write_table
from params import Params
from validate import check_one_sample_per_group, check_sort_fractions


def run(reads: pl.DataFrame, variants: pl.DataFrame | None, params: Params, out_dir: Path) -> dict:
    """Score every retained condition and write every file. Returns the manifest."""
    retained = retained_conditions(reads, params)

    # Both refusals run over the whole run before anything is written, so a failure leaves
    # nothing partial behind.
    check_one_sample_per_group(reads, retained)
    if params.sort_fraction_column is not None:
        check_sort_fractions(reads, params.sort_fraction_column, retained)

    parent = scoring.resolve_parent(variants)

    out_dir.mkdir(parents=True, exist_ok=True)

    conditions = [
        _score_one_condition(reads, params, parent, condition, index, out_dir)
        for index, condition in enumerate(retained)
    ]

    manifest = {
        "parentIdentified": parent.identified,
        # Null where there was no mutation-count table at all: the two reasons below are
        # for a table that exists and does not identify a single parent.
        "parentAbsenceReason": parent.absence_reason,
        "conditions": conditions,
    }
    write_manifest(manifest, out_dir)
    return manifest


def retained_conditions(reads: pl.DataFrame, params: Params) -> list[str]:
    """The condition column's own distinct values, minus the excluded ones, sorted.

    The values are the column's, never a set the caller typed: a typo then becomes a value
    matching no sample rather than a silent second condition.

    Sorting is not an ordering claim — conditions carry none (`condition-source`), and
    nothing this block emits depends on their order. It is here because the sort makes each
    condition's file index deterministic, which the workflow's pure-template dedup needs.
    """
    values = reads[COL_CONDITION].unique().drop_nulls().to_list()
    return sorted(value for value in values if value not in params.excluded_conditions)


def _score_one_condition(
    reads: pl.DataFrame,
    params: Params,
    parent: scoring.Parent,
    condition: str,
    index: int,
    out_dir: Path,
) -> dict:
    slice_c = reads.filter(pl.col(COL_CONDITION) == condition)

    per_gate = scoring.per_gate_frequencies(slice_c, params.sort_fraction_column)
    means = scoring.gate_rank_means(per_gate, params.gate_ranks)
    scored = scoring.apply_read_floor(means, params.read_floor)

    gate_rank_mean_file = write_table(
        scored.select(COL_VARIANT, OUT_GATE_RANK_MEAN),
        out_dir,
        score_file_name(OUT_GATE_RANK_MEAN, index),
    )

    bin_score = scoring.bin_scores(scored, parent)
    if bin_score is None:
        # The column is absent at this condition, not present-and-empty. A present column
        # with no keys would claim every variant was unscorable here.
        bin_score_file = None
        reference_mode = None
    else:
        bin_score_file = write_table(bin_score, out_dir, score_file_name(OUT_BIN_SCORE, index))
        reference_mode = parent.reference_mode

    distribution = scoring.read_distribution(per_gate, scored, params.gate_ranks, DISTRIBUTION_TOP_N)
    distribution_file = write_table(distribution, out_dir, distribution_file_name(index))

    return {
        # Verbatim, exactly as it appears in the metadata column — this value lands in a
        # domain key a consumer matches on.
        "condition": condition,
        "gateRankMeanFile": gate_rank_mean_file,
        "binScoreFile": bin_score_file,
        "readDistributionFile": distribution_file,
        "referenceMode": reference_mode,
        "gatesCollected": _gates_collected(slice_c, params.gate_ranks),
        "variantsScored": scored.height,
        # How many the distribution view actually draws, against how many were scored.
        # Read by the view's own title, which names the count only where something was left
        # out: a truncated chart is otherwise indistinguishable from a complete one — the
        # same failure the sibling block's correction annotation has, where the view looks
        # right and says nothing about what it omitted. The count belongs here rather than
        # being recomputed UI-side, so the number shown is the number the run produced.
        "variantsPlotted": min(scored.height, DISTRIBUTION_TOP_N),
        # Reported as applied, from inside the computation. Deriving it from the run's
        # arguments instead would survive a slip that dropped the column from the reads
        # export and declare a correction that did not happen.
        "sortYieldCorrected": params.sort_fraction_column is not None,
        "sortFractionSum": _sort_fraction_sum(slice_c, params.sort_fraction_column),
    }


def _gates_collected(slice_c: pl.DataFrame, gate_ranks: dict[str, int]) -> list[dict]:
    """Each gate this condition collected, with its depth taken **before** the floor.

    Pre-floor is the number needed to choose a floor at all — `input-defaults` makes an
    unset floor the normal first run precisely so the depth distribution can be seen.

    A gate counts as collected when a sample exists for it; its depth may still be zero,
    which clause 1 handles by having it contribute to neither sum. A gate with no sample at
    this condition is simply not collected here, and that is not an error.

    Ordered by declared rank, so the run summary reads along the binding axis.
    """
    depths = slice_c.group_by(COL_GATE).agg(pl.col(COL_READS).sum().alias("depth"))
    rows = depths.iter_rows(named=True)
    return [
        {"gate": row[COL_GATE], "depth": row["depth"]}
        for row in sorted(rows, key=lambda row: gate_ranks[row[COL_GATE]])
    ]


def _sort_fraction_sum(slice_c: pl.DataFrame, sort_fraction_column: str | None) -> float | None:
    """This condition's supplied fractions, summed. None in the uncorrected mode.

    Taken over the supplied values — one per condition-and-gate group, which is the grain
    `frac_cb` is defined on — rather than once per variant row. Written this way the rule
    survives v2 replicates unchanged, where a group may hold more than one sample but still
    supplies one fraction per gate.

    A sum short of 1.0 is legitimate and is not renormalized: it is what a condition that
    collected only some of the declared gates correctly looks like.
    """
    if sort_fraction_column is None:
        return None
    per_gate = slice_c.group_by(COL_GATE).agg(pl.col(sort_fraction_column).first().alias("fraction"))
    total = per_gate["fraction"].sum()
    return None if total is None else float(total)
