"""Rolling nucleotide-level scores up to the protein, with an uncertainty for each.

Which nucleotide variants belong to one protein arrives as a `proteinKey` column from the
`aaToNt` linker. This module never translates a variant to find out.

Both quantities pool the reads of a protein's nucleotide variants and then compute once, exactly
as an amino-acid-grain run would. The regression test demands exact agreement for the rank mean.
Pooling also keeps a depleted variant's reads in the protein: averaging per-variant ratios
would have to drop every zero, and the protein would read as more enriched than it is.

Every value carries `max(SE_counting, SE_replicate)`, in the value's own units — how well the
reads pin the number down, versus how much the variants disagree. The larger is the honest one.
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
    ENRICHMENT_ZERO_READS_PSEUDOCOUNT,
    OUT_GATE_ENRICHMENT,
    OUT_GATE_RANK_MEAN,
    OUT_GATE_READS,
    OUT_INPUT_READS,
    OUT_NT_VARIANTS,
    OUT_UNCERTAINTY,
)
from scoring import ONE_READ_ENRICHMENT

TOTAL_READS = "totalReads"

_RANK = "_rank"
_WEIGHT = "_weight"
_VARIANCE = "_variance"
_COUNTING = "_counting"
_REPLICATE = "_replicate"
N_EFF = "_nEff"
WEIGHT_TOTAL = "_weightTotal"


def pool_reads_by_protein(
    reads: pl.DataFrame, proteins: pl.DataFrame, sort_fraction_column: str | None = None
) -> pl.DataFrame:
    """Relabel every nucleotide variant with its protein and sum the reads that collide.

    Returns the SAME shape that went in, with `variantKey` now holding a protein key, so
    every function downstream becomes protein-level with no second implementation.

    Rows the linker does not place are dropped: translating them would contradict the
    linker, and keeping them as their own protein invents a singleton.
    """
    # One value per (condition, gate) after `pool_replicates`, so the first is exact.
    carried = [sort_fraction_column] if sort_fraction_column in reads.columns else []
    placed = reads.join(proteins, on=COL_VARIANT, how="inner")
    return (
        # The parent is in the key, not just carried: a protein belongs to one parent, and the
        # pooled rows keep their own depths scoped the way the per-variant rows were.
        placed.group_by(COL_SAMPLE, COL_CONDITION, COL_GATE, COL_PARENT_ID, COL_PROTEIN)
        .agg(pl.col(COL_READS).sum(), *(pl.col(name).first() for name in carried))
        .rename({COL_PROTEIN: COL_VARIANT})
        .select(COL_SAMPLE, COL_VARIANT, COL_READS, COL_CONDITION, COL_GATE, COL_PARENT_ID, *carried)
        .sort(COL_SAMPLE, COL_VARIANT)
    )


def rank_mean_counting_error(
    per_gate: pl.DataFrame,
    means: pl.DataFrame,
    gate_ranks: dict[str, int],
) -> pl.DataFrame:
    """The counting error on a pooled gate rank mean: `σ_gate / √N_eff`.

    `σ² = Σ w_b (b − mean)² / Σ w_b`. Reads in one gate give σ = 0, pinned by depth alone;
    reads spread across the ladder are less certain at the same depth.

    `N_eff` is Kish's effective count, `(Σ w_b)² / Σ (w_b² / k_b)`. Each read carries weight
    `w_b / k_b`, one over its gate's depth, so reads from a shallow gate count for more and the
    mean rests on fewer independent reads than the total. With equal depths it is the total.
    """
    rank = pl.col(COL_GATE).replace_strict(gate_ranks, return_dtype=pl.Float64)
    joined = per_gate.filter(pl.col(COL_READS) > 0).with_columns(rank.alias(_RANK)).join(
        means.select(COL_VARIANT, OUT_GATE_RANK_MEAN), on=COL_VARIANT, how="inner"
    )

    spread = (
        joined.with_columns(
            (pl.col(_WEIGHT) * (pl.col(_RANK) - pl.col(OUT_GATE_RANK_MEAN)) ** 2).alias(_VARIANCE),
            (pl.col(_WEIGHT) ** 2 / pl.col(COL_READS)).alias("_weightSquare"),
        )
        .group_by(COL_VARIANT)
        .agg(
            pl.col(_VARIANCE).sum().alias("_numerator"),
            pl.col(_WEIGHT).sum().alias("_denominator"),
            pl.col("_weightSquare").sum().alias("_weightSquares"),
            pl.col(COL_READS).sum().alias(TOTAL_READS),
        )
        .filter((pl.col("_denominator") > 0) & (pl.col("_weightSquares") > 0))
        .with_columns((pl.col("_denominator") ** 2 / pl.col("_weightSquares")).alias(N_EFF))
        .with_columns(
            ((pl.col("_numerator") / pl.col("_denominator")).sqrt() / pl.col(N_EFF).sqrt())
            .alias(OUT_UNCERTAINTY)
        )
    )
    return spread.select(COL_VARIANT, OUT_UNCERTAINTY, TOTAL_READS).sort(COL_VARIANT)


def variant_weights(per_gate: pl.DataFrame) -> pl.DataFrame:
    """Each variant's total rank-mean weight, `Σ_b w_b` — its share of a pooled rank mean."""
    return per_gate.group_by(COL_VARIANT).agg(pl.col(_WEIGHT).sum().alias(WEIGHT_TOTAL))


