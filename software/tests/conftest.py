"""Fixture builders for tables small enough to compute by hand.

Every gate's depth is 100, so a frequency is a read count in hundredths and the arithmetic
comes out in exact decimals. `rel=1e-12` is the tolerance a float64 division needs, not a
range assertion.
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

    One sample per (condition, gate), with the id derived from the pair so two cannot
    collide. Use `replicate_frame` for a second sample of a gate.
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
# B and C share a mean by coincidence. Total reads separate them — P 100, A 100, B 98, C 2 —
# so a read floor has something to exclude.
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


def variants_frame(mutation_counts: dict[str, int], sequences: dict[str, str] | None = None):
    """The per-variant mutation-count table. With `sequences`, the nucleotide grain; without,
    the amino-acid grain, on which the synonymous baseline correctly refuses."""
    keys = sorted(mutation_counts)
    frame = pl.DataFrame(
        {"variantKey": keys, "mutationCount": [mutation_counts[key] for key in keys]},
        schema_overrides={"mutationCount": pl.Int64},
    )
    if sequences is None:
        return frame
    return frame.with_columns(
        pl.col("variantKey").replace_strict(sequences, return_dtype=pl.String).alias("sequence")
    )


# The parent is the single variant whose amino-acid mutation count is zero.
BASE_MUTATION_COUNTS = {"P": 0, "A": 1, "B": 2, "C": 3}


# ---------------------------------------------------------------------------
# Enrichment fixtures.
# ---------------------------------------------------------------------------

INPUT_GATE = "in"

# The unsorted reference for BASE_ROWS, at depth 100 like every ranked gate.
#
#   gate |  P |  A |  B |  C | depth
#   -----+----+----+----+----+------
#   in   | 20 | 30 | 40 | 10 |  100
INPUT_ROWS: list[tuple[str, str, int]] = [
    (INPUT_GATE, "P", 20),
    (INPUT_GATE, "A", 30),
    (INPUT_GATE, "B", 40),
    (INPUT_GATE, "C", 10),
]

# enrichment = the variant's frequency in the gate / its frequency in the input.
#
#   variant | f_in |  g1            |  g2           |  g3
#   --------+------+----------------+---------------+---------------
#   P       |  .20 | .10/.20 = 0.5  | .20/.20 = 1.0 | .70/.20 = 3.5
#   A       |  .30 | .30/.30 = 1.0  | .50/.30 = 5/3 | .20/.30 = 2/3
#   B       |  .40 | .59/.40 = 1.475| .29/.40 = .725| .10/.40 = 0.25
#   C       |  .10 | .01/.10 = 0.1  | .01/.10 = 0.1 | .00/.10 = 0.0
#
# C in g3 is the zero-numerator case: a measured 0, not a missing row.
BASE_ENRICHMENTS: dict[str, dict[str, float]] = {
    "g1": {"P": 0.5, "A": 1.0, "B": 1.475, "C": 0.1},
    "g2": {"P": 1.0, "A": 5 / 3, "B": 0.725, "C": 0.1},
    "g3": {"P": 3.5, "A": 2 / 3, "B": 0.25, "C": 0.0},
}


# ---------------------------------------------------------------------------
# Baseline fixtures — a nucleotide-grain library over one wild-type protein.
#
# W1 is the exact parent nucleotide sequence. W2..W6 are synonymous with it: different nucleotides, same
# protein. M1 changes the protein.
#
# Both gates are 1000 deep, so a frequency is the read count in thousandths.
#
#   variant | in   f_in | g1   f_g1 | enrichment
#   --------+-----------+-----------+-----------
#   W1      | 400   .40 |  50   .05 | 0.125     <- the parent nucleotide sequence, excluded from the set
#   W2      | 100   .10 |  50   .05 | 0.5
#   W3      | 100   .10 | 100   .10 | 1.0
#   W4      | 100   .10 | 150   .15 | 1.5
#   W5      | 100   .10 | 200   .20 | 2.0
#   W6      | 100   .10 | 250   .25 | 2.5
#   M1      | 100   .10 | 200   .20 | 2.0
#
# The synonymous baseline is W2..W6: [0.5, 1.0, 1.5, 2.0, 2.5], median 1.5. W1's 0.125 sits
# far below on purpose — let it in and the median moves to 1.25.
# ---------------------------------------------------------------------------

SYNONYMOUS_INPUT_ROWS: list[tuple[str, str, int]] = [
    (INPUT_GATE, "W1", 400),
    (INPUT_GATE, "W2", 100),
    (INPUT_GATE, "W3", 100),
    (INPUT_GATE, "W4", 100),
    (INPUT_GATE, "W5", 100),
    (INPUT_GATE, "W6", 100),
    (INPUT_GATE, "M1", 100),
]

SYNONYMOUS_GATE_ROWS: list[tuple[str, str, int]] = [
    ("g1", "W1", 50),
    ("g1", "W2", 50),
    ("g1", "W3", 100),
    ("g1", "W4", 150),
    ("g1", "W5", 200),
    ("g1", "W6", 250),
    ("g1", "M1", 200),
]

SYNONYMOUS_ROWS = SYNONYMOUS_GATE_ROWS + SYNONYMOUS_INPUT_ROWS

SYNONYMOUS_GATE_RANKS = {"g1": 1}

# Nucleotide grain with real sequences: the synonymous set is read from the codons.
# Parent is Met-Leu-Trp; Leu's six codons supply all five synonymous variants, and M1 changes
# that codon to Val as the missense control.
#
#   W1  ATG CTG TGG   M L W   the exact parent nucleotide sequence
#   W2  ATG TTA TGG   M L W   silent
#   W3  ATG TTG TGG   M L W   silent
#   W4  ATG CTT TGG   M L W   silent
#   W5  ATG CTC TGG   M L W   silent
#   W6  ATG CTA TGG   M L W   silent
#   M1  ATG GTG TGG   M V W   missense
SYNONYMOUS_PARENT_CODONS = ["ATG", "CTG", "TGG"]

SYNONYMOUS_SEQUENCES = {
    "W1": "ATGCTGTGG",
    "W2": "ATGTTATGG",
    "W3": "ATGTTGTGG",
    "W4": "ATGCTTTGG",
    "W5": "ATGCTCTGG",
    "W6": "ATGCTATGG",
    "M1": "ATGGTGTGG",
}

# Counted from the sequences rather than typed, so a fixture edit cannot leave the count
# disagreeing with the sequence it describes — which would make the parent unresolvable and
# every test below fail for the wrong reason.
SYNONYMOUS_MUTATION_COUNTS = {
    key: sum(1 for a, b in zip(SYNONYMOUS_SEQUENCES["W1"], sequence, strict=True) if a != b)
    for key, sequence in SYNONYMOUS_SEQUENCES.items()
}

# The five the synonymous baseline should select. W1 is the parent and excluded by construction —
# it changed no codon — and M1 changed the protein.
SYNONYMOUS_SILENT_KEYS = ("W2", "W3", "W4", "W5", "W6")

SYNONYMOUS_ENRICHMENTS = {
    "W1": 0.125,
    "W2": 0.5,
    "W3": 1.0,
    "W4": 1.5,
    "W5": 2.0,
    "W6": 2.5,
    "M1": 2.0,
}

# The five synonymous values, sorted: [0.5, 1.0, 1.5, 2.0, 2.5].
#
# Linear interpolation over n = 5 puts a quantile q at index 4q, so p25, p50 and p75 land
# exactly on the second, third and fourth members. p5 is at index 0.2 and p95 at index 3.8:
#   p5  = 0.5 + 0.2 * (1.0 - 0.5) = 0.6
#   p95 = 2.0 + 0.8 * (2.5 - 2.0) = 2.4
SYNONYMOUS_BASELINE_LEVEL = 1.5
SYNONYMOUS_BASELINE_SPREAD = {"p5": 0.6, "p25": 1.0, "p75": 2.0, "p95": 2.4}


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
    mode: str | None = None,
    input_gate: str | None = None,
    baseline: str | None = None,
    baseline_sequence: str | None = None,
) -> Path:
    """Write a parameter document. Defaults are the no-floor, uncorrected gate-ranking run.

    Optionals are written as explicit nulls; the workflow omits them instead. `test_params`
    pins both spellings."""
    document = {
        "gateRanks": gate_ranks if gate_ranks is not None else GATE_RANKS,
        "excludedConditions": excluded if excluded is not None else [],
        "readFloor": read_floor,
        "sortFractionColumn": sort_fraction_column,
        "mode": mode,
        "inputGate": input_gate,
        "baseline": baseline,
        "baselineSequence": baseline_sequence,
    }
    path.write_text(json.dumps(document), encoding="utf-8")
    return path
