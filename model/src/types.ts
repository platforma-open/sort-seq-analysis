import type { GraphMakerState } from "@milaboratories/graph-maker";
import type { PlDataTableStateV2, PlRef, SUniversalPColumnId } from "@platforma-sdk/model";

/**
 * What the workflow consumes — seven arguments and no others. The count is part of the claim:
 * no certainty statistic, no per-gate threshold, no parent-variant key. An eighth is a spec
 * change, not an implementation detail.
 */
export type BlockArgs = {
  /** 1. The dataset selection that anchors every other input. */
  abundanceRef: PlRef;
  /** 2. A per-sample metadata column, picked from the option list. */
  conditionColumnRef: SUniversalPColumnId;
  /** 3. A per-sample metadata column, picked for the other role. */
  gateColumnRef: SUniversalPColumnId;
  /**
   * 4. A rank per **selected** gate, along the binding axis. Ranks are contiguous from 1.
   *
   * Derived from `BlockData.gateOrder` by position — the workflow and the computation want a
   * value → rank map, the user wants to drag a list.
   *
   * The key set doubles as the run's gate scope: a value of the gate column absent from this
   * map is not a rung on the ladder, and its samples take no part in the run. A gate column
   * that also names an unsorted input or a specificity arm is the ordinary case, not an
   * incomplete configuration.
   */
  gateRanks: Record<string, number>;
  /** 5. Absent (empty) means every distinct value of the condition column is a condition. */
  excludedConditions: string[];
  /** 6. Absent means **no floor is applied** — not a floor of zero, and not a guess. */
  readFloor?: number;
  /** 7. Absent means the score is computed **uncorrected**, declared on every value. */
  sortFractionColumnRef?: SUniversalPColumnId;
};

/**
 * The unified data the user edits. Shaped on the UI's terms, projected to `BlockArgs` by
 * the args lambda — view state never crosses.
 */
export type BlockData = {
  // --- The seven arguments, in argument order ------------------------------
  abundanceRef?: PlRef;
  conditionColumnRef?: SUniversalPColumnId;
  gateColumnRef?: SUniversalPColumnId;
  /**
   * The selected gates in declared order, weakest binder first.
   *
   * A list rather than a value → rank map because the control is drag-to-reorder and position
   * *is* the rank, which makes a duplicated rank and a rank naming an absent value
   * unrepresentable rather than merely refused.
   *
   * Seeded with every value the gate column carries when the column is picked, and then
   * **narrowed by the user**: removing a gate takes it out of the run. It need not cover
   * `gateValues`, only be non-empty and name nothing outside it.
   */
  gateOrder: string[];
  excludedConditions: string[];
  /** `undefined` applies no floor at all, and is the normal first run. */
  readFloor?: number;
  sortFractionColumnRef?: SUniversalPColumnId;

  // --- Snapshots of the picked columns' distinct values ---------------------
  //
  // The args lambda sees only `data`, but two of its validations need a picked column's
  // *values*, which only a PFrame fetch produces. So the UI writes the ref and the values it
  // implies in one user gesture.
  //
  // Deliberately allowed to go stale if upstream re-emits the column and the user does not
  // re-pick: keeping it fresh means a watcher on an output writing back to shared data, whose
  // multi-client race costs more than the staleness. The computation re-derives the real
  // values anyway.
  /** Distinct values of the picked gate column, at the moment it was picked. */
  gateValues: string[];
  /**
   * Only the option list knows a column's label, and that list is an output — so deriving the
   * subtitle from it in a watcher would be output → data. Snapshotting keeps the subtitle a
   * pure function of `data`.
   */
  gateColumnLabel?: string;
  /** Distinct values of the picked condition column, at the moment it was picked. */
  conditionValues: string[];

  /** The user's override for the block subtitle. Empty means use the derived label. */
  customBlockLabel: string;

  // --- Pure view state. Never projected. ------------------------------------
  //
  // The settings drawer's open state is deliberately absent: it must close when a run starts,
  // which means reacting to an output, and writing that back to shared data is the hairpin. It
  // lives in a local Vue ref instead.
  resultsTableState: PlDataTableStateV2;
  /**
   * One chart state per condition, so re-templating one arm leaves the others alone.
   *
   * Which condition a page shows is deliberately not here — it is in the route, and so
   * per-client. Held in `data` it would be shared, and two people would fight over which arm
   * is on screen.
   */
  distributionGraphStates: Record<string, GraphMakerState>;
};

/** One gate a condition collected, with its depth taken **before** the floor. */
export type GateCollected = {
  gate: string;
  depth: number;
};

/** The manifest's per-condition entry. */
export type ConditionSummary = {
  /** Verbatim, exactly as it appears in the metadata column. */
  condition: string;
  gateRankMeanFile: string;
  /** Null where the column is not produced at this condition. */
  binScoreFile: string | null;
  readDistributionFile: string;
  /** Null where `binScore` is not produced. */
  referenceMode: "referenced" | "cancelled" | null;
  gatesCollected: GateCollected[];
  variantsScored: number;
  /**
   * Of the `variantsScored` total, how many the distribution draws — one series per variant, so
   * it is cut to the highest-scoring few. Reported only in that view's title, where a truncated
   * chart would otherwise be indistinguishable from a complete one.
   */
  variantsPlotted: number;
  /** As applied, reported from inside the computation rather than from the arguments. */
  sortYieldCorrected: boolean;
  /** Null in the uncorrected mode. A sum short of 1.0 is legitimate. */
  sortFractionSum: number | null;
};

/**
 * The manifest — the only thing the caller reads to know what the run produced. Whether
 * `binScore` exists at a condition, in which reference mode, and whether the correction was
 * applied are held only here.
 */
export type RunManifest = {
  parentIdentified: boolean;
  /**
   * Which of the two reasons applied, or null — null also covers the case where there was
   * no mutation-count table at all, which is a third state rather than a reason.
   */
  parentAbsenceReason: string | null;
  conditions: ConditionSummary[];
};
