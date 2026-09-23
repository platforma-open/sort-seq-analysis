import type { GraphMakerState } from "@milaboratories/graph-maker";
import { kind } from "@platforma-open/milaboratories.sort-seq-analysis.kind";
import { createPlDataTableStateV2, DataModelBuilder } from "@platforma-sdk/model";
import type { BlockData } from "./types";

/**
 * The chart a condition's distribution page opens with. Takes a finished title because the
 * caller holds the drawn-variant count. Seeded once per condition, so an existing chart keeps
 * the title it was created with.
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
 * `readFloor` is absent rather than 0: absent applies no floor, where 0 would be one the block
 * invented. Later shape changes add `.migrate<Next>(...)` links rather than editing this.
 */
export const blockDataModel = new DataModelBuilder({ kind })
  .from<Omit<BlockData, "ntResultsTableState">>("Ver_2026_08_07")
  // Each of the two score tables keeps its own grid state; older blocks have only one.
  .migrate<BlockData>("Ver_2026_09_21", (previous) => ({
    ...previous,
    ntResultsTableState: createPlDataTableStateV2(),
  }))
  // The kind's init-params contract, field for field. `.templateParams(...)` in `index.ts`
  // projects the same fields back out; the two must name the same set. `params` is optional,
  // so every field keeps a default.
  .init(({ params }) => ({
    conditionColumnRef: params?.conditionColumnRef,
    gateColumnRef: params?.gateColumnRef,
    sortFractionColumnRef: params?.sortFractionColumnRef,
    gateOrder: params?.gateOrder ?? [],
    gateValues: params?.gateValues ?? [],
    gateColumnLabel: params?.gateColumnLabel,
    conditionValues: params?.conditionValues ?? [],

    // Not init params — see the kind. The two facts and the baseline are absent rather than
    // defaulted: an absent input means no enrichment, and an absent order flag means ordered.
    excludedConditions: [],
    customBlockLabel: "",
    resultsTableState: createPlDataTableStateV2(),
    ntResultsTableState: createPlDataTableStateV2(),
    distributionGraphStates: {},
  }));
