"""One run: validate, score each condition independently, write the manifest.

Conditions are scored independently and are never paired or ordered.

The manifest is the whole of what the workflow learns — it cannot re-derive which scores
were produced or in which reference mode.

The input gate is a reference, not a rung: `selected_gates` admits it, `ranked_gates`
removes it everywhere the ladder itself is read.
"""

from __future__ import annotations

from pathlib import Path

import codons
import polars as pl
import rollup
import scoring
from constants import (
    COL_CONDITION,
    COL_GATE,
    COL_PARENT_ID,
    COL_POSITION_LABEL,
    COL_PROTEIN,
    COL_READS,
    COL_RESIDUE,
    COL_VARIANT,
    DISTRIBUTION_TOP_N,
    OUT_BIN_SCORE,
    OUT_GATE_ENRICHMENT,
    OUT_GATE_RANK_MEAN,
    OUT_GATE_READS,
    OUT_INPUT_READS,
    OUT_POSITION,
    OUT_UNCERTAINTY,
    OUT_NT_VARIANTS,
)
from io_layer import (
    baseline_file_name,
    distribution_file_name,
    gate_score_file_name,
    rolled_gate_score_file_name,
    rolled_score_file_name,
    score_file_name,
    write_manifest,
    write_table,
)
from params import Params
from pooling import pool_replicates
from validate import check_sort_fractions


def run(
    reads: pl.DataFrame,
    variants: pl.DataFrame | None,
    positions: pl.DataFrame | None,
    params: Params,
    out_dir: Path,
) -> dict:
    """Score every retained condition and write every file. Returns the manifest."""
    in_scope = selected_gates(reads, params)

    # From the rungs alone: read from the full in-scope set, a condition holding only input
    # rows would become a condition of the run and be scored to an empty file.
    retained = retained_conditions(ranked_gates(in_scope, params), params)

    # Must run before anything else reads the table — see `pooling`.
    in_scope, pooled_groups = pool_replicates(in_scope, params.sort_fraction_column, retained)

    # Before anything is written, so a failure leaves nothing partial. Rungs only: an
    # unsorted input has no sort fraction to supply.
    if params.sort_fraction_column is not None:
        check_sort_fractions(ranked_gates(in_scope, params), params.sort_fraction_column, retained)

    parent = scoring.resolve_parent(variants)
    # Resolved before the baseline, which reads the synonymous set from it.
    codon_facts = codons.analyse(variants, in_scope, parent.variant_key)
    baseline = scoring.resolve_baseline(
        variants, in_scope, params.baseline, params.baseline_sequence, parent, codon_facts
    )
    # None here costs the per-position output only.
    alignment = _align_positions(codon_facts, positions)
    # The roll-up's precondition. Reported as `rolledUp`, which the workflow reads to pick
    # the axis: a spec on the amino-acid axis over nucleotide keys joins to nothing.
    proteins = protein_map(variants)

    out_dir.mkdir(parents=True, exist_ok=True)

    conditions = [
        _score_one_condition(
            in_scope, params, parent, baseline, codon_facts, alignment, proteins,
            condition, index, out_dir,
        )
        for index, condition in enumerate(retained)
    ]

    manifest = {
        "mode": params.mode,
        "parentIdentified": parent.identified,
        # Null where there was no mutation-count table at all.
        "parentAbsenceReason": parent.absence_reason,
        "baselineOption": baseline.option,
        "baselineIdentified": baseline.identified,
        "baselineAbsenceReason": baseline.absence_reason,
        "baselineVariants": len(baseline.variant_keys),
        "rolledUp": proteins is not None,
        "codonScheme": _codon_report(codon_facts),
        "positionAlignment": {
            "verified": alignment is not None and alignment.verified,
            "reason": None if alignment is None else alignment.reason,
            "parentId": None if alignment is None else (alignment.parent_id or None),
        },
        "pooledGroups": pooled_groups,
        "conditions": conditions,
    }
    write_manifest(manifest, out_dir)
    return manifest


def protein_map(variants: pl.DataFrame | None) -> pl.DataFrame | None:
    """Nucleotide variant -> its protein, from the `aaToNt` linker. None disables the roll-up."""
    if variants is None or COL_PROTEIN not in variants.columns:
        return None
    mapping = variants.select(COL_VARIANT, COL_PROTEIN).drop_nulls()
    return mapping if mapping.height > 0 else None


def ranked_gates(reads: pl.DataFrame, params: Params) -> pl.DataFrame:
    """The in-scope rows minus the input. Everything about the ladder is read through this."""
    return reads.filter(pl.col(COL_GATE).is_in(list(params.gate_ranks)))


