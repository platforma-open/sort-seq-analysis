"""Literal names and tokens shared across the computation.

Input and output table headers are the workflow's side of the interface; changing one
here requires the matching change in the workflow.
"""

# --- Input table headers ----------------------------------------------------

COL_SAMPLE = "sampleId"
COL_VARIANT = "variantKey"
COL_READS = "reads"
COL_CONDITION = "condition"
COL_GATE = "gate"
COL_MUTATION_COUNT = "mutationCount"

# Optional; present only at nucleotide grain.
COL_SEQUENCE = "sequence"

# The `aaToNt` linker's answer, not derived here. Optional.
COL_PROTEIN = "proteinKey"

# The profiler's per-position parent residues, used to label this block's codon offsets.
# `parentId` is also the key of the optional variant -> parent table: a dataset may carry any
# number of parents, and every depth is taken within one.
COL_PARENT_ID = "parentId"
COL_POSITION_LABEL = "position"
COL_RESIDUE = "residue"

# Stands in for the parent on a run that resolved no parent link, so the per-parent group-by is
# degenerate rather than branched on.
PARENT_UNKNOWN = ""

# --- Output headers ---------------------------------------------------------

OUT_GATE_RANK_MEAN = "gateRankMean"
OUT_BIN_SCORE = "binScore"
OUT_GATE_FREQUENCY = "gateFrequency"
OUT_GATE_READS = "gateReads"
OUT_GATE_ENRICHMENT = "gateEnrichment"
OUT_INPUT_READS = "inputReads"
# The enrichment divided by its own parent's baseline level for that gate. 1.0 is a variant
# behaving like one of no effect — the same zero point on every gate, condition and parent.
OUT_ENRICHMENT_VS_BASELINE = "gateEnrichmentVsBaseline"

# `position` is this block's own codon offset, zero-based — NOT the profiler's position
# label. Aligning the two is `pipeline._align_positions`; being one out is undetectable
# downstream.
OUT_POSITION = "position"
OUT_BASELINE_LEVEL = "baselineLevel"
OUT_BASELINE_VARIANTS = "baselineVariants"

# `uncertainty` is max(SE_counting, SE_replicate), never their average, in the value's units.
OUT_UNCERTAINTY = "uncertainty"
OUT_NT_VARIANTS = "ntVariants"

# Stands in for a zero gate count in the enrichment's counting error only. Without it a
# measured zero has an error of exactly zero, which claims certainty from no reads.
ENRICHMENT_ZERO_READS_PSEUDOCOUNT = 0.5

# --- Output file names ------------------------------------------------------
# All must stay matchable by the file-set regexes below: the workflow collects them with
# saveFileSet(name, regex), not by name. `index` is the condition's position in the sorted
# retained list, never the condition value, which is arbitrary user data.

SCORE_FILE_PATTERN = "score_{quantity}_c{index}.tsv"
DISTRIBUTION_FILE_PATTERN = "dist_c{index}.tsv"
MANIFEST_FILE = "manifest.json"
# One row per parent for the whole run, keyed [parentId]. In the score set so it needs no
# second file set; the manifest names it.
PARENT_SUMMARY_FILE = "score_parentSummary.tsv"

# `rank` is the gate's declared rank, not its position among the gates this condition
# collected — otherwise one name would mean different gates in different conditions.
GATE_SCORE_FILE_PATTERN = "score_{quantity}_c{index}_g{rank}.tsv"

# The rolled-up protein level, emitted beside the measured level, not instead of it.
ROLLED_SCORE_FILE_PATTERN = "score_{quantity}_aa_c{index}.tsv"
ROLLED_GATE_SCORE_FILE_PATTERN = "score_{quantity}_aa_c{index}_g{rank}.tsv"

# Keyed on codon offset, not on a variant, so it gets its own file set.
BASELINE_FILE_PATTERN = "baseline_c{index}_g{rank}.tsv"
# The same baseline per gate, one row per parent. Keyed on [parentId] alone, so a dataset
# carrying several parents reports each — an annotation on the enrichment column can hold one.
BASELINE_GATE_FILE_PATTERN = "baseline_gate_c{index}_g{rank}.tsv"
# The baseline of `binScore` itself, one row per parent. Gate-ranking mode only, where the
# score is per condition rather than per gate.
BASELINE_BIN_SCORE_FILE_PATTERN = "baseline_binScore_c{index}.tsv"
BASELINE_FILE_SET_REGEX = r"^baseline_.*\.tsv$"

