import type { GraphMakerState } from "@milaboratories/graph-maker";
import type { PlDataTableStateV2, PlRef, SUniversalPColumnId } from "@platforma-sdk/model";

/**
 * One word for what the run did, **derived** by the computation from whether an input was
 * named. It is a report, never an input — nothing configures a mode.
 */
export type RunMode = "gate-ranking" | "enrichment";

/** What a per-gate enrichment is read against. `synonymous` needs the nucleotide grain. */
export type BaselineOption = "wild-type" | "synonymous" | "sequence";

/**
 * What the workflow consumes. Fields 8-11 are omitted rather than defaulted on a gate-ranking
 * run, so an existing block's args keep their exact bytes.
 */
export type BlockArgs = {
  /** 1. The dataset selection that anchors every other input. */
  abundanceRef: PlRef;
  /** 2. A per-sample metadata column, picked from the option list. */
  conditionColumnRef: SUniversalPColumnId;
  /** 3. A per-sample metadata column, picked for the other role. */
  gateColumnRef: SUniversalPColumnId;
  /**
   * 4. A rank per selected gate, contiguous from 1, derived from `gateOrder` by position.
   *
   * The key set doubles as the run's gate scope: a gate-column value absent from it takes no
   * part in the run, which is the ordinary case rather than an incomplete configuration.
   */
  gateRanks: Record<string, number>;
  /** 5. Absent (empty) means every distinct value of the condition column is a condition. */
  excludedConditions: string[];
  /** 6. Absent means **no floor is applied** — not a floor of zero, and not a guess. */
  readFloor?: number;
  /** 7. Absent means the score is computed **uncorrected**, declared on every value. */
  sortFractionColumnRef?: SUniversalPColumnId;

  /**
   * 8. Whether the gates lie along a binding axis. Absent means they do. False drops the rank
   * metrics and keeps the enrichment.
   */
  gatesOrdered?: boolean;
  /**
   * 9. The gate-column value naming the unsorted reference. Optional: naming one is what asks
   * for the enrichment. Never a key of `gateRanks` — a gate that referenced itself would give
   * exactly 1 everywhere.
   */
  inputGate?: string;
  /** 10. Absent means report no baseline, which is an answer and not an unset field. */
  baseline?: BaselineOption;
  /** 11. The variant key the `sequence` baseline names. Set only with that option. */
  baselineSequence?: string;
};

/** What the user edits. Projected to `BlockArgs` by the args lambda; view state never crosses. */
export type BlockData = {
  // --- The seven arguments, in argument order ------------------------------
  abundanceRef?: PlRef;
  conditionColumnRef?: SUniversalPColumnId;
  gateColumnRef?: SUniversalPColumnId;
  /**
   * The selected gates in declared order, weakest binder first. A list, not a rank map, so
   * position IS the rank and a duplicate rank is unrepresentable. Seeded from the column then
   * narrowed by the user; removing a gate takes it out of the run.
   */
  gateOrder: string[];
  excludedConditions: string[];
  /** `undefined` applies no floor at all, and is the normal first run. */
  readFloor?: number;
  sortFractionColumnRef?: SUniversalPColumnId;

  // --- The two facts, plus the baseline -------------------------------------
  //
  // The run is read off these: an input turns the enrichment on, the order turns the rank
  // metrics on. There is no mode.
  /** `undefined` means ordered, which is the ordinary case. */
  gatesOrdered?: boolean;
  /** The gate value serving as the unsorted reference. Only meaningful in enrichment mode. */
  inputGate?: string;
  /** `undefined` reports no baseline. */
  baseline?: BaselineOption;
  /** The variant key for the `sequence` baseline. */
  baselineSequence?: string;

  // --- Snapshots of the picked columns' distinct values ---------------------
  //
  // The args lambda sees only `data`, but two validations need a picked column's VALUES, which
  // only a PFrame fetch produces — so the UI writes ref and values in one gesture.
  //
  // Allowed to go stale: keeping it fresh means a watcher on an output writing back to shared
  // data, and the computation re-derives the real values anyway.
  /** Distinct values of the picked gate column, at the moment it was picked. */
  gateValues: string[];
  /** Snapshotted so the subtitle stays a pure function of `data`: only the option list knows a
   *  column's label, and that list is an output. */
  gateColumnLabel?: string;
  /** Distinct values of the picked condition column, at the moment it was picked. */
  conditionValues: string[];

  /** The user's override for the block subtitle. Empty means use the derived label. */
  customBlockLabel: string;

  // --- Pure view state. Never projected. ------------------------------------
  //
  // The drawer's open state is deliberately absent — it must close on an output change, which
  // would be the hairpin. It lives in a local Vue ref.
  resultsTableState: PlDataTableStateV2;
  /**
   * The nucleotide table's own grid state. Separate because the two tables hold different
   * columns on different axes. Required rather than optional: `v-model` bound to `undefined`
   * writes grid state into nothing and loses it on reload.
   */
  ntResultsTableState: PlDataTableStateV2;
  /**
   * The baseline table's grid state. Its own, because that table is keyed on `[parentId]` and
   * shares no column with either score table.
   */
  /** One chart state per condition. Which condition is on screen lives in the route instead,
   *  so two clients do not fight over it. */
  distributionGraphStates: Record<string, GraphMakerState>;
};

