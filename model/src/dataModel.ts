import type { GraphMakerState } from "@milaboratories/graph-maker";
import { createPlDataTableStateV2, DataModelBuilder } from "@platforma-sdk/model";
import type { BlockData } from "./types";

/**
 * The chart a condition's distribution page opens with.
 *
 * Takes a finished title because the caller is the one holding the drawn-variant count. Seeded
 * once per condition, so a chart that already has state keeps the title it was created with —
 * which only shows in exports, the page suppressing GraphMaker's own header.
 */
export function defaultDistributionGraphState(title: string): GraphMakerState {
  return {
    title,
    template: "line",
    // Left unset, the chart opens with its settings panel over the plot.
    currentTab: null,
  };
}

/**
 * `readFloor` is deliberately absent rather than 0: those are different runs. Absent applies no
 * floor at all, where 0 would be a floor the block invented.
 *
 * Later shape changes add `.migrate<Next>("Ver_…", prev => …)` links rather than editing this.
 */
export const blockDataModel = new DataModelBuilder().from<BlockData>("Ver_2026_08_07").init(() => ({
  gateOrder: [],
  excludedConditions: [],
  gateValues: [],
  customBlockLabel: "",
  conditionValues: [],
  resultsTableState: createPlDataTableStateV2(),
  distributionGraphStates: {},
}));