SCORE_FILE_SET_REGEX = r"^score_.*\.tsv$"
DISTRIBUTION_FILE_SET_REGEX = r"^dist_.*\.tsv$"

# --- Reference-mode tokens --------------------------------------------------

MODE_REFERENCED = "referenced"
MODE_CANCELLED = "cancelled"

PARENT_ABSENT_NO_ZERO = "no-variant-with-zero-mutation-count"
PARENT_ABSENT_MULTIPLE_ZERO = "multiple-variants-with-zero-mutation-count"

# --- Run modes --------------------------------------------------------------
# A report, not a setting: `enrichment` where an input was named. The rank metrics follow the
# gate order instead, so an ordered run with an input produces both families.

RUN_MODE_GATE_RANKING = "gate-ranking"
RUN_MODE_ENRICHMENT = "enrichment"

# --- Baseline options -------------------------------------------------------
# Wild type and a named sequence are single variants, so their spread is degenerate. Only
# the synonymous set is a population.

BASELINE_WILD_TYPE = "wild-type"
BASELINE_SYNONYMOUS = "synonymous"
BASELINE_SEQUENCE = "sequence"

BASELINE_OPTIONS = frozenset({BASELINE_WILD_TYPE, BASELINE_SYNONYMOUS, BASELINE_SEQUENCE})

BASELINE_ABSENT_NO_MUTATION_COUNT = "no-mutation-count-table"
BASELINE_ABSENT_PARENT_UNIDENTIFIED = "parent-not-identified"
BASELINE_ABSENT_NEEDS_NUCLEOTIDE = "synonymous-baseline-needs-nucleotide-grain"
BASELINE_ABSENT_NO_SYNONYMOUS = "no-synonymous-variants"
BASELINE_ABSENT_SEQUENCE_UNKNOWN = "named-sequence-absent-from-dataset"

# Percentiles, never a standard error: this is a population spread, and an SE over ~70
# variants is roughly 8x tighter than the spread it would be mistaken for.
BASELINE_PERCENTILES = (5, 25, 75, 95)

# --- Codon facts ------------------------------------------------------------

CODON_SIZE = 3

# Read share a base needs at one codon offset to be admitted to the inferred scheme.
# A judgment, but a wide one: NNK separates ~50% G / ~46% T from ~2% A / ~2% C at the third
# offset, so anything between 0.05 and 0.4 gives the same answer. The manifest reports the
# frequencies so a library that does not separate this cleanly is visible.
CODON_BASE_MIN_FRACTION = 0.10

# Distinct codons a position needs before it votes on the scheme. Each position votes once,
# so without this a position carrying a single sequencing error would vote as loudly as a
# fully-sampled one. Bounds the scheme call only; reachability and the baseline are unaffected.
CODON_POSITION_MIN_VARIANTS = 8

CODON_ABSENT_NO_SEQUENCE = "no-sequence-column"
CODON_ABSENT_PARENT_UNIDENTIFIED = "parent-not-identified"
CODON_ABSENT_PARENT_OUT_OF_FRAME = "parent-sequence-not-in-frame"
CODON_ABSENT_NO_SINGLE_CODON_VARIANTS = "no-single-codon-variants"
CODON_ABSENT_NOT_DEGENERATE = "no-degenerate-position-found"

# Any of these means no per-position output at all. Assuming the two numberings agree would
# put every value on the wrong residue.
POSITION_ALIGN_MULTIPLE_PARENTS = "more-than-one-parent"
POSITION_ALIGN_NON_NUMERIC = "position-labels-not-numeric"
POSITION_ALIGN_LENGTH_MISMATCH = "position-count-differs-from-codon-count"
POSITION_ALIGN_RESIDUE_MISMATCH = "parent-residues-disagree-with-translation"

# --- Sort fractions ---------------------------------------------------------
# Range and tolerance adopted from titeseq-analysis.

SORT_FRACTION_MIN = 0.0
SORT_FRACTION_MAX = 1.0
SORT_FRACTION_SUM_TOLERANCE = 1e-3

# Display bound on the read-distribution view only; the scored set is unaffected. The
# manifest records how much was cut.
DISTRIBUTION_TOP_N = 20