def selected_gates(reads: pl.DataFrame, params: Params) -> pl.DataFrame:
    """The rows this run reads at all: the ranked gates, plus the input gate.

    `gateRanks` is a selection — a gate column routinely carries values that are not rungs
    (specificity, stability arms). Dropping them here, once, lets everything downstream treat
    `gate_ranks` as total over the rows it is handed.
    """
    in_run = list(params.gate_ranks)
    if params.input_gate is not None:
        in_run.append(params.input_gate)
    return reads.filter(pl.col(COL_GATE).is_in(in_run))


def retained_conditions(reads: pl.DataFrame, params: Params) -> list[str]:
    """The condition column's own distinct values, minus the excluded ones, sorted.

    Read from the in-scope rows, so a condition whose samples all sit in unselected gates is
    dropped rather than scored to an empty file. Sorted only to make the file index
    deterministic, which the workflow's pure-template dedup needs.
    """
    values = reads[COL_CONDITION].unique().drop_nulls().to_list()
    return sorted(value for value in values if value not in params.excluded_conditions)


def _score_one_condition(
    reads: pl.DataFrame,
    params: Params,
    parent: scoring.Parent,
    baseline: scoring.Baseline,
    codon_facts: codons.CodonAnalysis,
    alignment: codons.PositionAlignment | None,
    proteins: pl.DataFrame | None,
    condition: str,
    index: int,
    out_dir: Path,
) -> dict:
    slice_c = reads.filter(pl.col(COL_CONDITION) == condition)
    ranked_c = ranked_gates(slice_c, params)
    input_c = input_rows_for(reads, condition, params)

    # A depth is summed over one gate's own rows, so including the reference moves no rung's
    # frequency.
    per_gate = scoring.per_gate_frequencies(
        pl.concat([ranked_c, input_c]) if input_c.height > 0 else ranked_c,
        params.sort_fraction_column,
    )
    ranked_per_gate = ranked_gates(per_gate, params)

    # The measured level, always emitted. On a nucleotide run the baseline is measured here,
    # before pooling: pooling turns every synonymous variant into the parent and erases the set.
    means = scoring.gate_rank_means(ranked_per_gate, params.gate_ranks)
    scored = scoring.apply_read_floor(means, params.read_floor)

    gate_rank_mean_file = write_table(
        scored.select(COL_VARIANT, OUT_GATE_RANK_MEAN),
        out_dir,
        score_file_name(OUT_GATE_RANK_MEAN, index),
    )

    # The protein level, beside the measured one. Pooled in linear space: a gate index is
    # already a log-fluorescence scale, so a second log would be wrong.
    rolled: dict | None = None
    scored_rolled = None
    if proteins is not None:
        pooled = rollup.pool_reads_by_protein(
            pl.concat([ranked_c, input_c]) if input_c.height > 0 else ranked_c, proteins
        )
        pooled_ranked = ranked_gates(
            scoring.per_gate_frequencies(pooled, params.sort_fraction_column), params
        )
        means_rolled = scoring.gate_rank_means(pooled_ranked, params.gate_ranks)
        scored_rolled = scoring.apply_read_floor(means_rolled, params.read_floor)
        errors = rollup.combine_errors(
            rollup.rank_mean_counting_error(pooled_ranked, scored_rolled, params.gate_ranks),
            rollup.replicate_error(
                means.join(proteins, on=COL_VARIANT, how="inner"), OUT_GATE_RANK_MEAN
            ),
        )
        rolled = {
            "gateRankMeanFile": write_table(
                scored_rolled.join(errors, on=COL_VARIANT, how="left").select(
                    COL_VARIANT, OUT_GATE_RANK_MEAN, OUT_UNCERTAINTY, OUT_NT_VARIANTS
                ),
                out_dir,
                rolled_score_file_name(OUT_GATE_RANK_MEAN, index),
            ),
            "binScoreFile": None,
            "gateEnrichments": [],
            "variantsScored": scored_rolled.height,
        }

    if params.scores_enrichment:
        # Not produced in enrichment mode: the baseline already references every variant to
        # the parent, and two references would disagree. Mode left unclaimed, not set to a
        # token, so no consumer reads a cancellation that did not happen.
        bin_score_file = None
        reference_mode = None
    else:
        bin_score = scoring.bin_scores(scored, parent)
        if bin_score is None:
            # Absent, not present-and-empty: an empty column would claim every variant was
            # unscorable here.
            bin_score_file = None
            reference_mode = None
        else:
            bin_score_file = write_table(bin_score, out_dir, score_file_name(OUT_BIN_SCORE, index))
            reference_mode = parent.reference_mode

    distribution = scoring.read_distribution(
        ranked_per_gate, scored, params.gate_ranks, DISTRIBUTION_TOP_N
    )
    distribution_file = write_table(distribution, out_dir, distribution_file_name(index))

    gate_enrichments: list[dict] = []
    if params.scores_enrichment:
        # Order matters: the baseline is read from these unpooled rows.
        enrichments = scoring.gate_enrichments(
            per_gate, scored, params.gate_ranks, params.input_gate
        )
        if enrichments is not None:
            summaries = scoring.baseline_summary(enrichments, baseline, params.gate_ranks)
            position_rows = scoring.baseline_by_position(
                enrichments, baseline, codon_facts, params.gate_ranks
            )
            gate_enrichments = _write_gate_enrichments(
                enrichments, summaries, position_rows, alignment, params, index, out_dir
            )
            # Only now, after the baseline: average in log space, weighted by reads.
            if rolled is not None:
                rolled["gateEnrichments"] = _write_gate_enrichments(
                    rollup.rollup_enrichment(enrichments, proteins),
                    summaries,
                    {},
                    alignment,
                    params,
                    index,
                    out_dir,
                    rolled=True,
                )

    return {
        # Verbatim: this lands in a domain key a consumer matches on.
        "condition": condition,
        "gateRankMeanFile": gate_rank_mean_file,
        "binScoreFile": bin_score_file,
        "readDistributionFile": distribution_file,
        "referenceMode": reference_mode,
        "gatesCollected": _gates_collected(ranked_c, params.gate_ranks),
        # Every enrichment here rests on it, and a thin input makes the values texture.
        "inputDepth": _input_depth(input_c, params),
        "gateEnrichments": gate_enrichments,
        "rolled": rolled,
        "variantsScored": scored.height,
        # The view's title names this when it is short of `variantsScored`; a truncated
        # chart is otherwise indistinguishable from a complete one.
        "variantsPlotted": min(scored.height, DISTRIBUTION_TOP_N),
        # Reported from inside the computation: derived from the arguments it would survive
        # a slip that dropped the column from the export.
        "sortYieldCorrected": params.sort_fraction_column is not None,
        "sortFractionSum": _sort_fraction_sum(ranked_c, params.sort_fraction_column),
    }


