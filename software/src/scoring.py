"""The arithmetic, implementing `../dms-analysis#bin-score-formula`.

    gateRankMean(v,c)  =  Σ_b ( b · w_vcb ) / Σ_b w_vcb          range [1, G]

      freq_vcb  =  reads_vcb / depth_cb        depth_cb = Σ_v reads_vcb
      w_vcb     =  freq_vcb                    (uncorrected)
      w_vcb     =  freq_vcb · frac_cb          (sort-yield corrected, Adams eq. A3)

    binScore(v,c)      =  gateRankMean(v,c) − gateRankMean(parent,c)   where identifiable
    binScore(v,c)      =  gateRankMean(v,c)                            where it is not

Every function here takes one condition's rows and is pure. Which conditions exist,
which files get written and what the manifest says is `pipeline`'s.

The clause numbers in the comments are that atom's seven contract clauses. Three of them
are the reason this module is unit-tested against hand-computed numbers rather than
eyeballed: clause 1 (a zero-depth gate contributes to neither numerator nor denominator),
clause 2 (the denominator runs over collected gates only, waste not imputed) and clause 3
(the floor is applied *after* the depths are taken) all produce output of ordinary shape
and plausible content when implemented wrongly.
"""

from __future__ import annotations

from dataclasses import dataclass

import polars as pl
from constants import (
    COL_GATE,
    COL_MUTATION_COUNT,
    COL_READS,
    COL_VARIANT,
    MODE_CANCELLED,
    MODE_REFERENCED,
    OUT_BIN_SCORE,
    OUT_GATE_FREQUENCY,
    OUT_GATE_RANK_MEAN,
    OUT_GATE_READS,
    PARENT_ABSENT_MULTIPLE_ZERO,
    PARENT_ABSENT_NO_ZERO,
)

# Internal working columns. Prefixed so they cannot collide with a metadata column the
# workflow happened to name the same thing.
_DEPTH = "_depth"
_WEIGHT = "_weight"
_RANK = "_rank"
_NUMERATOR = "_numerator"
_DENOMINATOR = "_denominator"

TOTAL_READS = "totalReads"


@dataclass(frozen=True)
class Parent:
    """The outcome of looking for the parent row.

    `parent-row-identification` permits exactly one mechanism — the variant whose
    amino-acid mutation count is zero — so there are exactly two ways identification
    fails, and both mean the same thing for the output: `binScore` is emitted in the
    **cancelled** form, numerically equal to `gateRankMean`.

    `binScore` not being produced *at all* is a third and different state, reached only
    when there is no mutation-count table to read. Then no reference exists to cancel
    against and no reference mode is claimed.
    """

    variant_key: str | None
    identified: bool
    absence_reason: str | None
    produce_bin_score: bool

    @property
    def reference_mode(self) -> str | None:
        if not self.produce_bin_score:
            return None
        return MODE_REFERENCED if self.identified else MODE_CANCELLED


def resolve_parent(variants: pl.DataFrame | None) -> Parent:
    """Find the parent row, or record why there isn't one.

    `variants` is None when the workflow omitted the table because its mutation-count
    predicate resolved to nothing. That is not a failure: `gateRankMean` is unaffected
    and `binScore` is simply produced at no condition.
    """
    if variants is None:
        # No mutation count anywhere — distinct from "a table exists and no row is zero".
        # A missing table is what the workflow uses to say this, precisely so the two
        # cannot be confused (see `workflow-structure`).
        return Parent(variant_key=None, identified=False, absence_reason=None, produce_bin_score=False)

    zero_rows = variants.filter(pl.col(COL_MUTATION_COUNT) == 0)
    count = zero_rows.height

    if count == 1:
        return Parent(
            variant_key=zero_rows.item(0, COL_VARIANT),
            identified=True,
            absence_reason=None,
            produce_bin_score=True,
        )

    # Unidentifiable, both ways. More than one zero-count row is the case a nucleotide
    # grain would produce for a library of synonymous barcodes over one wild type — which
    # is why the workflow matches the mutation count at the amino-acid grain.
    reason = PARENT_ABSENT_NO_ZERO if count == 0 else PARENT_ABSENT_MULTIPLE_ZERO
    return Parent(variant_key=None, identified=False, absence_reason=reason, produce_bin_score=True)


