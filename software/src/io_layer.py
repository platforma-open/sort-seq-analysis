"""Reading the input tables and writing the score files, distribution files and manifest.

Key and metadata columns are read as strings, never inferred. Condition values are emitted
verbatim into a domain key: a condition written `7.50` would infer as a float and render
back as `7.5`, matching nothing in the source column.
"""

from __future__ import annotations

import json
from pathlib import Path

import polars as pl

from constants import (
    BASELINE_BIN_SCORE_FILE_PATTERN,
    BASELINE_FILE_PATTERN,
    BASELINE_GATE_FILE_PATTERN,
    COL_CONDITION,
    COL_GATE,
    COL_MUTATION_COUNT,
    COL_PARENT_ID,
    COL_POSITION_LABEL,
    COL_READS,
    COL_RESIDUE,
    COL_SAMPLE,
    COL_SEQUENCE,
    COL_VARIANT,
    DISTRIBUTION_FILE_PATTERN,
    GATE_SCORE_FILE_PATTERN,
    MANIFEST_FILE,
    ROLLED_GATE_SCORE_FILE_PATTERN,
    ROLLED_SCORE_FILE_PATTERN,
    SCORE_FILE_PATTERN,
)

# Read as text, so what comes back out is byte-identical to what went in.
_STRING_COLUMNS = (COL_SAMPLE, COL_VARIANT, COL_CONDITION, COL_GATE)


def read_reads(path: Path, sort_fraction_column: str | None) -> pl.DataFrame:
    """The per-sample × per-variant table, plus the sort-fraction column where supplied.

    `reads` is Int64 deliberately: a fractional value means the workflow exported normalized
    abundance instead of read counts, and failing loudly is right.
    """
    wanted: dict[str, pl.DataType] = {name: pl.String() for name in _STRING_COLUMNS}
    wanted[COL_READS] = pl.Int64()
    if sort_fraction_column is not None:
        wanted[sort_fraction_column] = pl.Float64()

    # Overrides are narrowed to columns the file actually has. A `schema_overrides` dict whose
    # length happens to equal the file's column count is applied BY POSITION, so one override
    # naming an absent column silently renames the last real one.
    # `infer_schema=False` is required, not tidiness: the probe would otherwise infer types
    # from the first chunk and refuse the file it is only being asked to name the columns of —
    # a `condition` of 5.5 and 7.5 infers as float and then chokes on the input arm's `NA`.
    present = pl.read_csv(path, separator="\t", n_rows=0, infer_schema=False).columns
    overrides = {name: dtype for name, dtype in wanted.items() if name in present}

    frame = pl.read_csv(path, separator="\t", schema_overrides=overrides)
    # The sort-fraction column is deliberately not required here: `validate` refuses its
    # absence with a message naming the column, and owns that rule.
    _require_columns(frame, path, [COL_SAMPLE, COL_VARIANT, COL_READS, COL_CONDITION, COL_GATE])
    return frame


def read_variants(path: Path | None) -> pl.DataFrame | None:
    """The per-variant mutation-count table, or None where the workflow omitted it.

    A missing table, not a nullable column, so "no mutation count anywhere" never has to be
    told from "none for this variant". Omission means `binScore` is produced nowhere.
    """
    if path is None:
        return None
    frame = pl.read_csv(
        path,
        separator="\t",
        schema_overrides={COL_VARIANT: pl.String(), COL_MUTATION_COUNT: pl.Int64()},
    )
    _require_columns(frame, path, [COL_VARIANT, COL_MUTATION_COUNT])

    # Cast where present rather than named above: polars refuses an override for a missing
    # column, and its absence is the ordinary amino-acid-grain run.
    if COL_SEQUENCE in frame.columns:
        frame = frame.with_columns(pl.col(COL_SEQUENCE).cast(pl.String()))
    return frame


def read_positions(path: Path | None) -> pl.DataFrame | None:
    """The per-position parent residues, or None where the profiler column did not resolve.

    `position` is text: it lands in an axis a consumer joins on, so `007` must stay `007`.
    """
    if path is None:
        return None
    frame = pl.read_csv(
        path,
        separator="\t",
        schema_overrides={
            COL_PARENT_ID: pl.String(),
            COL_POSITION_LABEL: pl.String(),
            COL_RESIDUE: pl.String(),
        },
    )
    _require_columns(frame, path, [COL_PARENT_ID, COL_POSITION_LABEL, COL_RESIDUE])
    return frame


