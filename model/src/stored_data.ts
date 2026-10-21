import type { GraphMakerState } from "@milaboratories/graph-maker";
import type { PlDataTableStateV2, PlRef } from "@platforma-sdk/model";
import type { BaselineOption } from "./types";

/**
 * Data as stored at `Ver_2026_09_21`: the dataset as a ref to an upstream output, the condition,
 * gate and sort-fraction columns as ids anchored against the dataset, the picked gates, excluded
 * conditions and input gate as plain values, and the distinct values of the gate and condition
 * columns snapshotted when they were picked.
 */
export type BlockDataV2 = {
  abundanceRef?: PlRef;
  conditionColumnRef?: string;
  gateColumnRef?: string;
  gateOrder: string[];
  excludedConditions: string[];
  readFloor?: number;
  sortFractionColumnRef?: string;
  gatesOrdered?: boolean;
  inputGate?: string;
  baseline?: BaselineOption;
  baselineSequence?: string;
  gateValues: string[];
  gateColumnLabel?: string;
  conditionValues: string[];
  customBlockLabel: string;
  resultsTableState: PlDataTableStateV2;
  ntResultsTableState: PlDataTableStateV2;
  distributionGraphStates: Record<string, GraphMakerState>;
};

/** Data as stored at `Ver_2026_08_07`: the same shape, before the nucleotide table had a state. */
export type BlockDataV1 = Omit<BlockDataV2, "ntResultsTableState">;