def per_gate_frequencies(reads_c: pl.DataFrame, sort_fraction_column: str | None) -> pl.DataFrame:
    """Per (variant, gate): the frequency and the weight it contributes.

    `depth_cb` is summed over **every variant in `reads_c`**. `reads_c` is the condition's
    full slice — the workflow is forbidden from applying the floor to it — so this is the
    pre-floor depth clause 3 requires. Taking depths over a floor-filtered set instead
    would make the floor move every surviving variant's score, and two runs at two floor
    settings incomparable with nothing in the output saying so.

    Returns `reads_c` plus `_depth`, `gateFrequency` and `_weight`.
    """
    with_depth = reads_c.with_columns(pl.col(COL_READS).sum().over(COL_GATE).alias(_DEPTH))

    # Clause 1: a gate with depth 0 contributes to neither numerator nor denominator.
    # Zero frequency achieves that for both sums at once, so the gate needs no special
    # case anywhere downstream.
    with_freq = with_depth.with_columns(
        pl.when(pl.col(_DEPTH) > 0)
        .then(pl.col(COL_READS) / pl.col(_DEPTH))
        .otherwise(0.0)
        .alias(OUT_GATE_FREQUENCY)
    )

    if sort_fraction_column is None:
        weight = pl.col(OUT_GATE_FREQUENCY)
    else:
        # Adams eq. A3. The column is validated present and in range before we get here.
        weight = pl.col(OUT_GATE_FREQUENCY) * pl.col(sort_fraction_column)

    return with_freq.with_columns(weight.alias(_WEIGHT))


def gate_rank_means(per_gate: pl.DataFrame, gate_ranks: dict[str, int]) -> pl.DataFrame:
    """The weighted mean per variant, **before** the floor.

    Returns `[variantKey, gateRankMean, totalReads]`, one row per variant with a defined
    mean. A variant whose denominator is zero — no reads in any collected gate, or reads
    only in zero-depth gates — gets no row at all, per `unscorable-is-absent`: no key, no
    NA row, no sentinel.

    Clause 2: the denominator runs over the collected gates only. That falls out of
    `per_gate` holding rows only for gates the condition collected; the uncollected waste
    fraction is never reconstructed.
    """
    # replace_strict raises on a gate value with no rank rather than dropping its reads.
    # Reaching it is a bug in this package, not a caller error: `gateRanks` names the gates
    # the run covers, and `pipeline.selected_gates` has already dropped every row outside
    # that set. So this is an internal invariant — the one place that would notice a future
    # caller assembling `per_gate` without going through that filter, where the failure
    # would otherwise be a silently lighter weighted mean.
    rank = pl.col(COL_GATE).replace_strict(gate_ranks, return_dtype=pl.Float64)

    return (
        per_gate.with_columns(rank.alias(_RANK))
        .group_by(COL_VARIANT)
        .agg(
            (pl.col(_RANK) * pl.col(_WEIGHT)).sum().alias(_NUMERATOR),
            pl.col(_WEIGHT).sum().alias(_DENOMINATOR),
            pl.col(COL_READS).sum().alias(TOTAL_READS),
        )
        .filter(pl.col(_DENOMINATOR) > 0)
        .with_columns((pl.col(_NUMERATOR) / pl.col(_DENOMINATOR)).alias(OUT_GATE_RANK_MEAN))
        .select(COL_VARIANT, OUT_GATE_RANK_MEAN, TOTAL_READS)
        .sort(COL_VARIANT)
    )


def apply_read_floor(means: pl.DataFrame, read_floor: int | None) -> pl.DataFrame:
    """Decide which variants are scored. Never changes a score.

    Clause 3. `read_floor` of None is the no-floor run, which `input-defaults` makes the
    normal first one: every variant holding reads in at least one collected gate is
    scored. Because the depths were already taken over the full set, this is a pure
    membership filter — the property the optional-floor decision rests on, and the one
    `computation-test-suite` pins with a two-floor comparison.
    """
    if read_floor is None:
        return means
    return means.filter(pl.col(TOTAL_READS) >= read_floor)


