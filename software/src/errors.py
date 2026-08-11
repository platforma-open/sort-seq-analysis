"""The one error type a caller is meant to see.

`validation-boundary` splits violations in two, and each rule is checked in exactly one
place. Configuration violations — a required argument absent, an anchor resolving to
nothing, the three metadata roles not distinct, an incomplete gate order, every
condition excluded, a negative floor — are refused by the block model before the run
starts and never arrive here.

What arrives here is the data-value class: a sort-fraction set breaking
`sort-fraction-values`, and more than one sample in a condition-and-gate group. Those
raise `Refusal`, which `main` turns into a non-zero exit that names the offending
values and writes no file.

A `Refusal` is therefore *not* an internal assertion. Anything raised as some other
exception type is a bug in this package or a caller violating the interface, and is
allowed to propagate with its traceback.
"""


class Refusal(Exception):
    """A data-value violation that stops the run. The message is user-facing."""