/** One gate a condition collected, with its depth taken **before** the floor. */
export type GateCollected = {
  gate: string;
  depth: number;
};

/** One condition-and-gate group whose reads were pooled across several samples. */
export type PooledGroup = {
  condition: string;
  gate: string;
  /** Sample **ids**, sorted. The UI resolves them to labels via `sampleLabelPframe`. */
  samples: string[];
  /** Replicates supplied different fractions and were averaged. Absent when uncorrected. */
  sortFractionsDiffer?: boolean;
};

/**
 * A baseline as measured at one gate. `spread` is percentiles and deliberately carries no
 * standard error: an SE shrinks as √n and describes the mean, where a threshold needs the
 * scatter of the variants themselves.
 */
export type BaselineSummary = {
  /** The median: a ratio has a long tail, so a mean would sit where no cell does. */
  level: number;
  spread: { p5: number; p25: number; p75: number; p95: number };
  /** How many baseline variants survived the floor at this gate and backed the numbers above. */
  variants: number;
};

/** One gate's enrichment file, and the baseline measured beside it. */
export type GateEnrichment = {
  /** Verbatim, as the condition is — this value lands in a domain key a consumer matches on. */
  gate: string;
  /** The gate's declared rank, which is also the suffix in the file name. */
  rank: number;
  file: string;
  /** Whether the file carries the vs-baseline column. It needs a resolved, non-zero level. */
  hasVsBaseline: boolean;
  variantsEnriched: number;
  /** Null where no baseline was resolved, or where none of its variants survived the floor here. */
  baseline: BaselineSummary | null;
  /**
   * The baseline split by codon position, as a TSV file name. Null outside the synonymous
   * option. Keyed on this block's own zero-based codon offset, NOT the profiler's position
   * axis; one out puts every baseline on the wrong residue and looks plausible.
   */
  /**
   * The same baseline per gate, one row per parent, keyed on `[parentId]`. Emitted on every
   * run: the annotations above can describe one baseline, and a dataset may carry several
   * parents.
   */
  baselineGateFile: string | null;
  baselinePositionFile: string | null;
  /** How many codon positions carried a value, so a thin split is visible without opening it. */
  baselinePositions: number;
};

/**
 * The library's degenerate codon, inferred from the run's own reads rather than declared.
 * Inferred per codon offset, so each call rests on every read in the run.
 *
 * `baseFrequencies` is how a human checks it: wide separation between offsets means the
 * inference holds, narrow separation means it should not be trusted on that run.
 */
export type CodonSchemeSummary = {
  identified: boolean;
  /** Why none could be inferred, or null. Null also covers the ordinary protein-grain run. */
  absenceReason: string | null;
  /** The scheme in the notation people use for it, e.g. `"NNK"`. Null where none was inferred. */
  label: string | null;
  codons: string[];
  /** One map per codon offset: base -> share of reads. */
  baseFrequencies: Record<string, number>[];
  reads: number;
  positionsTotal: number;
  positionsReachable: number;
  /**
   * Codon offsets that cannot carry a synonymous change, zero-based — the cells a heat map
   * should leave blank. NOT aligned to the profiler's position axis.
   */
  unreachablePositions: number[];
};

