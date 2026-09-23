"""Codon-level facts, derived from the per-variant nucleotide sequence.

Three questions: which codon a variant changed, what codon set the library used
(`infer_scheme`), and whether a position can carry a synonymous change at all
(`reachable_positions`).

This module translates single CODONS and never a whole variant. Which nucleotide variants
belong to one protein stays the `aaToNt` linker's answer — a second implementation that
disagreed would regroup variants silently.

Reachability is a property of the parent CODON, not of its residue. Under NNK, Phe is the
clean case: NNK's only Phe codon is TTT, so a parent TTC is reachable and a parent TTT is
not. Same residue, opposite answers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import product

import polars as pl

from constants import (
    CODON_ABSENT_NO_SEQUENCE,
    CODON_ABSENT_NO_SINGLE_CODON_VARIANTS,
    CODON_ABSENT_NOT_DEGENERATE,
    CODON_ABSENT_PARENT_OUT_OF_FRAME,
    CODON_ABSENT_PARENT_UNIDENTIFIED,
    CODON_BASE_MIN_FRACTION,
    CODON_POSITION_MIN_VARIANTS,
    CODON_SIZE,
    COL_READS,
    COL_SEQUENCE,
    COL_VARIANT,
    POSITION_ALIGN_LENGTH_MISMATCH,
    POSITION_ALIGN_MULTIPLE_PARENTS,
    POSITION_ALIGN_NON_NUMERIC,
    POSITION_ALIGN_RESIDUE_MISMATCH,
)

BASES = ("T", "C", "A", "G")

# NCBI translation table 1, in the standard TCAG x TCAG x TCAG order.
_RESIDUES = "FFLLSSSSYY**CC*WLLLLPPPPHHQQRRRRIIIMTTTTNNKKSSRRVVVVAAAADDEEGGGG"

CODON_TABLE: dict[str, str] = {
    "".join(triple): _RESIDUES[index]
    for index, triple in enumerate(product(BASES, repeat=CODON_SIZE))
}

STOP = "*"


@dataclass(frozen=True)
class CodonScheme:
    """The library's degenerate codon, inferred from what the run sequenced.

    `bases` holds the set admitted at each offset — NNK is "anything, anything, G or T".
    Inferring the pattern rather than 32 independent codons rests each offset's call on every
    read in the run. `frequencies` is kept so a human can check it.
    """

    bases: tuple[frozenset[str], ...]
    codons: frozenset[str]
    frequencies: tuple[dict[str, float], ...]
    # Reads behind the inference, so a thin run is visible rather than quietly confident.
    reads: int

    @property
    def is_degenerate(self) -> bool:
        """Whether any offset admits more than one base. One that does not is a single
        sequence, not a library, and every reachability answer would be False."""
        return any(len(offset) > 1 for offset in self.bases)

    def label(self) -> str:
        """The scheme in IUPAC notation, e.g. `NNK`, so an unnamed set still prints readably."""
        return "".join(_IUPAC.get(frozenset(offset), "?") for offset in self.bases)


# Only the sets a degenerate codon actually uses; anything else prints as "?".
_IUPAC: dict[frozenset[str], str] = {
    frozenset("A"): "A",
    frozenset("C"): "C",
    frozenset("G"): "G",
    frozenset("T"): "T",
    frozenset("GT"): "K",
    frozenset("AC"): "M",
    frozenset("AG"): "R",
    frozenset("CT"): "Y",
    frozenset("CG"): "S",
    frozenset("AT"): "W",
    frozenset("CGT"): "B",
    frozenset("AGT"): "D",
    frozenset("ACT"): "H",
    frozenset("ACG"): "V",
    frozenset("ACGT"): "N",
}


def split_codons(sequence: str) -> list[str] | None:
    """The sequence as triplets, or None where it is not a whole number of codons.

    Half the frame guard: splitting assumes frame 0, and reading one base out would make every
    codon after the offset nonsense.
    """
    if not sequence or len(sequence) % CODON_SIZE != 0:
        return None
    return [sequence[i : i + CODON_SIZE] for i in range(0, len(sequence), CODON_SIZE)]


def residue(codon: str) -> str | None:
    """The amino acid a codon encodes, or None for anything not a plain ACGT triplet.

    None rather than "X": a placeholder would compare equal to itself and make two unknowns
    look synonymous.
    """
    return CODON_TABLE.get(codon.upper())


def translates_cleanly(codons: list[str]) -> bool:
    """Whether every codon is a plain triplet and none but the last is a stop.

    The other half of the frame guard: catches a wrong frame whose length happens to be a
    multiple of three, since an out-of-frame read hits stop codons almost immediately.
    """
    residues = [residue(codon) for codon in codons]
    if any(value is None for value in residues):
        return False
    return STOP not in residues[:-1]


def changed_codon(parent_codons: list[str], variant_codons: list[str]) -> int | None:
    """The single codon offset at which a variant differs from the parent, or None.

    None where the variant is the parent, differs at several codons, or has a different
    length. Restricting to one changed codon is the strongest error filter available here.
    """
    if len(parent_codons) != len(variant_codons):
        return None
    changed = [i for i, (p, v) in enumerate(zip(parent_codons, variant_codons)) if p != v]
    return changed[0] if len(changed) == 1 else None


def infer_scheme(
    observations: list[tuple[int, str, int]],
    min_fraction: float = CODON_BASE_MIN_FRACTION,
) -> CodonScheme | None:
    """Infer the library's degenerate codon from observed variant codons and their reads.

    `observations` is (position, codon, reads) for every single-codon variant.

    Every position gets ONE vote, whatever its depth. Reads decide what is real within a
    position; positions decide what the library is. Read-weighting across positions lets one
    abundant position decide the scheme — a position holding 44% of reads and 98.6% one codon
    drags the answer from NNK to NND.

    Pooled across positions, never read per position: no synonymous variant at a position
    proves nothing, since it may be reachable but thinly covered.

    None where there is nothing to infer from, or no offset admits more than one base.
    """
    if not observations:
        return None

    per_position: dict[int, list[dict[str, int]]] = {}
    distinct: dict[int, set[str]] = {}
    reads_total = 0
    for position, codon, reads in observations:
        if reads <= 0 or residue(codon) is None:
            continue
        reads_total += reads
        counts = per_position.setdefault(
            position, [dict.fromkeys(BASES, 0) for _ in range(CODON_SIZE)]
        )
        distinct.setdefault(position, set()).add(codon.upper())
        for offset, base in enumerate(codon.upper()):
            counts[offset][base] += reads

    # Without this the equal-vote rule lets a position whose only variant is a sequencing error
    # speak as loudly as a fully-sampled one.
    voting = [
        counts
        for position, counts in per_position.items()
        if len(distinct[position]) >= CODON_POSITION_MIN_VARIANTS
    ]
    if not voting:
        return None

    # Each voting position's own read-weighted composition, then the unweighted mean of those.
    totals = [dict.fromkeys(BASES, 0.0) for _ in range(CODON_SIZE)]
    for counts in voting:
        for offset, base_counts in enumerate(counts):
            depth = sum(base_counts.values())
            if depth == 0:
                continue
            for base, count in base_counts.items():
                totals[offset][base] += count / depth

    frequencies = tuple(
        {base: value / len(voting) for base, value in offset.items()} for offset in totals
    )
    bases = tuple(
        frozenset(base for base, fraction in offset.items() if fraction >= min_fraction)
        for offset in frequencies
    )

    # An empty offset means the threshold swallowed a real signal. Refuse: the codon set would
    # be empty and mark every position unreachable.
    if any(len(offset) == 0 for offset in bases):
        return None

    codons = frozenset("".join(triple) for triple in product(*bases))
    scheme = CodonScheme(bases=bases, codons=codons, frequencies=frequencies, reads=reads_total)
    return scheme if scheme.is_degenerate else None


@dataclass(frozen=True)
class CodonChange:
    """The one codon a variant changed, and whether that change was silent.

    `silent` compares two single codons' residues, never a whole variant, so nothing here
    asserts which protein a variant is — only that this codon did not change it.
    """

    position: int
    codon: str
    silent: bool


@dataclass(frozen=True)
class CodonAnalysis:
    """Everything the codon facts amount to for one run, or why there are none.

    Resolved once per run: a set that changed between conditions would make two positions of
    one run incomparable.
    """

    scheme: CodonScheme | None
    absence_reason: str | None
    parent_codons: list[str] = field(default_factory=list)
    # Codon offset -> whether a synonymous change is possible there. Empty without a scheme.
    reachable: dict[int, bool] = field(default_factory=dict)
    # Single-codon variants only: a variant absent here is the parent or changed several.
    changes: dict[str, CodonChange] = field(default_factory=dict)

    @property
    def identified(self) -> bool:
        return self.scheme is not None

    @property
    def in_frame(self) -> bool:
        """Whether the parent split into codons. Silent-variant answers need only this; the
        scheme is for reachability and is a separate question."""
        return len(self.parent_codons) > 0

    def is_designed(self, change: CodonChange) -> bool:
        """Whether a change used a codon the library designed. With no scheme, everything
        counts — better than silently emptying the set."""
        return self.scheme is None or change.codon in self.scheme.codons

    @property
    def silent_variants(self) -> tuple[str, ...]:
        """The variants whose single changed codon left the protein unchanged, sorted.

        The parent is excluded by construction — it changed no codon, so it never enters
        `changes`. That matters: it is a large share of a real library and leaving it in caps
        the baseline near its own enrichment.

        Off-scheme codons are excluded too, which keeps silent sequencing errors out. That is
        a stronger mask than filtering positions by reachability and subsumes it.
        """
        return tuple(
            sorted(
                key
                for key, change in self.changes.items()
                if change.silent and self.is_designed(change)
            )
        )

    def position_of(self, variant_key: str) -> int | None:
        """The codon offset a variant changed, or None where it changed none or several."""
        change = self.changes.get(variant_key)
        return None if change is None else change.position

    @property
    def reachable_count(self) -> int:
        return sum(1 for value in self.reachable.values() if value)

    @property
    def unreachable_positions(self) -> list[int]:
        """The cells a heat map should leave blank rather than fill with silent errors."""
        return sorted(position for position, value in self.reachable.items() if not value)


def analyse(
    variants: pl.DataFrame | None,
    reads: pl.DataFrame,
    parent_key: str | None,
    min_fraction: float = CODON_BASE_MIN_FRACTION,
) -> CodonAnalysis:
    """Derive the run's codon facts from the per-variant sequences, or record why there are none.

    Every offset below is an offset of the parent, so `parent_key` is required.
    """
    if variants is None or COL_SEQUENCE not in variants.columns:
        return CodonAnalysis(scheme=None, absence_reason=CODON_ABSENT_NO_SEQUENCE)
    if parent_key is None:
        return CodonAnalysis(scheme=None, absence_reason=CODON_ABSENT_PARENT_UNIDENTIFIED)

    parent_rows = variants.filter(pl.col(COL_VARIANT) == parent_key)
    parent_sequence = parent_rows.item(0, COL_SEQUENCE) if parent_rows.height > 0 else None
    if not parent_sequence:
        return CodonAnalysis(scheme=None, absence_reason=CODON_ABSENT_NO_SEQUENCE)

    parent_codons = split_codons(str(parent_sequence))
    # Both halves of the frame guard: a bad length or an internal stop both mean the amplicon
    # does not start where triplet splitting assumes.
    if parent_codons is None or not translates_cleanly(parent_codons):
        return CodonAnalysis(scheme=None, absence_reason=CODON_ABSENT_PARENT_OUT_OF_FRAME)

    # Summed over the whole run: one library, and splitting by condition only thins the evidence.
    totals = dict(
        reads.group_by(COL_VARIANT)
        .agg(pl.col(COL_READS).sum().alias("total"))
        .iter_rows()
    )

    changes: dict[str, CodonChange] = {}
    observations: list[tuple[str, int]] = []
    for key, sequence in variants.select(COL_VARIANT, COL_SEQUENCE).iter_rows():
        if key == parent_key or not sequence:
            continue
        variant_codons = split_codons(str(sequence))
        if variant_codons is None:
            continue
        position = changed_codon(parent_codons, variant_codons)
        if position is None:
            continue
        codon = variant_codons[position]
        parent_residue = residue(parent_codons[position])
        # Both must be real: two Nones comparing equal would make unknowns look synonymous.
        silent = parent_residue is not None and parent_residue == residue(codon)
        changes[key] = CodonChange(position=position, codon=codon, silent=silent)
        observations.append((position, codon, int(totals.get(key, 0))))

    if not observations:
        return CodonAnalysis(
            scheme=None,
            absence_reason=CODON_ABSENT_NO_SINGLE_CODON_VARIANTS,
            parent_codons=parent_codons,
        )

    scheme = infer_scheme(observations, min_fraction)
    if scheme is None:
        # Silent-variant answers survive — they need only the parent's codons. Only
        # reachability is lost.
        return CodonAnalysis(
            scheme=None,
            absence_reason=CODON_ABSENT_NOT_DEGENERATE,
            parent_codons=parent_codons,
            changes=changes,
        )

    return CodonAnalysis(
        scheme=scheme,
        absence_reason=None,
        parent_codons=parent_codons,
        reachable=reachable_positions(parent_codons, scheme),
        changes=changes,
    )


@dataclass(frozen=True)
class PositionAlignment:
    """The profiler's own position label for each of this block's codon offsets.

    Verified, never assumed: this block counts codons from zero, the profiler uses its own
    numbering, and being one out puts every value on the wrong residue while looking
    plausible. Checked by translating the parent's codons and demanding each label's residue
    agrees.
    """

    parent_id: str
    labels: tuple[str, ...]
    reason: str | None = None

    @property
    def verified(self) -> bool:
        return self.reason is None and len(self.labels) > 0


def align_positions(
    parent_codons: list[str],
    parent_ids: list[str],
    labels: list[str],
    residues: list[str],
) -> PositionAlignment:
    """Match this block's codon offsets to the profiler's position labels, or refuse.

    Inputs are the profiler's parent-residue table, column by column. Refusal costs the
    per-position output only.
    """
    distinct_parents = sorted(set(parent_ids))
    if len(distinct_parents) != 1:
        # The block assumes one parent throughout, so a multi-parent table is out of scope.
        return PositionAlignment("", (), POSITION_ALIGN_MULTIPLE_PARENTS)

    ordered = sorted(zip(labels, residues, strict=True), key=lambda pair: pair[0])
    # Numeric, because a lexical sort puts position 10 before position 2. Anything non-numeric
    # is a numbering this code does not understand.
    if not all(label.lstrip("-").isdigit() for label, _ in ordered):
        return PositionAlignment(distinct_parents[0], (), POSITION_ALIGN_NON_NUMERIC)
    ordered = sorted(ordered, key=lambda pair: int(pair[0]))

    if len(ordered) != len(parent_codons):
        return PositionAlignment(distinct_parents[0], (), POSITION_ALIGN_LENGTH_MISMATCH)

    for (label, residue_value), codon in zip(ordered, parent_codons, strict=True):
        if residue(codon) != residue_value:
            return PositionAlignment(distinct_parents[0], (), POSITION_ALIGN_RESIDUE_MISMATCH)

    return PositionAlignment(distinct_parents[0], tuple(label for label, _ in ordered))


def reachable_positions(parent_codons: list[str], scheme: CodonScheme) -> dict[int, bool]:
    """Per codon offset: whether the scheme holds a different codon encoding the same residue.

    False for a parent codon that is not a plain triplet or encodes a stop.
    """
    answers: dict[int, bool] = {}
    for position, parent_codon in enumerate(parent_codons):
        parent_residue = residue(parent_codon)
        if parent_residue is None or parent_residue == STOP:
            answers[position] = False
            continue
        answers[position] = any(
            codon != parent_codon and residue(codon) == parent_residue for codon in scheme.codons
        )
    return answers
