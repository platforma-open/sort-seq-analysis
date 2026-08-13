"""Reading the two input tables and writing the score files, distribution files and manifest.

One thing here is load-bearing rather than plumbing: **the key and metadata columns are
read as strings, never inferred.** `condition-source` bars relabelling and requires a
retained condition value to be emitted verbatim as it appears in the column, and
`emitted-columns` puts that value in a domain key a consumer matches on. Type inference
would break that silently — a condition written `7.50` parses as a float and renders back
as `7.5`, so the domain value would match nothing in the source metadata column and the
failure would look like absent data rather than a renamed key.
"""

from __future__ import annotations

import json
from pathlib import Path

import polars as pl
from constants import (
    COL_CONDITION,
    COL_GATE,
    COL_MUTATION_COUNT,
    COL_READS,
    COL_SAMPLE,
    COL_VARIANT,
    DISTRIBUTION_FILE_PATTERN,
    MANIFEST_FILE,
    SCORE_FILE_PATTERN,
)

# Read as text, so what comes back out is byte-identical to what went in.
_STRING_COLUMNS = (COL_SAMPLE, COL_VARIANT, COL_CONDITION, COL_GATE)


def read_reads(path: Path, sort_fraction_column: str | None) -> pl.DataFrame:
    """The per-sample × per-variant table: sampleId, variantKey, reads, condition, gate,
    and the sort-fraction column where the run supplies one.

    `reads` is Int64 because it is a read count — the profiler's own `readCount` column.
    A fractional value here means the workflow exported the normalized abundance instead,
    which is the mistake the two-annotation abundance predicate exists to prevent, and
    failing loudly is the right response to it.
    """
    overrides: dict[str, pl.DataType] = {name: pl.String() for name in _STRING_COLUMNS}
    overrides[COL_READS] = pl.Int64()
    if sort_fraction_column is not None:
        overrides[sort_fraction_column] = pl.Float64()

    frame = pl.read_csv(path, separator="\t", schema_overrides=overrides)
    _require_columns(frame, path, [COL_SAMPLE, COL_VARIANT, COL_READS, COL_CONDITION, COL_GATE])
    return frame


def read_variants(path: Path | None) -> pl.DataFrame | None:
    """The per-variant mutation-count table, or None where the workflow omitted it.

    Omission is meaningful: the mutation-count predicate resolved to nothing, so `binScore`
    is produced at no condition while `gateRankMean` is unaffected. The workflow expresses
    that as a missing *table* rather than a nullable column precisely so no reader has to
    tell "no mutation count anywhere" from "none for this variant".
    """
    if path is None:
        return None
    frame = pl.read_csv(
        path,
        separator="\t",
        schema_overrides={COL_VARIANT: pl.String(), COL_MUTATION_COUNT: pl.Int64()},
    )
    _require_columns(frame, path, [COL_VARIANT, COL_MUTATION_COUNT])
    return frame


def _require_columns(frame: pl.DataFrame, path: Path, required: list[str]) -> None:
    missing = [name for name in required if name not in frame.columns]
    if missing:
        raise ValueError(
            f"{path.name} is missing required column(s): {', '.join(missing)} "
            f"(has: {', '.join(frame.columns)})"
        )


def score_file_name(quantity: str, index: int) -> str:
    return SCORE_FILE_PATTERN.format(quantity=quantity, index=index)


def distribution_file_name(index: int) -> str:
    return DISTRIBUTION_FILE_PATTERN.format(index=index)


def write_table(frame: pl.DataFrame, out_dir: Path, name: str) -> str:
    """Write one TSV and return its name for the manifest.

    An empty frame still writes its header. For a score file that is the true statement
    that no variant was scorable at this condition — which is different from the column
    not being produced, and the manifest distinguishes them with a null file name.
    """
    frame.write_csv(out_dir / name, separator="\t")
    return name


def write_manifest(manifest: dict, out_dir: Path) -> str:
    """Write the manifest — the only thing the caller reads to know what to construct.

    `sort_keys=False` on purpose: the per-condition list is already in sorted order and
    the field order matches `computation-interface`'s table, which makes the file readable
    when someone opens it to debug a run.
    """
    path = out_dir / MANIFEST_FILE
    with path.open("w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2, sort_keys=False)
        handle.write("\n")
    return MANIFEST_FILE
