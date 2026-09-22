"""The parameter document carrying the whole run configuration.

The shape below is the workflow's side of the interface:

    gateRanks           each *selected* gate value -> its integer rank, contiguous from 1.
                        The key set is the run's gate scope: a value of the gate column
                        absent from it is not a rung on the ladder and its samples are
                        dropped. Coverage of the column is neither required nor checked.
    excludedConditions  condition values to drop; empty where none are excluded
    readFloor           a non-negative integer, or null for no floor
    sortFractionColumn  the reads-table column carrying frac_cb, or null for uncorrected
    mode                "gate-ranking" or "enrichment"; absent means gate-ranking
    inputGate           the gate value naming the unsorted reference. Enrichment mode only,
                        and required there.
    baseline            "wild-type", "synonymous" or "sequence"; null for no baseline
    baselineSequence    the variant key the "sequence" baseline names; null otherwise

The input is a gate VALUE, not a sample, so one parameter gives every condition its own
reference with no condition-to-sample map to keep in step.

Strict about shape, silent about policy: an unknown field or wrong type raises, but a null
`readFloor` or `sortFractionColumn` is a real answer, not a missing value.

An absent optional key means exactly what an explicit null means — Tengo has no JSON null
literal and omits fields instead, so only `gateRanks` is required.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from constants import (
    BASELINE_OPTIONS,
    BASELINE_SEQUENCE,
    RUN_MODE_ENRICHMENT,
    RUN_MODE_GATE_RANKING,
)

_REQUIRED_FIELDS = frozenset({"gateRanks"})
_OPTIONAL_FIELDS = frozenset(
    {
        "excludedConditions",
        "readFloor",
        "sortFractionColumn",
        "mode",
        "inputGate",
        "baseline",
        "baselineSequence",
    }
)
_KNOWN_FIELDS = _REQUIRED_FIELDS | _OPTIONAL_FIELDS

_RUN_MODES = frozenset({RUN_MODE_GATE_RANKING, RUN_MODE_ENRICHMENT})


@dataclass(frozen=True)
class Params:
    """The run configuration, validated for shape."""

    gate_ranks: dict[str, int]
    excluded_conditions: frozenset[str]
    read_floor: int | None
    sort_fraction_column: str | None
    mode: str
    input_gate: str | None
    baseline: str | None
    baseline_sequence: str | None

    @property
    def scores_enrichment(self) -> bool:
        """Whether this run produces a per-gate enrichment. The single place the mode token
        becomes a behaviour, so a third mode lands here and not in five branches."""
        return self.mode == RUN_MODE_ENRICHMENT

    @property
    def sort_yield_corrected(self) -> bool:
        """Whether this run applies the sort-yield correction. A property of the run, never
        of a condition — no run mixes modes.

        This is the intent; the manifest reports the correction as applied.
        """
        return self.sort_fraction_column is not None


def load_params(path: Path) -> Params:
    """Parse and shape-check the parameter document.

    Raises ValueError, which is a caller bug rather than a data refusal: the workflow writes
    this file itself.
    """
    with path.open(encoding="utf-8") as handle:
        raw = json.load(handle)

    if not isinstance(raw, dict):
        raise ValueError(f"parameter document must be a JSON object, got {type(raw).__name__}")

    missing = sorted(_REQUIRED_FIELDS - raw.keys())
    if missing:
        raise ValueError(f"parameter document is missing required field(s): {', '.join(missing)}")
    unknown = sorted(raw.keys() - _KNOWN_FIELDS)
    if unknown:
        raise ValueError(f"parameter document carries unknown field(s): {', '.join(unknown)}")

    gate_ranks = _parse_gate_ranks(raw["gateRanks"])
    mode = _parse_mode(raw.get("mode"))
    input_gate = _parse_input_gate(raw.get("inputGate"), mode, gate_ranks)
    baseline = _parse_baseline(raw.get("baseline"))

    return Params(
        gate_ranks=gate_ranks,
        excluded_conditions=_parse_excluded(raw.get("excludedConditions", [])),
        read_floor=_parse_read_floor(raw.get("readFloor")),
        sort_fraction_column=_parse_sort_fraction_column(raw.get("sortFractionColumn")),
        mode=mode,
        input_gate=input_gate,
        baseline=baseline,
        baseline_sequence=_parse_baseline_sequence(raw.get("baselineSequence"), baseline),
    )


def _parse_gate_ranks(value: object) -> dict[str, int]:
    if not isinstance(value, dict) or not value:
        raise ValueError("gateRanks must be a non-empty object mapping gate value -> integer rank")
    ranks: dict[str, int] = {}
    for gate, rank in value.items():
        # bool is an int subclass in Python and would silently rank a gate 0 or 1.
        if not isinstance(rank, int) or isinstance(rank, bool):
            raise ValueError(f"gateRanks[{gate!r}] must be an integer, got {rank!r}")
        ranks[str(gate)] = rank
    return ranks


def _parse_excluded(value: object) -> frozenset[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError("excludedConditions must be a list of strings (empty where none are excluded)")
    return frozenset(value)


def _parse_read_floor(value: object) -> int | None:
    # null is the no-floor run.
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"readFloor must be an integer or null, got {value!r}")
    if value < 0:
        # The block refuses this before the run; reaching here means a non-block caller.
        raise ValueError(f"readFloor must be non-negative, got {value}")
    return value


def _parse_sort_fraction_column(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ValueError(f"sortFractionColumn must be a non-empty string or null, got {value!r}")
    return value


def _parse_mode(value: object) -> str:
    # Absent is the gate-ranking run — a real answer, not a compatibility shim.
    if value is None:
        return RUN_MODE_GATE_RANKING
    if value not in _RUN_MODES:
        raise ValueError(f"mode must be one of {sorted(_RUN_MODES)} or null, got {value!r}")
    return str(value)


def _parse_input_gate(value: object, mode: str, gate_ranks: dict[str, int]) -> str | None:
    """The reference gate. Required in enrichment mode, refused outside it.

    Refused rather than ignored: silently dropping it would score the run against nothing
    while the settings said otherwise.
    """
    if mode != RUN_MODE_ENRICHMENT:
        if value is not None:
            raise ValueError(f"inputGate is meaningful only in {RUN_MODE_ENRICHMENT!r} mode, got {value!r}")
        return None

    if not isinstance(value, str) or not value:
        raise ValueError(f"{RUN_MODE_ENRICHMENT!r} mode requires inputGate to be a non-empty string, got {value!r}")

    # A gate cannot also be its own reference: every enrichment there would be exactly 1.
    if value in gate_ranks:
        raise ValueError(f"inputGate {value!r} is also a ranked gate; the reference cannot be a rung on the ladder")
    return value


def _parse_baseline(value: object) -> str | None:
    # Null is "report no baseline", which is an answer and not an unset field: a run may
    # legitimately want the enrichment values alone.
    if value is None:
        return None
    if value not in BASELINE_OPTIONS:
        raise ValueError(f"baseline must be one of {sorted(BASELINE_OPTIONS)} or null, got {value!r}")
    return str(value)


def _parse_baseline_sequence(value: object, baseline: str | None) -> str | None:
    if baseline != BASELINE_SEQUENCE:
        if value is not None:
            raise ValueError(f"baselineSequence is meaningful only with the {BASELINE_SEQUENCE!r} baseline")
        return None
    if not isinstance(value, str) or not value:
        raise ValueError(f"the {BASELINE_SEQUENCE!r} baseline requires baselineSequence, got {value!r}")
    return value