/**
 * One parent the run scored. A dataset may carry any number — the profiler takes a FASTA of
 * them — and every depth is taken within one, so each resolves its own parent row, codon
 * scheme and baseline.
 */
export type ParentSummary = {
  /** Null for variants the parent link did not place. They are scored among themselves. */
  parentId: string | null;
  variants: number;
  reads: number;
  parentIdentified: boolean;
  parentAbsenceReason: string | null;
  baselineIdentified: boolean;
  baselineAbsenceReason: string | null;
  baselineVariants: number;
  codonScheme: CodonSchemeSummary;
  positionAlignment: { verified: boolean; reason: string | null; parentId: string | null };
};

/**
 * The protein level, where the run could reach it. Emitted beside the measured level rather
 * than instead of it.
 *
 * It carries no baseline band: the synonymous variants are pooled into the parent protein, so
 * at this grain there is no set left to measure noise from. The band stays on the nucleotide
 * level, where it was measured.
 */
export type RolledSummary = {
  gateRankMeanFile: string;
  /** Null outside gate-ranking mode, where `binScore` is not produced. */
  binScoreFile: string | null;
  referenceMode: "referenced" | "cancelled" | null;
  gateEnrichments: GateEnrichment[];
  variantsScored: number;
};

/** The manifest's per-condition entry. */
export type ConditionSummary = {
  /** Verbatim, exactly as it appears in the metadata column. */
  condition: string;
  gateRankMeanFile: string;
  /** Null where the column is not produced at this condition. */
  binScoreFile: string | null;
  /**
   * The noise band on `binScore`, one row per parent. Gate-ranking mode only — the score is
   * per condition there, so its baseline is one number rather than one per gate.
   */
  binScoreBaselineFile: string | null;
  readDistributionFile: string;
  /** Null where `binScore` is not produced. */
  referenceMode: "referenced" | "cancelled" | null;
  gatesCollected: GateCollected[];
  /** The reference's depth, or null outside enrichment mode. Zero is distinct from null:
   *  input rows exist but carry no reads. */
  inputDepth: number | null;
  /** Empty outside enrichment mode, and where the condition had no usable reference. */
  gateEnrichments: GateEnrichment[];
  /** The protein level, or null where the run could not reach it. */
  rolled: RolledSummary | null;
  variantsScored: number;
  /** How many of `variantsScored` the distribution draws. Shown in that view's title, where a
   *  truncated chart is otherwise indistinguishable from a complete one. */
  variantsPlotted: number;
  /** As applied, reported from inside the computation rather than from the arguments. */
  sortYieldCorrected: boolean;
  /** Null in the uncorrected mode. A sum short of 1.0 is legitimate. */
  sortFractionSum: number | null;
};

/** The manifest — the only thing the caller reads to know what the run produced. */
export type RunManifest = {
  mode: RunMode;
  parentIdentified: boolean;
  /** Null also covers "no mutation-count table at all", which is a third state, not a reason. */
  parentAbsenceReason: string | null;
  /** Chosen once for the run; how much survived the floor is per gate. */
  baselineOption: BaselineOption | null;
  baselineIdentified: boolean;
  /** Why none could be resolved, or null. Each value names a different thing to fix. */
  baselineAbsenceReason: string | null;
  baselineVariants: number;
  /** Inferred once for the run. */
  codonScheme: CodonSchemeSummary;
  /**
   * Every parent the run scored. One entry is the ordinary case; the top-level fields above
   * are that parent's. With several, those fields are the conjunction and these carry each.
   */
  parents: ParentSummary[];
  /**
   * The gate ladder, already rendered: `"1 = NEG, 2 = MP, ..."`. Ordered weakest first, so a
   * consumer can say what a mean bin of 2.6 means. Empty where the gates carry no order.
   */
  gateLadder: string;
  /** Retained conditions only; empty on a run with no replicates. */
  pooledGroups: PooledGroup[];
  conditions: ConditionSummary[];
};