def bin_scores(scored: pl.DataFrame, parent: Parent) -> pl.DataFrame | None:
    """`binScore` for the variants scored at this condition, or None where the column is
    not produced here.

    Three outcomes, and the difference between the last two is clause 5:

    * **no mutation-count table** — not produced anywhere. None.
    * **parent unidentifiable** — the cancelled form: numerically identical to
      `gateRankMean`, still emitted, and the mode in the domain is what tells a consumer
      which situation it is reading.
    * **parent identifiable but unscored here** — the column is **absent at this
      condition**, and it does *not* fall back to the cancelled form. The fallback is
      triggered by the parent being unidentifiable, never by its score being missing.
      A present column with no keys would claim every variant was unscorable, which is a
      different and false statement.
    """
    if not parent.produce_bin_score:
        return None

    if not parent.identified:
        return scored.select(COL_VARIANT, pl.col(OUT_GATE_RANK_MEAN).alias(OUT_BIN_SCORE))

    parent_row = scored.filter(pl.col(COL_VARIANT) == parent.variant_key)
    if parent_row.height == 0:
        # Clause 5. The parent is known but fell below the floor, or had no reads here.
        return None

    parent_mean = parent_row.item(0, OUT_GATE_RANK_MEAN)
    return scored.select(COL_VARIANT, (pl.col(OUT_GATE_RANK_MEAN) - parent_mean).alias(OUT_BIN_SCORE))


def top_scoring_variants(scored: pl.DataFrame, top_n: int) -> pl.DataFrame:
    """The `top_n` highest-scoring variants, as a one-column frame of variant keys.

    Ranked on `gateRankMean` descending — the block's own score, and the direction its
    `rankingOrder` annotation already declares — with the variant key ascending as the
    tiebreaker. The tiebreaker is not cosmetic: ties are ordinary at low read counts, and
    without it two runs over identical inputs could emit different variant sets, which
    would make the file non-deterministic and break pure-template dedup.
    """
    return (
        scored.sort([OUT_GATE_RANK_MEAN, COL_VARIANT], descending=[True, False])
        .head(top_n)
        .select(COL_VARIANT)
    )


def read_distribution(
    per_gate: pl.DataFrame,
    scored: pl.DataFrame,
    gate_ranks: dict[str, int],
    top_n: int,
) -> pl.DataFrame:
    """Per (drawn variant, collected gate): the frequency and the raw reads.

    The row set is **the `top_n` highest-scoring variants**, not every scored one. The view
    is one series per variant, so at library scale every scored variant would be a line on
    one chart — unreadable, and heavy to move. The scored set itself is untouched: it is
    what the score columns and the results table carry. The caller records how many
    variants were drawn against how many were scored, so a truncated view never reads as
    a complete one.

    Every collected gate appears for every drawn variant, including gates where the
    variant had no reads — the view draws a profile across gates, and a missing point
    would read as a gap in the sort rather than as a variant absent from that gate.

    Both quantities travel because the frequency is a shape and the reads say whether to
    trust it: a variant with four reads across two gates draws the same profile as one
    with four thousand.
    """
    collected = sorted(per_gate[COL_GATE].unique().to_list(), key=lambda gate: gate_ranks[gate])
    grid = top_scoring_variants(scored, top_n).join(pl.DataFrame({COL_GATE: collected}), how="cross")

    observed = per_gate.select(COL_VARIANT, COL_GATE, OUT_GATE_FREQUENCY, pl.col(COL_READS).alias(OUT_GATE_READS))

    return (
        grid.join(observed, on=[COL_VARIANT, COL_GATE], how="left")
        .with_columns(
            pl.col(OUT_GATE_FREQUENCY).fill_null(0.0),
            pl.col(OUT_GATE_READS).fill_null(0),
        )
        .sort(COL_VARIANT, COL_GATE)
    )