def replicate_error(
    values: pl.DataFrame,
    value_column: str,
    weight_column: str,
    by: tuple[str, ...] = (COL_PROTEIN,),
) -> pl.DataFrame:
    """The scatter of a protein's nucleotide variants, as the error of their weighted mean.

    `SE² = n/(n−1) · Σ wᵢ² (xᵢ − x̄)² / (Σ wᵢ)²`, with `x̄` the w-weighted mean. The pooled score
    IS that weighted mean — pooling weights each variant by its share of the reads — so this is
    the scatter of the number actually reported. With equal weights it is `SD / √n`. A one-read
    variant carries a one-read weight, so its wild value barely moves the estimate.

    `values` is one row per (protein, nucleotide variant), plus `by`'s other keys. A group with
    one variant gets null, NOT zero: zero would claim perfect agreement where there is nothing
    to compare, and the caller's max() would silently discard it.
    """
    keys = list(by)
    weight = pl.col(weight_column).cast(pl.Float64)
    centre = (weight * pl.col(value_column)).sum().over(keys) / weight.sum().over(keys)
    return (
        values.with_columns(centre.alias("_centre"))
        .group_by(keys)
        .agg(
            (weight**2 * (pl.col(value_column) - pl.col("_centre")) ** 2).sum().alias("_scatter"),
            weight.sum().alias("_weights"),
            pl.len().alias(OUT_NT_VARIANTS),
        )
        .with_columns(
            pl.when((pl.col(OUT_NT_VARIANTS) > 1) & (pl.col("_weights") > 0))
            .then(
                (pl.col(OUT_NT_VARIANTS) / (pl.col(OUT_NT_VARIANTS) - 1) * pl.col("_scatter")).sqrt()
                / pl.col("_weights")
            )
            .otherwise(None)
            .alias(OUT_UNCERTAINTY)
        )
        .rename({COL_PROTEIN: COL_VARIANT})
        .select(COL_VARIANT, *(key for key in keys if key != COL_PROTEIN), OUT_UNCERTAINTY, OUT_NT_VARIANTS)
        .sort(COL_VARIANT, *(key for key in keys if key != COL_PROTEIN))
    )


def enrichment_uncertainty(
    pooled: pl.DataFrame, per_variant: pl.DataFrame, proteins: pl.DataFrame
) -> pl.DataFrame:
    """The error on each pooled protein enrichment, in the enrichment's own units.

    `pooled` is `scoring.gate_enrichments` over the pooled reads, `per_variant` the same over the
    nucleotide variants. Returns `pooled` plus `uncertainty` and `ntVariants`.

    * Counting: `E·√(1/k_gate + 1/k_input)`, the delta method on Poisson counts. A gate count of
      zero uses a pseudocount in this term only, or a measured zero would claim no error at all.
    * Replicate: `replicate_error` over the protein's nucleotide-variant enrichments at this gate,
      weighted by input reads, over the variants that passed the floor. Null with fewer than two.

    Symmetric, so it understates the upward error on a thin count; below ~20 reads on either side
    the read columns beside it are the better guide.
    """
    gate_reads = pl.max_horizontal(
        pl.col(OUT_GATE_READS).cast(pl.Float64), pl.lit(ENRICHMENT_ZERO_READS_PSEUDOCOUNT)
    )
    counting = (
        pl.col(ONE_READ_ENRICHMENT)
        * gate_reads
        * (1.0 / gate_reads + 1.0 / pl.col(OUT_INPUT_READS)).sqrt()
    )

    # Weighted by input reads: with the input depth shared, that is each variant's share of the
    # pooled ratio.
    replicate = replicate_error(
        per_variant.join(proteins, on=COL_VARIANT, how="inner"),
        OUT_GATE_ENRICHMENT,
        OUT_INPUT_READS,
        by=(COL_PROTEIN, COL_GATE),
    ).rename({OUT_UNCERTAINTY: _REPLICATE})

    return (
        pooled.with_columns(counting.alias(_COUNTING))
        .join(replicate, on=[COL_VARIANT, COL_GATE], how="left")
        .with_columns(
            # null means "no replicate estimate", not zero.
            pl.max_horizontal(
                pl.col(_COUNTING), pl.col(_REPLICATE).fill_null(pl.col(_COUNTING))
            ).alias(OUT_UNCERTAINTY),
            # A protein can pass the floor on pooled reads while none of its variants does alone.
            pl.col(OUT_NT_VARIANTS).fill_null(0),
        )
        .drop(_COUNTING, _REPLICATE)
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
            # A protein can pass the floor on pooled reads while none of its variants does alone.
            pl.col(OUT_NT_VARIANTS).fill_null(0),
        )
        .select(COL_VARIANT, OUT_UNCERTAINTY, OUT_NT_VARIANTS, TOTAL_READS)
        .sort(COL_VARIANT)
    )
