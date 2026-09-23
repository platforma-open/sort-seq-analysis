"""The parameter document carrying the whole run configuration.

The shape below is the workflow's side of the interface:

    gateRanks           each *selected* gate value -> its integer rank, contiguous from 1.
                        The key set is the run's gate scope: a value of the gate column
                        absent from it is not a rung on the ladder and its samples are
                        dropped. Coverage of the column is neither required nor checked.
    excludedConditions  condition values to drop; empty where none are excluded
    readFloor           a non-negative integer, or null for no floor
    sortFractionColumn  the reads-table column carrying frac_cb, or null for uncorrected
    gatesOrdered        whether the gates lie along a binding axis; absent means they do
    inputGate           the gate value naming the unsorted reference; absent means no
                        enrichment
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
)

_REQUIRED_FIELDS = frozenset({"gateRanks"})
_OPTIONAL_FIELDS = frozenset(
    {
        "excludedConditions",
        "readFloor",
        "sortFractionColumn",
        "gatesOrdered",
        "inputGate",
        "baseline",
        "baselineSequence",
    }
)
_KNOWN_FIELDS = _REQUIRED_FIELDS | _OPTIONAL_FIELDS



@dataclass(frozen=True)
class Params:
    """The run configuration, validated for shape."""

    gate_ranks: dict[str, int]
    excluded_conditions: frozenset[str]
    read_floor: int | None
    sort_fraction_column: str | None
    gates_ordered: bool
    input_gate: str | None
    baseline: str | None
    baseline_sequence: str | None

    @property
    def scores_enrichment(self) -> bool:
        """Whether this run produces a per-gate enrichment.

        Read off the data, not off a setting: an enrichment needs a reference, so naming one is
        the whole of what turns it on.
        """
        return self.input_gate is not None

    @property
    def scores_gate_rank(self) -> bool:
        """Whether this run produces the rank metrics.

        The other fact. Ranks only mean something along a binding axis, so an unordered gate set
        gets the enrichment and nothing that claims an order.
        """
        return self.gates_ordered

    @property
    def sort_yield_corrected(self) -> bool:
        """Whether this run applies the sort-yield correction. A property of the run, never
        of a condition.

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
    gates_ordered = _parse_gates_ordered(raw.get("gatesOrdered"))
    input_gate = _parse_input_gate(raw.get("inputGate"), gate_ranks)
    if not gates_ordered and input_gate is None:
        raise ValueError(
            "unordered gates and no inputGate leave nothing to compute: "
            "order the gates, or name an unsorted input"
        )
    baseline = _parse_baseline(raw.get("baseline"))

    return Params(
        gate_ranks=gate_ranks,
        excluded_conditions=_parse_excluded(raw.get("excludedConditions", [])),
        read_floor=_parse_read_floor(raw.get("readFloor")),
        sort_fraction_column=_parse_sort_fraction_column(raw.get("sortFractionColumn")),
        gates_ordered=gates_ordered,
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


def _parse_gates_ordered(value: object) -> bool:
    """Whether the gates lie along a binding axis. Absent means they do, which is every
    document written before the flag existed."""
    if value is None:
        return True
    if not isinstance(value, bool):
        raise ValueError(f"gatesOrdered must be a boolean or null, got {value!r}")
    return value


def _parse_input_gate(value: object, gate_ranks: dict[str, int]) -> str | None:
    """The reference gate. Optional: naming one is what turns the enrichment on."""
    if value is None:
        return None

    if not isinstance(value, str) or not value:
        raise ValueError(f"inputGate must be a non-empty string or null, got {value!r}")

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