def _align_positions(
    facts: codons.CodonAnalysis, positions: pl.DataFrame | None
) -> codons.PositionAlignment | None:
    """Match codon offsets to the profiler's position labels. None where there is nothing
    to match against."""
    if positions is None or positions.height == 0 or not facts.in_frame:
        return None
    return codons.align_positions(
        facts.parent_codons,
        positions[COL_PARENT_ID].to_list(),
        positions[COL_POSITION_LABEL].to_list(),
        positions[COL_RESIDUE].to_list(),
    )


def _label_positions(
    rows: pl.DataFrame | None, alignment: codons.PositionAlignment | None
) -> pl.DataFrame | None:
    """Swap this block's codon offsets for the profiler's position labels.

    None unless the mapping was verified: a file keyed on private offsets would join to the
    wrong residue, and a heat map one position out looks entirely plausible. The parent id
    rides along because the resulting column is keyed on `[parentId, position]`.
    """
    if rows is None or alignment is None or not alignment.verified:
        return None

    # `OUT_POSITION` and `COL_POSITION_LABEL` are the same string, so replace in place rather
    # than joining a second column of that name.
    labels = alignment.labels
    return rows.with_columns(
        pl.lit(alignment.parent_id).alias(COL_PARENT_ID),
        pl.col(OUT_POSITION)
        .map_elements(
            lambda offset: labels[offset] if 0 <= offset < len(labels) else None,
            return_dtype=pl.String,
        )
        .alias(OUT_POSITION),
    ).select(COL_PARENT_ID, OUT_POSITION, pl.exclude(COL_PARENT_ID, OUT_POSITION))


def _codon_report(facts: codons.CodonAnalysis) -> dict:
    """What the run inferred about the library, as the manifest carries it.

    Base frequencies travel so a human can check the call — wide separation between offsets
    means the threshold barely matters. Unreachable positions travel rather than reachable
    ones: shorter, and the list a consumer acts on by leaving those cells blank.
    """
    if facts.scheme is None:
        return {
            "identified": False,
            "absenceReason": facts.absence_reason,
            "label": None,
            "codons": [],
            "baseFrequencies": [],
            "reads": 0,
            "positionsTotal": len(facts.parent_codons),
            "positionsReachable": 0,
            "unreachablePositions": [],
        }

    scheme = facts.scheme
    return {
        "identified": True,
        "absenceReason": None,
        # e.g. "NNK".
        "label": scheme.label(),
        "codons": sorted(scheme.codons),
        # One map per codon offset, rounded — read by eye, not joined on.
        "baseFrequencies": [
            {base: round(fraction, 4) for base, fraction in sorted(offset.items())}
            for offset in scheme.frequencies
        ],
        "reads": scheme.reads,
        "positionsTotal": len(facts.parent_codons),
        "positionsReachable": facts.reachable_count,
        "unreachablePositions": facts.unreachable_positions,
    }


