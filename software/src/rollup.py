"""Rolling nucleotide-level scores up to the protein, with an uncertainty for each.

Which nucleotide variants belong to one protein arrives as a `proteinKey` column from the
`aaToNt` linker. This module never translates a variant to find out.

The two quantities roll up differently:

* Gate rank mean pools the reads, then computes once, in LINEAR space — a gate index is
  already a log-fluorescence scale. This is algebraically what protein grain does upstream,
  so the regression test demands exact agreement.
* Enrichment averages in LOG space, weighted by reads. It is a ratio, so a linear average
  lets one strongly-enriched variant dominate a protein whose others disagree.

Every value carries `max(SE_counting, SE_replicate)` — how well the reads pin the number
down, versus how much the variants disagree. The larger is the honest one.
"""

from __future__ import annotations

import polars as pl
from constants import (
    COL_CONDITION,
    COL_GATE,
    COL_PARENT_ID,
    COL_PROTEIN,
    COL_READS,
    COL_SAMPLE,
    COL_VARIANT,
    OUT_GATE_ENRICHMENT,
    OUT_GATE_RANK_MEAN,
    OUT_GATE_READS,
    OUT_INPUT_READS,
    OUT_UNCERTAINTY,
    OUT_NT_VARIANTS,
)

TOTAL_READS = "totalReads"

_RANK = "_rank"
_WEIGHT = "_weight"
_LOG = "_log"
_VARIANCE = "_variance"
_INVERSE_VARIANCE = "_inverseVariance"


def pool_reads_by_protein(reads: pl.DataFrame, proteins: pl.DataFrame) -> pl.DataFrame:
    """Relabel every nucleotide variant with its protein and sum the reads that collide.

    Returns the SAME shape that went in, with `variantKey` now holding a protein key, so
    every function downstream becomes protein-level with no second implementation.

    Rows the linker does not place are dropped: translating them would contradict the
    linker, and keeping them as their own protein invents a singleton.
    """
    placed = reads.join(proteins, on=COL_VARIANT, how="inner")
    return (
        # The parent is in the key, not just carried: a protein belongs to one parent, and the
        # pooled rows keep their own depths scoped the way the per-variant rows were.
        placed.group_by(COL_SAMPLE, COL_CONDITION, COL_GATE, COL_PARENT_ID, COL_PROTEIN)
        .agg(pl.col(COL_READS).sum())
        .rename({COL_PROTEIN: COL_VARIANT})
        .select(COL_SAMPLE, COL_VARIANT, COL_READS, COL_CONDITION, COL_GATE, COL_PARENT_ID)
        .sort(COL_SAMPLE, COL_VARIANT)
    )


def rank_mean_counting_error(
    per_gate: pl.DataFrame,
    means: pl.DataFrame,
    gate_ranks: dict[str, int],
) -> pl.DataFrame:
    """The counting error on a pooled gate rank mean: `σ_gate / √N`.

    `σ² = Σ w_b (b − mean)² / Σ w_b`. Reads in one gate give σ = 0, pinned by depth alone;
    reads spread across the ladder are less certain at the same depth.

    `N` is total reads over the collected gates. Unconfirmed: the spec says `√N_eff` without
    defining `N_eff`. Worth settling before this number reaches a threshold.
    """
    rank = pl.col(COL_GATE).replace_strict(gate_ranks, return_dtype=pl.Float64)
    joined = per_gate.with_columns(rank.alias(_RANK)).join(
        means.select(COL_VARIANT, OUT_GATE_RANK_MEAN), on=COL_VARIANT, how="inner"
    )

    spread = (
        joined.with_columns(
            (pl.col(_WEIGHT) * (pl.col(_RANK) - pl.col(OUT_GATE_RANK_MEAN)) ** 2).alias(_VARIANCE)
        )
        .group_by(COL_VARIANT)
        .agg(
            pl.col(_VARIANCE).sum().alias("_numerator"),
            pl.col(_WEIGHT).sum().alias("_denominator"),
            pl.col(COL_READS).sum().alias(TOTAL_READS),
        )
        .filter((pl.col("_denominator") > 0) & (pl.col(TOTAL_READS) > 0))
        .with_columns(
            ((pl.col("_numerator") / pl.col("_denominator")).sqrt() / pl.col(TOTAL_READS).sqrt())
            .alias(OUT_UNCERTAINTY)
        )
    )
    return spread.select(COL_VARIANT, OUT_UNCERTAINTY, TOTAL_READS).sort(COL_VARIANT)


