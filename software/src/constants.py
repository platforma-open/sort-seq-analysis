"""Literal names and tokens shared across the computation.

Every string a caller can observe is defined here once: the input table headers the
workflow writes, the output headers it imports, the manifest field names, and the two
reference-mode tokens. Nothing here is a choice this module is free to make — the
headers are the workflow's side of `computation-interface`, and the tokens come from
`../dms-analysis#bin-score-formula`.
"""

# ---------------------------------------------------------------------------
# Input table headers — written by the workflow's tsvFileBuilder (stage 2).
# ---------------------------------------------------------------------------

COL_SAMPLE = "sampleId"
COL_VARIANT = "variantKey"
COL_READS = "reads"
COL_CONDITION = "condition"
COL_GATE = "gate"
COL_MUTATION_COUNT = "mutationCount"

# ---------------------------------------------------------------------------
# Output headers — read back by the workflow's xsv.importFile (stage 3). Each score
# file carries the variant key and one value column; the value column is named after
# the quantity so the import schema is trivial on the other side.
# ---------------------------------------------------------------------------

OUT_GATE_RANK_MEAN = "gateRankMean"
OUT_BIN_SCORE = "binScore"
OUT_GATE_FREQUENCY = "gateFrequency"
OUT_GATE_READS = "gateReads"

# ---------------------------------------------------------------------------
# Output file names. The manifest names every file, so these patterns are internal —
# but they must stay regex-matchable, because the workflow collects them with
# exec's saveFileSet(name, regex) rather than by naming each file up front.
#
# The per-condition suffix is the condition's index in the sorted retained list, never
# the condition value itself: a condition value is arbitrary user data and may contain
# anything, including path separators. Sorting makes the index deterministic, which
# pure-template dedup depends on.
# ---------------------------------------------------------------------------

SCORE_FILE_PATTERN = "score_{quantity}_c{index}.tsv"
DISTRIBUTION_FILE_PATTERN = "dist_c{index}.tsv"
MANIFEST_FILE = "manifest.json"

SCORE_FILE_SET_REGEX = r"^score_.*\.tsv$"
DISTRIBUTION_FILE_SET_REGEX = r"^dist_.*\.tsv$"

# ---------------------------------------------------------------------------
# Reference-mode tokens. Plain scalars, per `selectable-distinction-matchability`:
# a consumer matches on these in a domain key, so they are never encoded structures.
# ---------------------------------------------------------------------------

MODE_REFERENCED = "referenced"
MODE_CANCELLED = "cancelled"

# Manifest values for why a parent could not be identified. `parent-row-identification`
# permits one mechanism — a single variant whose amino-acid mutation count is zero — so
# there are exactly two ways it fails.
PARENT_ABSENT_NO_ZERO = "no-variant-with-zero-mutation-count"
PARENT_ABSENT_MULTIPLE_ZERO = "multiple-variants-with-zero-mutation-count"

# ---------------------------------------------------------------------------
# Sort-fraction constraints, per `sort-fraction-values`. The tolerance and the range
# are adopted from titeseq-analysis rather than derived — both are shipped and tested
# there, and a second tolerance for the same quantity would fork this block from
# working code for no gain. 1e-3 is also the right order for four fractions rounded to
# three decimals on a sorter report.
# ---------------------------------------------------------------------------

SORT_FRACTION_MIN = 0.0
SORT_FRACTION_MAX = 1.0
SORT_FRACTION_SUM_TOLERANCE = 1e-3

# ---------------------------------------------------------------------------
# How many variants the read-distribution view draws.
#
# The distribution is one series per variant, and a saturation library has thousands of
# scored variants — every one of them a line on one chart. So the emission is cut to the
# highest-scoring few per condition. This is a display bound, which is why it lives here
# as a constant rather than becoming an eighth block argument: `argument-surface` fixes
# the argument count at seven, and the number of lines a chart reads well at is not a
# property of the experiment.
#
# The full scored set is unaffected — it is what the score columns and the results table
# carry. Only this view is cut, and the manifest records by how much.
# ---------------------------------------------------------------------------

DISTRIBUTION_TOP_N = 20