def _write_gate_enrichments(
    enrichments: pl.DataFrame,
    summaries: dict[str, dict],
    positions: dict[str, pl.DataFrame],
    alignment: codons.PositionAlignment | None,
    params: Params,
    index: int,
    out_dir: Path,
    rolled: bool = False,
) -> list[dict]:
    """One file per gate, and the manifest entry that names it.

    Each file carries the read counts beside the ratio: the ratio is not interpretable
    without them. Ordered by declared rank.
    """
    entries = []
    gates = sorted(
        enrichments[COL_GATE].unique().to_list(),
        key=lambda gate: params.gate_ranks[gate],
    )
    for gate in gates:
        rows = enrichments.filter(pl.col(COL_GATE) == gate)
        rank = params.gate_ranks[gate]
        # Present only on a rolled-up run: a per-variant enrichment has no nucleotide
        # variants to disagree.
        columns = [COL_VARIANT, OUT_GATE_ENRICHMENT, OUT_GATE_READS, OUT_INPUT_READS]
        if OUT_UNCERTAINTY in rows.columns:
            columns += [OUT_UNCERTAINTY, OUT_NT_VARIANTS]
        # The two levels must write to different names, or the measured values are lost
        # silently — same file, no error.
        name = (
            rolled_gate_score_file_name(OUT_GATE_ENRICHMENT, index, rank)
            if rolled
            else gate_score_file_name(OUT_GATE_ENRICHMENT, index, rank)
        )
        file_name = write_table(rows.select(columns), out_dir, name)
        # The baseline split by codon position. A null file name is the ordinary case: it
        # needs the synonymous option, readable codons, and a verified position mapping.
        position_rows = _label_positions(positions.get(gate), alignment)
        position_file = None
        if position_rows is not None and position_rows.height > 0:
            position_file = write_table(
                position_rows, out_dir, baseline_file_name(index, rank)
            )

        entries.append(
            {
                # Verbatim: lands in a domain key.
                "gate": gate,
                "rank": rank,
                "file": file_name,
                "variantsEnriched": rows.height,
                # Null is not zero: 0 would be a baseline measured at complete depletion.
                "baseline": summaries.get(gate),
                "baselinePositionFile": position_file,
                "baselinePositions": 0 if position_rows is None else position_rows.height,
            }
        )
    return entries


def input_rows_for(reads: pl.DataFrame, condition: str, params: Params) -> pl.DataFrame:
    """The rows serving as this condition's unsorted reference.

    The condition's own input if it has one, otherwise the run's. One shared input carrying
    its own condition value is the ordinary shape; looked for only inside the condition's
    slice it is not there, every denominator is zero, and the run looks healthy. Preferring
    the condition's own rows keeps a per-condition library from being pooled into one
    reference.

    Deliberately not filtered by `retained_conditions`: a condition value that exists only to
    label the input is excluded from scoring, and that must not discard the reference.
    """
    if params.input_gate is None:
        return reads.head(0)
    all_input = reads.filter(pl.col(COL_GATE) == params.input_gate)
    own = all_input.filter(pl.col(COL_CONDITION) == condition)
    return own if own.height > 0 else all_input


def _input_depth(input_c: pl.DataFrame, params: Params) -> int | None:
    """The reference's depth, or None outside enrichment mode. Zero is distinct from None:
    it means input rows exist but carry no reads."""
    if params.input_gate is None:
        return None
    return int(input_c[COL_READS].sum()) if input_c.height > 0 else 0


def _gates_collected(slice_c: pl.DataFrame, gate_ranks: dict[str, int]) -> list[dict]:
    """Each gate this condition collected, with its depth taken before the floor.

    Pre-floor is what a user needs to choose a floor at all. A gate with no sample here is
    simply not collected, which is not an error. Ordered by declared rank.
    """
    depths = slice_c.group_by(COL_GATE).agg(pl.col(COL_READS).sum().alias("depth"))
    rows = depths.iter_rows(named=True)
    return [
        {"gate": row[COL_GATE], "depth": row["depth"]}
        for row in sorted(rows, key=lambda row: gate_ranks[row[COL_GATE]])
    ]


def _sort_fraction_sum(slice_c: pl.DataFrame, sort_fraction_column: str | None) -> float | None:
    """This condition's supplied fractions, summed. None in the uncorrected mode.

    One value per condition-and-gate group, not per variant row. A sum short of 1.0 is
    legitimate and is never renormalized — it is what partial gate coverage looks like.
    """
    if sort_fraction_column is None:
        return None
    per_gate = slice_c.group_by(COL_GATE).agg(pl.col(sort_fraction_column).first().alias("fraction"))
    total = per_gate["fraction"].sum()
    return None if total is None else float(total)
