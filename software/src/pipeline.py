"""One run: validate, score each condition independently, write the manifest.

Conditions are scored independently and are never paired or ordered.

The manifest is the whole of what the workflow learns — it cannot re-derive which scores
were produced or in which reference mode.

The input gate is a reference, not a rung: `selected_gates` admits it, `ranked_gates`
removes it everywhere the ladder itself is read.
"""

from __future__ import annotations

from dataclasses import dataclass
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
    PARENT_SUMMARY_FILE,
    OUT_ENRICHMENT_VS_BASELINE,
    RUN_MODE_ENRICHMENT,
    RUN_MODE_GATE_RANKING,
    OUT_BASELINE_LEVEL,
    OUT_BASELINE_VARIANTS,
    BASELINE_PERCENTILES,
    PARENT_UNKNOWN,
)
from io_layer import (
    baseline_bin_score_file_name,
    baseline_file_name,
    baseline_gate_file_name,
    distribution_file_name,
    gate_score_file_name,
    rolled_gate_score_file_name,
    rolled_score_file_name,
    score_file_name,
    write_manifest,
    write_table,
)
from params import Params
from scoring import TOTAL_READS
from pooling import pool_replicates
from validate import check_sort_fractions


def run(
    reads: pl.DataFrame,
    variants: pl.DataFrame | None,
    positions: pl.DataFrame | None,
    parents: pl.DataFrame | None,
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

    # AFTER pooling, and that order is load-bearing. `pool_replicates` treats every column it
    # does not know as per-sample metadata and resolves it per (condition, gate) — the parent
    # is per variant, so attaching it first smears one variant's parent across a whole gate.
    # Before any depth is taken, because every depth below is taken within one parent.
    in_scope = attach_parents(in_scope, parents)

    # Before anything is written, so a failure leaves nothing partial. Rungs only: an
    # unsorted input has no sort fraction to supply.
    if params.sort_fraction_column is not None:
        check_sort_fractions(ranked_gates(in_scope, params), params.sort_fraction_column, retained)

    # One scope per parent. Every parent-derived fact — the parent row, the codon scheme, the
    # baseline, the position alignment — belongs to one parent and is resolved within it.
    scopes = _parent_scopes(variants, parents, in_scope, positions, params)
    variant_parent = _variant_parent(variants, parents)
    protein_parent = _protein_parent(variants, parents)
    # The roll-up's precondition. Reported as `rolledUp`, which the workflow reads to pick
    # the axis: a spec on the amino-acid axis over nucleotide keys joins to nothing.
    proteins = protein_map(variants)

    out_dir.mkdir(parents=True, exist_ok=True)

    conditions = [
        _score_one_condition(
            in_scope, params, scopes, variant_parent, protein_parent, proteins,
            condition, index, out_dir,
        )
        for index, condition in enumerate(retained)
    ]

    # The top-level parent fields describe the run as a whole. On a one-parent dataset they are
    # that parent's, unchanged; on several they are the conjunction, and `parents` carries each.
    only = next(iter(scopes.values())) if len(scopes) == 1 else None
    manifest = {
        # Derived from the two facts below, for a reader that wants one word for the run.
        "mode": RUN_MODE_ENRICHMENT if params.scores_enrichment else RUN_MODE_GATE_RANKING,
        "gatesOrdered": params.scores_gate_rank,
        # The ladder the ranks came from, already rendered: "1 = NEG, 2 = MP, ...". A consumer
        # puts it beside a mean bin so 2.6 can be read without opening the settings.
        #
        # Rendered here rather than in the workflow because a rank arrives there as a JSON
        # number, and Tengo's string form for one is not worth relying on. Empty where the
        # gates carry no order, and then no rank column is emitted either.
        "gateLadder": (
            ", ".join(
                f"{rank} = {gate}"
                for gate, rank in sorted(params.gate_ranks.items(), key=lambda pair: pair[1])
            )
            if params.scores_gate_rank
            else ""
        ),
        "scoresEnrichment": params.scores_enrichment,
        "parentIdentified": all(scope.parent.identified for scope in scopes.values()),
        # Null where there was no mutation-count table at all.
        "parentAbsenceReason": _first_reason(scope.parent.absence_reason for scope in scopes.values()),
        "baselineOption": params.baseline,
        "baselineIdentified": any(scope.baseline.identified for scope in scopes.values()),
        "baselineAbsenceReason": _first_reason(
            scope.baseline.absence_reason for scope in scopes.values()
        ),
        "baselineVariants": sum(len(scope.baseline.variant_keys) for scope in scopes.values()),
        "rolledUp": proteins is not None,
        # One parent's scheme where there is one parent. Several libraries are reported per
        # parent instead, because they may be different designs.
        "codonScheme": _codon_report(only.codon_facts) if only else _codon_report(None),
        "positionAlignment": _alignment_report(only.alignment) if only else _alignment_report(None),
        # Every parent the run scored, with what each contributed and what it resolved.
        "parents": _parent_report(in_scope, scopes),
        # The same counts as a table, or null where no parent was placed and there is nothing
        # to key on.
        "parentSummaryFile": _write_parent_summary(in_scope, scopes, out_dir),
        "pooledGroups": pooled_groups,
        "conditions": conditions,
    }
    write_manifest(manifest, out_dir)
    return manifest


@dataclass(frozen=True)
class ParentScope:
    """Everything one parent decides for itself.

    The parent row, the codon scheme, the baseline set and the position alignment are all
    relative to one reference sequence, so a dataset carrying several resolves each within its
    own. A run with no parent table has exactly one scope under `PARENT_UNKNOWN`, which is why
    the single-parent path is unchanged rather than special-cased.
    """

    parent_id: str
    parent: scoring.Parent
    codon_facts: codons.CodonAnalysis
    baseline: scoring.Baseline
    alignment: codons.PositionAlignment | None


def _variant_parent(
    variants: pl.DataFrame | None, parents: pl.DataFrame | None
) -> pl.DataFrame | None:
    """variantKey -> parentId, or None where there is no variants table at all.

    With no parent table every variant maps to `PARENT_UNKNOWN`, which is the single scope's
    own key — so the one-parent path takes the same join as the many-parent one.
    """
    if variants is None:
        return None
    if parents is None:
        return variants.select(COL_VARIANT).with_columns(
            pl.lit(PARENT_UNKNOWN).alias(COL_PARENT_ID)
        )
    return variants.select(COL_VARIANT).join(parents, on=COL_VARIANT, how="left").with_columns(
        pl.col(COL_PARENT_ID).fill_null(PARENT_UNKNOWN)
    )


def _protein_parent(
    variants: pl.DataFrame | None, parents: pl.DataFrame | None
) -> pl.DataFrame | None:
    """proteinKey -> parentId. Every nucleotide variant of a protein shares its parent, so the
    mapping is well defined and the rolled level can reference its own baseline."""
    if variants is None or COL_PROTEIN not in variants.columns:
        return None
    if parents is None:
        return (
            variants.select(pl.col(COL_PROTEIN).alias(COL_VARIANT))
            .unique()
            .with_columns(pl.lit(PARENT_UNKNOWN).alias(COL_PARENT_ID))
            .sort(COL_VARIANT)
        )
    placed = variants.select(COL_VARIANT, COL_PROTEIN).join(parents, on=COL_VARIANT, how="inner")
    return (
        placed.select(pl.col(COL_PROTEIN).alias(COL_VARIANT), COL_PARENT_ID)
        .unique()
        .sort(COL_VARIANT)
    )


def _parent_scopes(
    variants: pl.DataFrame | None,
    parents: pl.DataFrame | None,
    reads: pl.DataFrame,
    positions: pl.DataFrame | None,
    params: Params,
) -> dict[str, ParentScope]:
    """Resolve the parent row, codon facts, baseline and alignment once per parent.

    Each parent sees only its own variants and its own reads, so one parent's library cannot
    vote on another's codon scheme and one parent's synonymous set cannot reach another's
    baseline. Ordered by parent id, so the manifest is stable across runs.
    """
    placed = _variant_parent(variants, parents)
    ids = sorted(reads[COL_PARENT_ID].unique().drop_nulls().to_list()) or [PARENT_UNKNOWN]

    scopes: dict[str, ParentScope] = {}
    for parent_id in ids:
        if placed is None:
            own_variants = variants
        else:
            keys = placed.filter(pl.col(COL_PARENT_ID) == parent_id).select(COL_VARIANT)
            own_variants = variants.join(keys, on=COL_VARIANT, how="inner")
        own_reads = reads.filter(pl.col(COL_PARENT_ID) == parent_id)

        parent = scoring.resolve_parent(own_variants)
        # Before the baseline, which reads the synonymous set from it.
        facts = codons.analyse(own_variants, own_reads, parent.variant_key)
        baseline = scoring.resolve_baseline(
            own_variants, own_reads, params.baseline, params.baseline_sequence, parent, facts
        )
        scopes[parent_id] = ParentScope(
            parent_id=parent_id,
            parent=parent,
            codon_facts=facts,
            baseline=baseline,
            # This parent's rows only, so a table listing several no longer refuses outright.
            alignment=_align_positions(facts, _positions_for(positions, parent_id)),
        )
    return scopes


def _positions_for(positions: pl.DataFrame | None, parent_id: str) -> pl.DataFrame | None:
    """The parent-residue rows belonging to one parent.

    A run with no parent table cannot tell which rows are whose, so it gets the table whole —
    `align_positions` then refuses a multi-parent table exactly as before.
    """
    if positions is None or parent_id == PARENT_UNKNOWN:
        return positions
    own = positions.filter(pl.col(COL_PARENT_ID) == parent_id)
    return own if own.height > 0 else None


def _write_parent_summary(
    reads: pl.DataFrame, scopes: dict[str, ParentScope], out_dir: Path
) -> str | None:
    """One row per parent: how much of the dataset it holds, and whether it found its own row.

    Emitted in every mode, so the parents are visible on a run that produces no baseline.
    Unplaced variants are left out: they have no parent id to key a column on.
    """
    rows = [
        {
            COL_PARENT_ID: entry["parentId"],
            "parentVariants": entry["variants"],
            "parentReads": entry["reads"],
        }
        for entry in _parent_report(reads, scopes)
        if entry["parentId"] is not None
    ]
    if not rows:
        return None
    return write_table(pl.DataFrame(rows).sort(COL_PARENT_ID), out_dir, PARENT_SUMMARY_FILE)


def _first_reason(reasons) -> str | None:
    """The first absence reason any parent gave, or None where none did."""
    for reason in reasons:
        if reason is not None:
            return reason
    return None


def _alignment_report(alignment: codons.PositionAlignment | None) -> dict:
    return {
        "verified": alignment is not None and alignment.verified,
        "reason": None if alignment is None else alignment.reason,
        "parentId": None if alignment is None else (alignment.parent_id or None),
    }


def attach_parents(reads: pl.DataFrame, parents: pl.DataFrame | None) -> pl.DataFrame:
    """Label every read row with the parent its variant was aligned to.

    Always adds the column, so every depth downstream is taken within one parent and no
    caller has to remember to scope. Where no table resolved, or a variant is not in it,
    the row takes `PARENT_UNKNOWN` and the group-by is degenerate.
    """
    # This function owns the column: the reads table never carries one, and dropping any that
    # appears keeps the join from colliding into `parentId_right` and silently keeping the
    # wrong side.
    reads = reads.drop(COL_PARENT_ID) if COL_PARENT_ID in reads.columns else reads
    if parents is None:
        return reads.with_columns(pl.lit(PARENT_UNKNOWN).alias(COL_PARENT_ID))
    return reads.join(parents, on=COL_VARIANT, how="left").with_columns(
        pl.col(COL_PARENT_ID).fill_null(PARENT_UNKNOWN)
    )


def _parent_report(reads: pl.DataFrame, scopes: dict[str, ParentScope]) -> list[dict]:
    """Each parent in scope: what it contributed, and what it resolved for itself.

    `PARENT_UNKNOWN` reports a null id: those variants were placed under no parent, so they
    are scored among themselves rather than folded into another parent's depths.
    """
    grouped = (
        reads.group_by(COL_PARENT_ID)
        .agg(
            pl.col(COL_VARIANT).n_unique().alias("variants"),
            pl.col(COL_READS).sum().alias("reads"),
        )
        .sort(COL_PARENT_ID)
    )
    report = []
    for row in grouped.iter_rows(named=True):
        scope = scopes.get(row[COL_PARENT_ID])
        report.append(
            {
                "parentId": row[COL_PARENT_ID] or None,
                "variants": row["variants"],
                "reads": int(row["reads"]),
                "parentIdentified": scope is not None and scope.parent.identified,
                "parentAbsenceReason": None if scope is None else scope.parent.absence_reason,
                "baselineIdentified": scope is not None and scope.baseline.identified,
                "baselineAbsenceReason": None if scope is None else scope.baseline.absence_reason,
                "baselineVariants": 0 if scope is None else len(scope.baseline.variant_keys),
                "codonScheme": _codon_report(None if scope is None else scope.codon_facts),
                "positionAlignment": _alignment_report(None if scope is None else scope.alignment),
            }
        )
    return report


def parents_present(reads: pl.DataFrame) -> list[str]:
    """The parents this run actually scored, sorted. `PARENT_UNKNOWN` is one of them where
    variants could not be placed."""
    return sorted(reads[COL_PARENT_ID].unique().drop_nulls().to_list())


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
    scopes: dict[str, ParentScope],
    variant_parent: pl.DataFrame | None,
    protein_parent: pl.DataFrame | None,
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

    # Computed either way: the denominator and the read total are rank-independent, so the
    # membership `scored` carries is what the floor and the enrichment need. Only the *value*
    # is meaningless without an order, which is why it is written and not just computed.
    gate_rank_mean_file = None
    if params.scores_gate_rank:
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
            "gateRankMeanFile": (
                write_table(
                    scored_rolled.join(errors, on=COL_VARIANT, how="left").select(
                        COL_VARIANT, OUT_GATE_RANK_MEAN, OUT_UNCERTAINTY, OUT_NT_VARIANTS
                    ),
                    out_dir,
                    rolled_score_file_name(OUT_GATE_RANK_MEAN, index),
                )
                if params.scores_gate_rank
                else None
            ),
            # Filled in below on a gate-ranking run; binScore is not produced in enrichment mode.
            "binScoreFile": None,
            "referenceMode": None,
            "gateEnrichments": [],
            "variantsScored": scored_rolled.height,
        }

    bin_score_baseline_file = None
    if not params.scores_gate_rank:
        # No order, so nothing to reference along. Not withheld because an input was named:
        # the baseline references the enrichment and the parent references the mean bin, which
        # are two quantities on two scales rather than two rival references for one.
        bin_score_file = None
        reference_mode = None
    else:
        parents_by_id = {key: scope.parent for key, scope in scopes.items()}
        bin_score, reference_mode = scoring.bin_scores(scored, parents_by_id, variant_parent)
        if bin_score is None:
            # Absent, not present-and-empty: an empty column would claim every variant was
            # unscorable here.
            bin_score_file = None
            reference_mode = None
        else:
            bin_score_file = write_table(bin_score, out_dir, score_file_name(OUT_BIN_SCORE, index))
            # The same reference at protein grain: each protein against its own parent's
            # protein. No baseline band here — the synonymous variants were pooled into the
            # parent protein, so there is no set left to measure noise from at this grain.
            if rolled is not None and scored_rolled is not None:
                rolled_bin, rolled_mode = scoring.bin_scores(
                    scored_rolled, _parents_at_protein_grain(scopes, proteins), protein_parent
                )
                if rolled_bin is not None:
                    rolled["binScoreFile"] = write_table(
                        rolled_bin, out_dir, rolled_score_file_name(OUT_BIN_SCORE, index)
                    )
                    rolled["referenceMode"] = rolled_mode
            bin_score_baseline_file = _write_bin_score_baseline(
                scored.join(bin_score, on=COL_VARIANT, how="inner"),
                scopes, variant_parent, index, out_dir,
            )

    # Without an order the rank mean cannot rank anything, so the cut falls back to read depth.
    distribution = scoring.read_distribution(
        ranked_per_gate, scored, params.gate_ranks, DISTRIBUTION_TOP_N,
        by=OUT_GATE_RANK_MEAN if params.scores_gate_rank else TOTAL_READS,
    )
    distribution_file = write_table(distribution, out_dir, distribution_file_name(index))

    gate_enrichments: list[dict] = []
    if params.scores_enrichment:
        # Order matters: the baseline is read from these unpooled rows.
        enrichments = scoring.gate_enrichments(
            per_gate, scored, params.gate_ranks, params.input_gate
        )
        if enrichments is not None:
            # One baseline per parent. `summaries` keeps the single-parent shape for the
            # annotations; `by_parent` is what the per-gate baseline file carries.
            summaries, by_parent = _baseline_summaries(enrichments, scopes, params)
            position_rows = _baseline_positions(enrichments, scopes, params)
            gate_enrichments = _write_gate_enrichments(
                enrichments, summaries, by_parent, position_rows, variant_parent,
                params, index, out_dir,
            )
            # Only now, after the baseline: average in log space, weighted by reads.
            if rolled is not None:
                rolled["gateEnrichments"] = _write_gate_enrichments(
                    rollup.rollup_enrichment(enrichments, proteins),
                    summaries,
                    by_parent,
                    {},
                    protein_parent,
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
        # The noise band on `binScore`, one row per parent. Gate-ranking mode only.
        "binScoreBaselineFile": bin_score_baseline_file,
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


def _codon_report(facts: codons.CodonAnalysis | None) -> dict:
    """What the run inferred about the library, as the manifest carries it.

    Base frequencies travel so a human can check the call — wide separation between offsets
    means the threshold barely matters. Unreachable positions travel rather than reachable
    ones: shorter, and the list a consumer acts on by leaving those cells blank.
    """
    if facts is None or facts.scheme is None:
        return {
            "identified": False,
            "absenceReason": None if facts is None else facts.absence_reason,
            "label": None,
            "codons": [],
            "baseFrequencies": [],
            "reads": 0,
            "positionsTotal": 0 if facts is None else len(facts.parent_codons),
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


def _parents_at_protein_grain(
    scopes: dict[str, ParentScope], proteins: pl.DataFrame | None
) -> dict[str, scoring.Parent]:
    """Each parent's row, re-keyed onto the protein it belongs to.

    The parent is identified as a nucleotide variant. Pooled to protein grain its score lives
    under its own protein key, so referencing the rolled scores needs the parent named the same
    way. Everything else about the parent — whether it identified, and why not — carries over,
    so `bin_scores` needs no separate protein-grain path.
    """
    if proteins is None:
        return {}
    lookup = dict(zip(proteins[COL_VARIANT].to_list(), proteins[COL_PROTEIN].to_list()))
    out: dict[str, scoring.Parent] = {}
    for parent_id, scope in scopes.items():
        parent = scope.parent
        key = None if parent.variant_key is None else lookup.get(parent.variant_key)
        out[parent_id] = scoring.Parent(
            variant_key=key,
            # A parent the linker did not place has no protein to reference, so it stops being
            # identified at this grain even though it is at the nucleotide one.
            identified=parent.identified and key is not None,
            absence_reason=parent.absence_reason,
            produce_bin_score=parent.produce_bin_score,
        )
    return out


def _write_bin_score_baseline(
    scored: pl.DataFrame,
    scopes: dict[str, ParentScope],
    variant_parent: pl.DataFrame | None,
    index: int,
    out_dir: Path,
) -> str | None:
    """The baseline of `binScore` itself, one row per parent, for one condition.

    Gate-ranking mode only. `binScore` already subtracts the parent, so this level is not a
    zero point — it should read near zero, and a level far from it says the parent sequence is
    not typical of its own synonymous family. The spread is what the level cannot give: how
    wide the noise is, in gate steps.
    """
    if OUT_BIN_SCORE not in scored.columns:
        return None
    rows = []
    for parent_id, scope in scopes.items():
        own = scored
        if variant_parent is not None:
            keys = variant_parent.filter(pl.col(COL_PARENT_ID) == parent_id).select(COL_VARIANT)
            own = scored.join(keys, on=COL_VARIANT, how="inner")
        summary = scoring.value_baseline(own, OUT_BIN_SCORE, scope.baseline)
        if summary is None:
            continue
        row = {COL_PARENT_ID: parent_id, OUT_BASELINE_LEVEL: summary["level"]}
        row.update(
            {
                scoring.percentile_column(percentile): summary["spread"][f"p{percentile}"]
                for percentile in BASELINE_PERCENTILES
            }
        )
        row[OUT_BASELINE_VARIANTS] = summary["variants"]
        rows.append(row)
    if not rows:
        return None
    return write_table(
        pl.DataFrame(rows).sort(COL_PARENT_ID), out_dir, baseline_bin_score_file_name(index)
    )


def _baseline_summaries(
    enrichments: pl.DataFrame, scopes: dict[str, ParentScope], params: Params
) -> tuple[dict[str, dict], dict[str, pl.DataFrame]]:
    """Per gate, each parent's baseline.

    Returns two views of one computation. The first is gate -> summary and carries the single
    parent's numbers, which is what the per-gate annotations can hold; it is empty where the
    run has several, because one annotation cannot describe several baselines. The second is
    gate -> a frame of one row per parent, which the per-gate baseline file carries on every
    run.
    """
    per_parent: dict[str, list[dict]] = {}
    single: dict[str, dict] = {}
    for parent_id, scope in scopes.items():
        summary = scoring.baseline_summary(enrichments, scope.baseline, params.gate_ranks)
        if len(scopes) == 1:
            single = summary
        for gate, values in summary.items():
            row = {COL_PARENT_ID: parent_id, OUT_BASELINE_LEVEL: values["level"]}
            row.update(
                {
                    scoring.percentile_column(percentile): values["spread"][f"p{percentile}"]
                    for percentile in BASELINE_PERCENTILES
                }
            )
            row[OUT_BASELINE_VARIANTS] = values["variants"]
            per_parent.setdefault(gate, []).append(row)

    frames = {
        gate: pl.DataFrame(rows).sort(COL_PARENT_ID) for gate, rows in per_parent.items() if rows
    }
    return single, frames


def _baseline_positions(
    enrichments: pl.DataFrame, scopes: dict[str, ParentScope], params: Params
) -> dict[str, pl.DataFrame]:
    """Per gate, the baseline split by codon position, labelled with each parent's own numbering.

    Each parent's offsets are matched against its own rows of the profiler's residue table, so
    a dataset carrying several no longer loses the per-position output outright. A parent whose
    alignment did not verify contributes nothing and the others still do.
    """
    by_gate: dict[str, list[pl.DataFrame]] = {}
    for scope in scopes.values():
        rows = scoring.baseline_by_position(
            enrichments, scope.baseline, scope.codon_facts, params.gate_ranks
        )
        for gate, frame in rows.items():
            labelled = _label_positions(frame, scope.alignment)
            if labelled is not None and labelled.height > 0:
                by_gate.setdefault(gate, []).append(labelled)
    return {gate: pl.concat(frames).sort(COL_PARENT_ID, OUT_POSITION) for gate, frames in by_gate.items()}


def _write_gate_enrichments(
    enrichments: pl.DataFrame,
    summaries: dict[str, dict],
    by_parent: dict[str, pl.DataFrame],
    positions: dict[str, pl.DataFrame],
    key_parent: pl.DataFrame | None,
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

        # The enrichment against its own parent's baseline, so 1.0 means "behaves like a
        # variant of no effect" on every gate, condition and parent. Divided, not subtracted:
        # an enrichment is a ratio, and subtracting would leave the gates incomparable.
        #
        # Absent where no baseline resolved, or where its level is zero — there is no usable
        # divisor, and an infinity is not a measurement.
        levels = by_parent.get(gate)
        if levels is not None and key_parent is not None:
            usable = levels.filter(pl.col(OUT_BASELINE_LEVEL) > 0).select(
                COL_PARENT_ID, OUT_BASELINE_LEVEL
            )
            if usable.height > 0:
                rows = (
                    rows.join(key_parent, on=COL_VARIANT, how="left")
                    .join(usable, on=COL_PARENT_ID, how="left")
                    .with_columns(
                        (pl.col(OUT_GATE_ENRICHMENT) / pl.col(OUT_BASELINE_LEVEL)).alias(
                            OUT_ENRICHMENT_VS_BASELINE
                        )
                    )
                )
                columns += [OUT_ENRICHMENT_VS_BASELINE]
        # The two levels must write to different names, or the measured values are lost
        # silently — same file, no error.
        name = (
            rolled_gate_score_file_name(OUT_GATE_ENRICHMENT, index, rank)
            if rolled
            else gate_score_file_name(OUT_GATE_ENRICHMENT, index, rank)
        )
        file_name = write_table(rows.select(columns), out_dir, name)
        # One row per parent, on every run. This is where a multi-parent baseline lives; the
        # annotations on the column above can only describe one.
        baseline_rows = by_parent.get(gate)
        baseline_gate_file = None
        if baseline_rows is not None and baseline_rows.height > 0:
            baseline_gate_file = write_table(
                baseline_rows, out_dir, baseline_gate_file_name(index, rank)
            )

        # The baseline split by codon position, already labelled with each parent's own
        # numbering. A null file name is the ordinary case: it needs the synonymous option,
        # readable codons, and a verified position mapping.
        position_rows = positions.get(gate)
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
                # Whether the file carries the vs-baseline column. The workflow cannot derive
                # it: the annotations are absent on a multi-parent run where the column is not.
                "hasVsBaseline": OUT_ENRICHMENT_VS_BASELINE in columns,
                "variantsEnriched": rows.height,
                # Null is not zero: 0 would be a baseline measured at complete depletion.
                "baseline": summaries.get(gate),
                "baselineGateFile": baseline_gate_file,
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
