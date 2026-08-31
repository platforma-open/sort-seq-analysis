import type { GraphMakerState } from "@milaboratories/graph-maker";
import { kind } from "@platforma-open/milaboratories.sort-seq-analysis.kind";
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
export const blockDataModel = new DataModelBuilder({ kind })
  .from<BlockData>("Ver_2026_08_07")
  // The first group is the kind's init-params contract, field for field, and
  // `.templateParams(...)` in `index.ts` projects those same fields back out. The two are
  // inverses; a field one names and the other drops is configuration that survives creation
  // and vanishes on export.
  //
  // `params` is optional — a block may be created with no template — so every field keeps its
  // own default behind it.
  .init(({ params }) => ({
    conditionColumnRef: params?.conditionColumnRef,
    gateColumnRef: params?.gateColumnRef,
    sortFractionColumnRef: params?.sortFractionColumnRef,
    gateOrder: params?.gateOrder ?? [],
    gateValues: params?.gateValues ?? [],
    gateColumnLabel: params?.gateColumnLabel,
    conditionValues: params?.conditionValues ?? [],

    // Not init params. The dataset ref is project-scoped, the exclusions and the floor are
    // decisions taken against the data in front of you, and the rest is view state. See the
    // kind for the reasoning on each.
    excludedConditions: [],
    customBlockLabel: "",
    resultsTableState: createPlDataTableStateV2(),
    distributionGraphStates: {},
  }));
