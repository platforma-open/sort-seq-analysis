"""The parameter document: one structured document carrying the whole run configuration.

Shape is fixed by `computation-interface`:

    gateRanks           each distinct value of the gate column -> its integer rank
    excludedConditions  condition values to drop; empty where none are excluded
    readFloor           a non-negative integer, or null for no floor
    sortFractionColumn  the reads-table column carrying frac_cb, or null for uncorrected

Reading it is deliberately strict about *shape* and deliberately silent about *policy*.
An unknown field or a wrong type is a caller bug and raises. But a `readFloor` of null
is not an error and not a missing value — `input-defaults` makes an unset floor an
answer: score every variant holding reads in at least one collected gate. Same for a
null `sortFractionColumn`: the run is uncorrected and says so on every value it emits.

**An absent optional key means exactly what an explicit null means.** Only `gateRanks` has
to be present. The workflow builds this document in Tengo, which has no JSON null literal —
it omits a field rather than nulling it — so a reader that demanded all four keys would
reject every uncorrected, unfloored run, which is the normal first run. The two spellings
are one meaning, and neither side has to know which the other chose.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

_REQUIRED_FIELDS = frozenset({"gateRanks"})
_OPTIONAL_FIELDS = frozenset({"excludedConditions", "readFloor", "sortFractionColumn"})
_KNOWN_FIELDS = _REQUIRED_FIELDS | _OPTIONAL_FIELDS


@dataclass(frozen=True)
class Params:
    """The run configuration, validated for shape."""

    gate_ranks: dict[str, int]
    excluded_conditions: frozenset[str]
    read_floor: int | None
    sort_fraction_column: str | None

    @property
    def sort_yield_corrected(self) -> bool:
        """Whether this run applies the sort-yield correction.

        `sort-fraction-values` makes the correction a property of the run rather than of
        a condition: requirement 1 admits no partial supply, so naming the column
        corrects every condition and omitting it corrects none. No run mixes modes.

        This is the *intent*; what the manifest reports is the correction **as applied**,
        which is read back from the computation rather than from here.
        """
        return self.sort_fraction_column is not None


def load_params(path: Path) -> Params:
    """Parse and shape-check the parameter document.

    Raises ValueError on a malformed document. That is a caller bug, not a data-value
    refusal — the workflow writes this file itself, so a bad shape means the workflow
    and this package disagree about their own interface.
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

    return Params(
        gate_ranks=_parse_gate_ranks(raw["gateRanks"]),
        excluded_conditions=_parse_excluded(raw.get("excludedConditions", [])),
        read_floor=_parse_read_floor(raw.get("readFloor")),
        sort_fraction_column=_parse_sort_fraction_column(raw.get("sortFractionColumn")),
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
    # null is the no-floor run, which `input-defaults` makes the normal first one.
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"readFloor must be an integer or null, got {value!r}")
    if value < 0:
        # A negative floor is a configuration violation the block refuses before the run
        # (`argument-surface`). Reaching here means a non-block caller; refuse on shape.
        raise ValueError(f"readFloor must be non-negative, got {value}")
    return value


def _parse_sort_fraction_column(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ValueError(f"sortFractionColumn must be a non-empty string or null, got {value!r}")
    return value
