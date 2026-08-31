"""Sort-seq analysis — the block's score computation.

One binary entrypoint, invoked once per run. Its interface is fixed by
`computation-interface`:

    --reads     the per-sample x per-variant table          (required)
    --variants  the per-variant mutation-count table        (optional; absent,
                binScore is produced at no condition)
    --params    the parameter document                      (required)
    --out-dir   where score files and the manifest are written   (required)

One invocation covers every condition. Nothing outside the arithmetic is per-condition —
parent row, mutation count, parameters and runenv are all shared — so per-condition calls
would multiply startup, leave the caller merging N manifests, and make the one-condition
case a loop's degenerate iteration.

**Diagnostics go to both streams, and that is deliberate.** They serve two different
readers. Stdout is the run's audit trail: the block saves it as a log stream and the UI
shows it, so the successful-run summary belongs there. Stderr is what the platform reads
back when the command fails — the k8s runner fills the error dialog's "Latest output"
from the stderr file alone. A refusal printed only to stdout therefore reaches the user
as a blank "exited with code 1", with the reason sitting in a log panel nobody was told
to open. So a refusal is written to both: stdout because it is part of the run's record,
stderr because it is the failure the platform is about to report.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from errors import Refusal
from io_layer import read_reads, read_variants
from params import load_params
from pipeline import run


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="facs-bin-score",
        description="Score protein variants from a sort-seq (FACS bin) experiment.",
    )
    parser.add_argument("--reads", required=True, type=Path, help="per-sample x per-variant table (TSV)")
    parser.add_argument(
        "--variants",
        type=Path,
        default=None,
        help="per-variant mutation-count table (TSV); omit where no mutation count is available",
    )
    parser.add_argument("--params", required=True, type=Path, help="parameter document (JSON)")
    parser.add_argument("--out-dir", required=True, type=Path, help="directory for score files and the manifest")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    params = load_params(args.params)
    reads = read_reads(args.reads, params.sort_fraction_column)
    variants = read_variants(args.variants)

    try:
        manifest = run(reads, variants, params, args.out_dir)
    except Refusal as refusal:
        # A data-value violation. Exit non-zero naming the offending values, having written
        # no file — nothing partial is produced.
        #
        # Both streams, per the module docstring: stdout keeps the run's record complete,
        # stderr is the only stream the platform quotes back in the error it shows.
        message = f"REFUSED: {refusal}"
        print(message)
        print(message, file=sys.stderr)
        return 1

    _report(manifest)
    return 0


def _report(manifest: dict) -> None:
    """Echo what the run did, so stdout carries the audit trail.

    The same facts are in the manifest the caller reads; printing them means a failed or
    surprising run can be understood from the log alone.
    """
    if manifest["parentIdentified"]:
        print("Parent row: identified")
    else:
        reason = manifest["parentAbsenceReason"]
        detail = reason if reason is not None else "no mutation-count table supplied"
        print(f"Parent row: not identified ({detail})")

    for entry in manifest["pooledGroups"]:
        samples = " + ".join(entry["samples"])
        line = (
            f"Pooled condition {entry['condition']!r} gate {entry['gate']!r}: "
            f"{len(entry['samples'])} samples merged ({samples})"
        )
        if entry.get("sortFractionsDiffer"):
            line += " — WARNING: replicates supplied different sort fractions; averaged"
        print(line)

    for entry in manifest["conditions"]:
        gates = ", ".join(f"{gate['gate']}={gate['depth']}" for gate in entry["gatesCollected"])
        summary = (
            f"Condition {entry['condition']!r}: "
            f"{entry['variantsScored']} variants scored; "
            f"gates (pre-floor depths) {gates}; "
            f"binScore {'absent' if entry['binScoreFile'] is None else entry['referenceMode']}; "
            f"sort-yield corrected: {str(entry['sortYieldCorrected']).lower()}"
        )
        if entry["sortFractionSum"] is not None:
            summary += f"; fraction sum {entry['sortFractionSum']}"
        print(summary)


if __name__ == "__main__":
    sys.exit(main())