def read_parents(path: Path | None) -> pl.DataFrame | None:
    """Variant -> the parent it was aligned to, or None where the linker did not resolve.

    A variant listed under more than one parent is dropped: the aligner assigns a sequence to
    one parent, so two rows mean two profiler runs reached one bundle, and picking either would
    scope that variant's depths to a library it is not part of.
    """
    if path is None:
        return None
    frame = pl.read_csv(
        path,
        separator="\t",
        schema_overrides={COL_VARIANT: pl.String(), COL_PARENT_ID: pl.String()},
    )
    _require_columns(frame, path, [COL_VARIANT, COL_PARENT_ID])
    mapping = frame.select(COL_VARIANT, COL_PARENT_ID).unique()
    ambiguous = (
        mapping.group_by(COL_VARIANT).agg(pl.len().alias("_n")).filter(pl.col("_n") > 1)
    )
    if ambiguous.height > 0:
        mapping = mapping.join(ambiguous.select(COL_VARIANT), on=COL_VARIANT, how="anti")
    return mapping.sort(COL_VARIANT)


def _require_columns(frame: pl.DataFrame, path: Path, required: list[str]) -> None:
    missing = [name for name in required if name not in frame.columns]
    if missing:
        raise ValueError(
            f"{path.name} is missing required column(s): {', '.join(missing)} "
            f"(has: {', '.join(frame.columns)})"
        )


def score_file_name(quantity: str, index: int) -> str:
    return SCORE_FILE_PATTERN.format(quantity=quantity, index=index)


def gate_score_file_name(quantity: str, index: int, rank: int) -> str:
    """One file per (condition, gate). `rank` is the gate's declared rank, not its position
    among the gates this condition collected — see `GATE_SCORE_FILE_PATTERN`."""
    return GATE_SCORE_FILE_PATTERN.format(quantity=quantity, index=index, rank=rank)


def rolled_score_file_name(quantity: str, index: int) -> str:
    """The protein-level counterpart of `score_file_name`."""
    return ROLLED_SCORE_FILE_PATTERN.format(quantity=quantity, index=index)


def rolled_gate_score_file_name(quantity: str, index: int, rank: int) -> str:
    """The protein-level counterpart of `gate_score_file_name`."""
    return ROLLED_GATE_SCORE_FILE_PATTERN.format(quantity=quantity, index=index, rank=rank)


def baseline_file_name(index: int, rank: int) -> str:
    """The per-position baseline for one (condition, gate). Its own prefix, because it is the
    only output not keyed on the variant axis — see `BASELINE_FILE_PATTERN`."""
    return BASELINE_FILE_PATTERN.format(index=index, rank=rank)


def baseline_gate_file_name(index: int, rank: int) -> str:
    """The per-gate baseline for one (condition, gate), one row per parent, keyed [parentId]."""
    return BASELINE_GATE_FILE_PATTERN.format(index=index, rank=rank)


def baseline_bin_score_file_name(index: int) -> str:
    """The baseline of `binScore` for one condition, one row per parent."""
    return BASELINE_BIN_SCORE_FILE_PATTERN.format(index=index)


def distribution_file_name(index: int) -> str:
    return DISTRIBUTION_FILE_PATTERN.format(index=index)


def write_table(frame: pl.DataFrame, out_dir: Path, name: str) -> str:
    """Write one TSV and return its name for the manifest.

    An empty frame still writes its header: no variant was scorable here, which differs from
    the column not being produced (a null file name in the manifest).
    """
    frame.write_csv(out_dir / name, separator="\t")
    return name


def write_manifest(manifest: dict, out_dir: Path) -> str:
    """Write the manifest — the only thing the caller reads to know what to construct.

    `sort_keys=False` keeps the declared field order, which makes the file readable when
    someone opens it to debug a run.
    """
    path = out_dir / MANIFEST_FILE
    with path.open("w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2, sort_keys=False)
        handle.write("\n")
    return MANIFEST_FILE
