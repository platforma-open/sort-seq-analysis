"""The arithmetic. Every function takes one condition's rows and is pure.

    gateRankMean(v,c)  =  Σ_b ( b · w_vcb ) / Σ_b w_vcb          range [1, G]

      freq_vcb  =  reads_vcb / depth_cb        depth_cb = Σ_v reads_vcb
      w_vcb     =  freq_vcb                    (uncorrected)
      w_vcb     =  freq_vcb · frac_cb          (sort-yield corrected, Adams eq. A3)

    binScore(v,c)      =  gateRankMean(v,c) − gateRankMean(parent,c)   where identifiable
    binScore(v,c)      =  gateRankMean(v,c)                            where it is not

    gateEnrichment(v,c,b)  =  freq_vcb / freq_vc,input        range [0, ∞)

The two zero cases are asymmetric. A zero numerator is a measurement — the variant was
depleted below detection — so the row is emitted with both read counts. A zero denominator
means no reference exists, so the variant gets no row at all.
"""

from __future__ import annotations

from dataclasses import dataclass

import codons
import polars as pl
from constants import (
    BASELINE_ABSENT_NEEDS_NUCLEOTIDE,
    BASELINE_ABSENT_NO_MUTATION_COUNT,
    BASELINE_ABSENT_NO_SYNONYMOUS,
    BASELINE_ABSENT_PARENT_UNIDENTIFIED,
    BASELINE_ABSENT_SEQUENCE_UNKNOWN,
    BASELINE_PERCENTILES,
    BASELINE_SEQUENCE,
    BASELINE_SYNONYMOUS,
    BASELINE_WILD_TYPE,
    CODON_ABSENT_NO_SEQUENCE,
    COL_GATE,
    COL_MUTATION_COUNT,
    COL_PARENT_ID,
    COL_READS,
    COL_VARIANT,
    MODE_CANCELLED,
    MODE_REFERENCED,
    OUT_BASELINE_LEVEL,
    OUT_BASELINE_VARIANTS,
    OUT_BIN_SCORE,
    OUT_GATE_ENRICHMENT,
    OUT_GATE_FREQUENCY,
    OUT_GATE_RANK_MEAN,
    OUT_GATE_READS,
    OUT_INPUT_READS,
    OUT_POSITION,
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
_INPUT_FREQUENCY = "_inputFrequency"

TOTAL_READS = "totalReads"


@dataclass(frozen=True)
class Parent:
    """The outcome of looking for the parent row: the variant whose mutation count is zero.

    Failing to identify one still emits `binScore`, in the cancelled form (numerically equal
    to `gateRankMean`). Not producing `binScore` at all is a third state, reached only when
    there is no mutation-count table.
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
    """Find the parent row, or record why there isn't one. None `variants` is not a failure."""
    if variants is None:
        # No mutation count anywhere — distinct from "a table exists and no row is zero".
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

    # The count is over the dataset's own alphabet, so exactly one row reaches zero at either
    # grain. More than one means an ambiguous library.
    reason = PARENT_ABSENT_NO_ZERO if count == 0 else PARENT_ABSENT_MULTIPLE_ZERO
    return Parent(variant_key=None, identified=False, absence_reason=reason, produce_bin_score=True)


def per_gate_frequencies(reads_c: pl.DataFrame, sort_fraction_column: str | None) -> pl.DataFrame:
    """Per (variant, gate): the frequency and the weight it contributes.

    Depths are summed over the condition's FULL slice, pre-floor. Over a floor-filtered set
    the floor would move every surviving variant's score, making two floor settings
    incomparable with nothing saying so.

    **A depth is taken within one parent.** A dataset may carry any number of parents, and
    pooling them scales every variant of a parent by how well its whole scaffold sorted:
    `enrichment_pooled = enrichment_scoped x (parent's share of the gate / of the input)`.
    Where no parent link resolved every row carries `PARENT_UNKNOWN`, so the group is
    degenerate and the single-parent numbers are unchanged.

    Returns `reads_c` plus `_depth`, `gateFrequency` and `_weight`.
    """
    with_depth = reads_c.with_columns(
        pl.col(COL_READS).sum().over([COL_PARENT_ID, COL_GATE]).alias(_DEPTH)
    )

    # Zero frequency drops a zero-depth gate from both sums at once, so it needs no special
    # case downstream.
    with_freq = with_depth.with_columns(
        pl.when(pl.col(_DEPTH) > 0)
        .then(pl.col(COL_READS) / pl.col(_DEPTH))
        .otherwise(0.0)
        .alias(OUT_GATE_FREQUENCY)
    )

    if sort_fraction_column is None:
        weight = pl.col(OUT_GATE_FREQUENCY)
    else:
        # Adams eq. A3; the column is validated before we get here.
        weight = pl.col(OUT_GATE_FREQUENCY) * pl.col(sort_fraction_column)

    return with_freq.with_columns(weight.alias(_WEIGHT))


def gate_rank_means(per_gate: pl.DataFrame, gate_ranks: dict[str, int]) -> pl.DataFrame:
    """The weighted mean per variant, before the floor.

    Returns `[variantKey, gateRankMean, totalReads]`. A variant with a zero denominator gets
    no row at all — no key, no NA, no sentinel. The denominator runs over collected gates
    only; the uncollected waste fraction is never reconstructed.
    """
    # Strict: an unranked gate raises rather than silently dropping its reads, which would
    # show only as a lighter weighted mean. `pipeline.selected_gates` guarantees it cannot fire.
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

    Depths were already taken over the full set, so this is a pure membership filter.
    """
    if read_floor is None:
        return means
    return means.filter(pl.col(TOTAL_READS) >= read_floor)


def bin_scores(
    scored: pl.DataFrame,
    parents_by_id: dict[str, Parent],
    variant_parent: pl.DataFrame | None,
) -> tuple[pl.DataFrame | None, str | None]:
    """`binScore` for the variants scored here, with the reference mode it was computed in.

    Each variant is referenced to **its own** parent, so a dataset carrying several gets one
    column whose every value is a difference from the right reference.

    Three outcomes:

    * no mutation-count table — `(None, None)`, produced nowhere.
    * NO parent identified — the cancelled form over every scored variant, equal to
      `gateRankMean`, mode `cancelled`. This is the state a one-parent run reaches when its
      parent row is missing, and it is unchanged.
    * at least one identified — the referenced form for their variants, mode `referenced`.
      A variant whose own parent went unidentified, or whose parent fell below the floor, gets
      **no row**: there is no reference to take a difference from, and emitting the cancelled
      form beside referenced ones would put two meanings in one column under one mode.
    """
    if not any(parent.produce_bin_score for parent in parents_by_id.values()):
        return None, None

    identified = {
        parent_id: parent for parent_id, parent in parents_by_id.items() if parent.identified
    }
    if not identified:
        return scored.select(COL_VARIANT, pl.col(OUT_GATE_RANK_MEAN).alias(OUT_BIN_SCORE)), MODE_CANCELLED

    # Only parents whose own row survived the floor here can reference anything.
    parent_means: dict[str, float] = {}
    for parent_id, parent in identified.items():
        row = scored.filter(pl.col(COL_VARIANT) == parent.variant_key)
        if row.height > 0:
            parent_means[parent_id] = row.item(0, OUT_GATE_RANK_MEAN)
    if not parent_means:
        return None, None

    if variant_parent is None:
        # One scope and no parent table: every scored variant belongs to it.
        only = next(iter(parents_by_id))
        placed = scored.select(COL_VARIANT).with_columns(pl.lit(only).alias(COL_PARENT_ID))
    else:
        placed = variant_parent

    referenced = (
        scored.join(placed, on=COL_VARIANT, how="left")
        .filter(pl.col(COL_PARENT_ID).is_in(list(parent_means)))
        .with_columns(
            (
                pl.col(OUT_GATE_RANK_MEAN)
                - pl.col(COL_PARENT_ID).replace_strict(parent_means, return_dtype=pl.Float64)
            ).alias(OUT_BIN_SCORE)
        )
        .select(COL_VARIANT, OUT_BIN_SCORE)
        .sort(COL_VARIANT)
    )
    if referenced.height == 0:
        return None, None
    return referenced, MODE_REFERENCED


def gate_enrichments(
    per_gate: pl.DataFrame,
    scored: pl.DataFrame,
    gate_ranks: dict[str, int],
    input_gate: str,
) -> pl.DataFrame | None:
    """Per (scored variant, collected gate): the enrichment against the input, with both
    read counts.

    `per_gate` must INCLUDE the input gate's rows — its frequencies are the denominators.

    None where there is no usable reference: the column is absent at this condition, not
    present-and-empty.

    The row set is every scored variant, so this deliberately does not reuse
    `read_distribution`, which is top-N for a chart. Both read counts travel because the
    ratio alone cannot be weighted: 4/40 and 4000/40000 are the same number, not the same
    evidence.
    """
    reference = (
        per_gate.filter(pl.col(COL_GATE) == input_gate)
        .select(
            COL_VARIANT,
            pl.col(OUT_GATE_FREQUENCY).alias(_INPUT_FREQUENCY),
            pl.col(COL_READS).alias(OUT_INPUT_READS),
        )
        # Zero denominator: no reference, so no row. An input gate that collected nothing
        # empties this frame and falls out as the None below.
        .filter(pl.col(_INPUT_FREQUENCY) > 0)
    )
    if reference.height == 0:
        return None

    ranked = per_gate.filter(pl.col(COL_GATE) != input_gate)

    # A gate that collected nothing is dropped whole. A column of zeros would say "every
    # variant was depleted here" rather than "nothing was measured here".
    depths = ranked.group_by(COL_GATE).agg(pl.col(_DEPTH).first())
    collected = sorted(
        depths.filter(pl.col(_DEPTH) > 0)[COL_GATE].to_list(),
        key=lambda gate: gate_ranks[gate],
    )
    if not collected:
        return None

    # Cross join so a variant absent from a gate gets its measured 0 rather than a hole.
    # `scored` carries the floor's decision.
    grid = (
        scored.select(COL_VARIANT)
        .join(reference, on=COL_VARIANT, how="inner")
        .join(pl.DataFrame({COL_GATE: collected}), how="cross")
    )
    observed = ranked.select(
        COL_VARIANT,
        COL_GATE,
        OUT_GATE_FREQUENCY,
        pl.col(COL_READS).alias(OUT_GATE_READS),
    )

    return (
        grid.join(observed, on=[COL_VARIANT, COL_GATE], how="left")
        .with_columns(
            pl.col(OUT_GATE_FREQUENCY).fill_null(0.0),
            pl.col(OUT_GATE_READS).fill_null(0),
        )
        .with_columns(
            (pl.col(OUT_GATE_FREQUENCY) / pl.col(_INPUT_FREQUENCY)).alias(OUT_GATE_ENRICHMENT)
        )
        .select(COL_VARIANT, COL_GATE, OUT_GATE_ENRICHMENT, OUT_GATE_READS, OUT_INPUT_READS)
        .sort(COL_VARIANT, COL_GATE)
    )


@dataclass(frozen=True)
class Baseline:
    """Which variants the enrichment is read against, or why none could be chosen.

    Resolved once per run, not per condition: a set that changed between conditions would
    make two gates of one run incomparable. How many survived the floor IS per condition,
    and the per-gate summary reports it.
    """

    option: str | None
    variant_keys: tuple[str, ...]
    absence_reason: str | None

    @property
    def identified(self) -> bool:
        return len(self.variant_keys) > 0


def resolve_baseline(
    variants: pl.DataFrame | None,
    reads: pl.DataFrame,
    option: str | None,
    sequence: str | None,
    parent: Parent,
    codon_facts: codons.CodonAnalysis,
) -> Baseline:
    """Pick the baseline variant set, or record why there isn't one.

    * wild type — the parent row, one variant.
    * synonymous — every variant whose single changed codon left the protein unchanged.
      The exact parent sequence is excluded: it is a large share of such a library on its
      own, and leaving it in caps the baseline near its own enrichment. Costs nothing here,
      since the parent changed no codon and `codons` never lists it.
    * sequence — one variant the user names.

    Synonymous needs the nucleotide grain; at protein grain those variants are already
    merged into the wild type. The absence reason says which grain would have it.
    """
    if option is None:
        return Baseline(option=None, variant_keys=(), absence_reason=None)

    if option == BASELINE_SEQUENCE:
        # Checked against the reads, so this option works without a mutation-count table.
        # A scan beats a unique() at library scale.
        known = reads.filter(pl.col(COL_VARIANT) == sequence).height > 0
        if not known:
            return Baseline(option, (), BASELINE_ABSENT_SEQUENCE_UNKNOWN)
        return Baseline(option, (str(sequence),), None)

    if variants is None:
        return Baseline(option, (), BASELINE_ABSENT_NO_MUTATION_COUNT)

    if option == BASELINE_WILD_TYPE:
        if not parent.identified:
            return Baseline(option, (), BASELINE_ABSENT_PARENT_UNIDENTIFIED)
        return Baseline(option, (str(parent.variant_key),), None)

    # No codons means no sequence to read them from, i.e. the protein-grain run. Frame
    # failures pass through unchanged: each names a different thing to fix.
    if not codon_facts.in_frame:
        reason = codon_facts.absence_reason
        if reason is None or reason == CODON_ABSENT_NO_SEQUENCE:
            reason = BASELINE_ABSENT_NEEDS_NUCLEOTIDE
        return Baseline(option, (), reason)

    silent = codon_facts.silent_variants
    if not silent:
        return Baseline(option, (), BASELINE_ABSENT_NO_SYNONYMOUS)
    # Already sorted, so the manifest is identical across runs — the workflow's dedup reads it.
    return Baseline(option, silent, None)


def baseline_summary(
    enrichments: pl.DataFrame,
    baseline: Baseline,
    gate_ranks: dict[str, int],
) -> dict[str, dict]:
    """Per gate: the baseline level, its spread, and how many variants back them.

    Percentiles, never a standard error. An SE shrinks as √n and describes the mean; a
    threshold needs how widely the variants themselves scatter, which does not shrink. No
    mean and no SE are emitted at all, because a number that is present will be used.

    The level is the median: an enrichment is a ratio with a long tail.

    Gates with no surviving baseline variant are absent rather than carrying nulls.
    """
    if not baseline.identified:
        return {}

    rows = enrichments.filter(pl.col(COL_VARIANT).is_in(list(baseline.variant_keys)))
    if rows.height == 0:
        return {}

    aggregations = [
        pl.col(OUT_GATE_ENRICHMENT).median().alias("level"),
        pl.col(OUT_GATE_ENRICHMENT).len().alias("variants"),
    ]
    aggregations += [
        # Linear interpolation: on a small set, the value a reader computing it by hand expects.
        pl.col(OUT_GATE_ENRICHMENT).quantile(percentile / 100, interpolation="linear").alias(f"p{percentile}")
        for percentile in BASELINE_PERCENTILES
    ]

    summary = rows.group_by(COL_GATE).agg(aggregations)

    return {
        row[COL_GATE]: {
            "level": row["level"],
            "spread": {f"p{percentile}": row[f"p{percentile}"] for percentile in BASELINE_PERCENTILES},
            "variants": row["variants"],
        }
        for row in sorted(summary.iter_rows(named=True), key=lambda row: gate_ranks[row[COL_GATE]])
    }


def value_baseline(values: pl.DataFrame, value_column: str, baseline: Baseline) -> dict | None:
    """Level and spread of one **per-variant** value over the baseline set.

    The sibling of `baseline_summary`, for a quantity that is already summed across gates.
    `gateRankMean` and `binScore` are per variant, so their baseline is one number per
    condition rather than one per gate.

    None where the baseline resolved nothing, or where none of its variants survived here.
    """
    if not baseline.identified:
        return None
    rows = values.filter(pl.col(COL_VARIANT).is_in(list(baseline.variant_keys)))
    if rows.height == 0:
        return None
    column = rows[value_column]
    return {
        "level": column.median(),
        "spread": {
            f"p{percentile}": column.quantile(percentile / 100, interpolation="linear")
            for percentile in BASELINE_PERCENTILES
        },
        "variants": rows.height,
    }


def percentile_column(percentile: int) -> str:
    """The header a percentile takes in the per-position baseline file."""
    return f"baselineP{percentile}"


def baseline_by_position(
    enrichments: pl.DataFrame,
    baseline: Baseline,
    codon_facts: codons.CodonAnalysis,
    gate_ranks: dict[str, int],
) -> dict[str, pl.DataFrame]:
    """The baseline split by the codon position each variant changed.

    Returns gate -> `[position, level, spread…, variants]`. Synonymous option only: the other
    two are single variants, so a split is one number repeated.

    Positions with nothing to report are absent rather than null — a blank cell reads as "no
    silent variant is possible here", which a row of nulls would not.

    Texture, not thresholds: a position often carries two values against the tens the
    per-gate summary pools, so the count travels on every row.
    """
    if baseline.option != BASELINE_SYNONYMOUS or not baseline.identified:
        return {}

    positions = [
        (key, codon_facts.position_of(key))
        for key in baseline.variant_keys
        if codon_facts.position_of(key) is not None
    ]
    if not positions:
        return {}

    keyed = pl.DataFrame(
        {
            COL_VARIANT: [key for key, _ in positions],
            OUT_POSITION: [position for _, position in positions],
        },
        schema_overrides={COL_VARIANT: pl.String, OUT_POSITION: pl.Int64},
    )
    rows = enrichments.join(keyed, on=COL_VARIANT, how="inner")
    if rows.height == 0:
        return {}

    aggregations = [
        pl.col(OUT_GATE_ENRICHMENT).median().alias(OUT_BASELINE_LEVEL),
        pl.col(OUT_GATE_ENRICHMENT).len().alias(OUT_BASELINE_VARIANTS),
    ]
    aggregations += [
        pl.col(OUT_GATE_ENRICHMENT)
        .quantile(percentile / 100, interpolation="linear")
        .alias(percentile_column(percentile))
        for percentile in BASELINE_PERCENTILES
    ]

    summary = rows.group_by(COL_GATE, OUT_POSITION).agg(aggregations)
    columns = [
        OUT_POSITION,
        OUT_BASELINE_LEVEL,
        *(percentile_column(percentile) for percentile in BASELINE_PERCENTILES),
        OUT_BASELINE_VARIANTS,
    ]

    return {
        gate: summary.filter(pl.col(COL_GATE) == gate).select(columns).sort(OUT_POSITION)
        for gate in sorted(summary[COL_GATE].unique().to_list(), key=lambda gate: gate_ranks[gate])
    }


def top_scoring_variants(
    scored: pl.DataFrame, top_n: int, by: str = OUT_GATE_RANK_MEAN
) -> pl.DataFrame:
    """The `top_n` variants the view draws, as a one-column frame of variant keys.

    `by` is the rank mean where the gates are ordered, and the read total where they are not —
    an unordered ladder has no score to rank along, and picking by depth is the honest fallback.

    The variant-key tiebreaker is load-bearing: ties are ordinary at low read counts, and
    without it two runs over one input could emit different sets and break dedup.
    """
    return (
        scored.sort([by, COL_VARIANT], descending=[True, False]).head(top_n).select(COL_VARIANT)
    )


def read_distribution(
    per_gate: pl.DataFrame,
    scored: pl.DataFrame,
    gate_ranks: dict[str, int],
    top_n: int,
    by: str = OUT_GATE_RANK_MEAN,
) -> pl.DataFrame:
    """Per (drawn variant, collected gate): the frequency and the raw reads.

    Top-N only — one series per variant, so the whole library would be unreadable. The
    scored set is untouched; the caller records the two counts so a truncated view never
    reads as complete.

    Every collected gate appears for every drawn variant: a missing point would read as a
    gap in the sort rather than a variant absent from that gate. Reads travel beside the
    frequency because four reads and four thousand draw the same profile.
    """
    collected = sorted(per_gate[COL_GATE].unique().to_list(), key=lambda gate: gate_ranks[gate])
    grid = top_scoring_variants(scored, top_n, by).join(
        pl.DataFrame({COL_GATE: collected}), how="cross"
    )

    observed = per_gate.select(COL_VARIANT, COL_GATE, OUT_GATE_FREQUENCY, pl.col(COL_READS).alias(OUT_GATE_READS))

    return (
        grid.join(observed, on=[COL_VARIANT, COL_GATE], how="left")
        .with_columns(
            pl.col(OUT_GATE_FREQUENCY).fill_null(0.0),
            pl.col(OUT_GATE_READS).fill_null(0),
        )
        .sort(COL_VARIANT, COL_GATE)
    )
