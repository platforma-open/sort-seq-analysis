"""Fixture builders for tables small enough to compute by hand.

`computation-test-suite` requires every case to assert a hand-computed expected number or
an expected absence — never a range. The tables here are built so the arithmetic comes out
in exact decimals wherever possible: each gate's depth is 100, so a denominator of summed
frequencies is 1.00 and the weighted mean reduces to a sum of tenths.

Floats are compared with `pytest.approx(..., rel=1e-12)`. That is not a range assertion —
it is a hand-computed number with the tolerance a float64 division needs. Asserting bitwise
equality on a quotient would test the FPU, not the formula.
"""

from __future__ import annotations

import json
from pathlib import Path

import polars as pl

# Three ordered gates along the binding axis, weakest first.
GATE_RANKS = {"g1": 1, "g2": 2, "g3": 3}

PARENT = "P"


def reads_frame(rows: list[tuple[str, str, int]], condition: str = "pH7", fractions: dict[str, float] | None = None):
    """Build a reads table from (gate, variantKey, reads) triples.

    One sample per (condition, gate) — the grain the arithmetic is defined on — with the
    sample id derived from the pair so a caller cannot accidentally collide two. Use
    `replicate_frame` for the second sample of a gate.
    """
    frame = pl.DataFrame(
        {
            "sampleId": [f"s_{condition}_{gate}" for gate, _, _ in rows],
            "variantKey": [variant for _, variant, _ in rows],
            "reads": [reads for _, _, reads in rows],
            "condition": [condition] * len(rows),
            "gate": [gate for gate, _, _ in rows],
        },
        schema_overrides={"reads": pl.Int64},
    )
    if fractions is not None:
        frame = frame.with_columns(
            pl.col("gate").replace_strict(fractions, return_dtype=pl.Float64).alias("sortFraction")
        )
    return frame


def replicate_frame(
    rows: list[tuple[str, str, int]],
    sample: str,
    condition: str = "pH7",
    fractions: dict[str, float] | None = None,
):
    """A second sample for gates `reads_frame` already covered. The sample id is given rather
    than derived, so it collides on (condition, gate); concat the two frames."""
    return reads_frame(rows, condition=condition, fractions=fractions).with_columns(
        pl.lit(sample).alias("sampleId")
    )


# The base table. Every gate's depth is exactly 100.
#
#   gate |  P |  A |  B | C | depth
#   -----+----+----+----+---+------
#   g1   | 10 | 30 | 59 | 1 |  100
#   g2   | 20 | 50 | 29 | 1 |  100
#   g3   | 70 | 20 | 10 | 0 |  100
#
# freq = reads / depth, so each variant's denominator is its total reads / 100:
#
#   P: .10 .20 .70  den 1.00  num 1(.10)+2(.20)+3(.70) = 2.60  mean 2.6
#   A: .30 .50 .20  den 1.00  num 1(.30)+2(.50)+3(.20) = 1.90  mean 1.9
#   B: .59 .29 .10  den  .98  num 1(.59)+2(.29)+3(.10) = 1.47  mean 1.5   (147/98 = 3/2)
#   C: .01 .01 .00  den  .02  num 1(.01)+2(.01)        =  .03  mean 1.5   (3/2)
#
# B and C land on the same mean by coincidence, not by construction — B sits mid-low across
# three gates and C has two reads split across the bottom two. What separates them is total
# reads: P 100, A 100, B 98, C 2, deliberately unequal so a read floor has something to
# exclude without touching anything else.
BASE_ROWS: list[tuple[str, str, int]] = [
    ("g1", "P", 10),
    ("g1", "A", 30),
    ("g1", "B", 59),
    ("g1", "C", 1),
    ("g2", "P", 20),
    ("g2", "A", 50),
    ("g2", "B", 29),
    ("g2", "C", 1),
    ("g3", "P", 70),
    ("g3", "A", 20),
    ("g3", "B", 10),
    ("g3", "C", 0),
]

BASE_MEANS = {"P": 2.6, "A": 1.9, "B": 1.5, "C": 1.5}
BASE_TOTAL_READS = {"P": 100, "A": 100, "B": 98, "C": 2}


def variants_frame(mutation_counts: dict[str, int]):
    """The per-variant mutation-count table, at the amino-acid grain."""
    keys = sorted(mutation_counts)
    return pl.DataFrame(
        {"variantKey": keys, "mutationCount": [mutation_counts[key] for key in keys]},
        schema_overrides={"mutationCount": pl.Int64},
    )


# The parent is the single variant whose amino-acid mutation count is zero.
BASE_MUTATION_COUNTS = {"P": 0, "A": 1, "B": 2, "C": 3}


def means_as_dict(frame) -> dict[str, float]:
    return dict(zip(frame["variantKey"].to_list(), frame["gateRankMean"].to_list(), strict=True))


def scores_as_dict(frame, column: str) -> dict[str, float]:
    return dict(zip(frame["variantKey"].to_list(), frame[column].to_list(), strict=True))


def write_tsv(frame, path: Path) -> Path:
    frame.write_csv(path, separator="\t")
    return path


def write_params(
    path: Path,
    *,
    gate_ranks: dict[str, int] | None = None,
    excluded: list[str] | None = None,
    read_floor: int | None = None,
    sort_fraction_column: str | None = None,
) -> Path:
    """Write a parameter document. Defaults are the no-floor, uncorrected, nothing-excluded
    run — which `input-defaults` makes the normal first one, not an unset configuration."""
    document = {
        "gateRanks": gate_ranks if gate_ranks is not None else GATE_RANKS,
        "excludedConditions": excluded if excluded is not None else [],
        "readFloor": read_floor,
        "sortFractionColumn": sort_fraction_column,
    }
    path.write_text(json.dumps(document), encoding="utf-8")
    return path
