"""Sort-seq analysis — the block's score computation.

One binary entrypoint, invoked once per run:

    --reads     the per-sample x per-variant table          (required)
    --variants  the per-variant mutation-count table        (optional; absent,
                binScore is produced at no condition)
    --params    the parameter document                      (required)
    --out-dir   where score files and the manifest are written   (required)

One invocation covers every condition; nothing outside the arithmetic is per-condition.

Refusals are written to BOTH streams. Stdout is the run's audit trail the UI shows; stderr
is the only stream the platform quotes back in its error dialog, so a refusal printed only
to stdout reaches the user as a blank "exited with code 1".
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from errors import Refusal
from io_layer import read_positions, read_reads, read_variants
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
    parser.add_argument(
        "--positions",
        type=Path,
        default=None,
        help="per-position parent residues (TSV); omit where the profiler column was absent",
    )
    parser.add_argument("--params", required=True, type=Path, help="parameter document (JSON)")
    parser.add_argument("--out-dir", required=True, type=Path, help="directory for score files and the manifest")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    params = load_params(args.params)
    reads = read_reads(args.reads, params.sort_fraction_column)
    variants = read_variants(args.variants)
    positions = read_positions(args.positions)

    try:
        manifest = run(reads, variants, positions, params, args.out_dir)
    except Refusal as refusal:
        # Nothing partial is written. Both streams — see the module docstring.
        message = f"REFUSED: {refusal}"
        print(message)
        print(message, file=sys.stderr)
        return 1

    _report(manifest)
    return 0


def _report(manifest: dict) -> None:
    """Echo what the run did, so a surprising run can be understood from the log alone."""
    print(f"Mode: {manifest['mode']}")

    if manifest["parentIdentified"]:
        print("Parent row: identified")
    else:
        reason = manifest["parentAbsenceReason"]
        detail = reason if reason is not None else "no mutation-count table supplied"
        print(f"Parent row: not identified ({detail})")

    scheme = manifest["codonScheme"]
    if scheme["identified"]:
        print(
            f"Codon scheme: {scheme['label']} inferred from {scheme['reads']} reads — "
            f"{scheme['positionsReachable']} of {scheme['positionsTotal']} positions can carry "
            f"a synonymous change"
        )
        for offset, frequencies in enumerate(scheme["baseFrequencies"]):
            shown = ", ".join(f"{base} {fraction:.1%}" for base, fraction in frequencies.items())
            print(f"  codon base {offset + 1}: {shown}")
    elif scheme["absenceReason"] != "no-sequence-column":
        # A missing sequence column is the ordinary amino-acid-grain run and not worth a line.
        print(f"Codon scheme: not inferred ({scheme['absenceReason']})")

    if manifest["baselineOption"] is not None:
        if manifest["baselineIdentified"]:
            print(f"Baseline ({manifest['baselineOption']}): {manifest['baselineVariants']} variant(s)")
        else:
            print(f"Baseline ({manifest['baselineOption']}): not resolved ({manifest['baselineAbsenceReason']})")

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

        _report_enrichment(entry)


def _report_enrichment(entry: dict) -> None:
    """The per-gate enrichment lines for one condition, or the one line saying why none.

    The input's depth is always named: a thin reference is invisible in the ratios.
    """
    if entry["inputDepth"] is None:
        return

    if not entry["gateEnrichments"]:
        print(f"  no enrichment produced (input depth {entry['inputDepth']})")
        return

    print(f"  enrichment against input (depth {entry['inputDepth']}):")
    for gate in entry["gateEnrichments"]:
        line = f"    gate {gate['gate']!r} (rank {gate['rank']}): {gate['variantsEnriched']} variants"
        baseline = gate["baseline"]
        if baseline is None:
            line += "; no baseline"
        else:
            spread = baseline["spread"]
            line += (
                f"; baseline {baseline['level']:.4g}"
                f" [p5 {spread['p5']:.4g}, p95 {spread['p95']:.4g}]"
                f" from {baseline['variants']} variant(s)"
            )
        print(line)


if __name__ == "__main__":
    sys.exit(main())