def replicate_error(values: pl.DataFrame, value_column: str) -> pl.DataFrame:
    """`SD(per-variant values) / √n`. `values` is one row per (protein, nucleotide variant).

    A protein with one variant gets null, NOT zero. Zero would claim perfect agreement where
    there is nothing to compare, and the caller's max() would silently discard it.
    """
    return (
        values.group_by(COL_PROTEIN)
        .agg(
            pl.col(value_column).std(ddof=1).alias("_sd"),
            pl.len().alias(OUT_NT_VARIANTS),
        )
        .with_columns(
            pl.when(pl.col(OUT_NT_VARIANTS) > 1)
            .then(pl.col("_sd") / pl.col(OUT_NT_VARIANTS).sqrt())
            .otherwise(None)
            .alias(OUT_UNCERTAINTY)
        )
        .select(pl.col(COL_PROTEIN).alias(COL_VARIANT), OUT_UNCERTAINTY, OUT_NT_VARIANTS)
        .sort(COL_VARIANT)
    )


def rollup_enrichment(enrichments: pl.DataFrame, proteins: pl.DataFrame) -> pl.DataFrame:
    """Per (protein, gate): the enrichment averaged over the protein's nucleotide variants.

    Averaged in log space, returned on the linear scale so consumers read the same units as
    the per-variant column. Inverse-variance weighted with the delta-method variance of a log
    ratio, `varᵢ ≈ 1/k_gate,ᵢ + 1/k_input,ᵢ`; `SE = 1/√(Σ wᵢ)`.

    Zero-enrichment rows are dropped — log −∞ has no finite variance — which is a real
    limitation, not a tidy-up. Their reads still count in the totals, so a protein resting on
    little shows a thin `ntVariants` against a large read total.
    """
    placed = enrichments.join(proteins, on=COL_VARIANT, how="inner")
    usable = placed.filter(
        (pl.col(OUT_GATE_ENRICHMENT) > 0)
        & (pl.col(OUT_GATE_READS) > 0)
        & (pl.col(OUT_INPUT_READS) > 0)
    )
    if usable.height == 0:
        return usable.select(COL_VARIANT, COL_GATE).head(0)

    weighted = usable.with_columns(
        pl.col(OUT_GATE_ENRICHMENT).log().alias(_LOG),
        (1.0 / pl.col(OUT_GATE_READS) + 1.0 / pl.col(OUT_INPUT_READS)).alias(_VARIANCE),
    ).with_columns((1.0 / pl.col(_VARIANCE)).alias(_INVERSE_VARIANCE))

    per_protein = weighted.group_by(COL_PROTEIN, COL_GATE).agg(
        (pl.col(_LOG) * pl.col(_INVERSE_VARIANCE)).sum().alias("_numerator"),
        pl.col(_INVERSE_VARIANCE).sum().alias("_denominator"),
        pl.col(_LOG).std(ddof=1).alias("_sd"),
        pl.len().alias(OUT_NT_VARIANTS),
        pl.col(OUT_GATE_READS).sum().alias(OUT_GATE_READS),
        pl.col(OUT_INPUT_READS).sum().alias(OUT_INPUT_READS),
    )

    counting = 1.0 / pl.col("_denominator").sqrt()
    replicate = (
        pl.when(pl.col(OUT_NT_VARIANTS) > 1)
        .then(pl.col("_sd") / pl.col(OUT_NT_VARIANTS).sqrt())
        .otherwise(None)
    )

    return (
        per_protein.with_columns(
            (pl.col("_numerator") / pl.col("_denominator")).exp().alias(OUT_GATE_ENRICHMENT),
            # null means "no replicate estimate", not zero.
            pl.max_horizontal(counting, replicate.fill_null(counting)).alias(OUT_UNCERTAINTY),
        )
        .select(
            pl.col(COL_PROTEIN).alias(COL_VARIANT),
            COL_GATE,
            OUT_GATE_ENRICHMENT,
            OUT_UNCERTAINTY,
            OUT_NT_VARIANTS,
            OUT_GATE_READS,
            OUT_INPUT_READS,
        )
        .sort(COL_VARIANT, COL_GATE)
    )


def combine_errors(counting: pl.DataFrame, replicate: pl.DataFrame) -> pl.DataFrame:
    """`max(SE_counting, SE_replicate)` per protein, plus the variant count and read total.

    Never an average, never the counting error alone: a protein whose variants scatter is not
    made certain by having been read deeply. With one variant there is no replicate estimate,
    so the counting error stands — `ntVariants` travels so that is visible.
    """
    joined = counting.join(
        replicate.rename({OUT_UNCERTAINTY: "_replicate"}), on=COL_VARIANT, how="left"
    )
    return (
        joined.with_columns(
            pl.max_horizontal(
                pl.col(OUT_UNCERTAINTY), pl.col("_replicate").fill_null(pl.col(OUT_UNCERTAINTY))
            ).alias(OUT_UNCERTAINTY),
            pl.col(OUT_NT_VARIANTS).fill_null(1),
        )
        .select(COL_VARIANT, OUT_UNCERTAINTY, OUT_NT_VARIANTS, TOTAL_READS)
        .sort(COL_VARIANT)
    )
