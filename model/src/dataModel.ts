import type { GraphMakerState } from "@milaboratories/graph-maker";
import { kind } from "@platforma-open/milaboratories.sort-seq-analysis.kind";
import {
  createPlDataTableStateV2,
  DataModelBuilder,
  isColumnUniversalId,
  isColumnValueId,
} from "@platforma-sdk/model";
import { toColumnId } from "./abundance";
import type { BlockDataV1, BlockDataV2 } from "./stored_data";
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
  .from<BlockDataV1>("Ver_2026_08_07")
  // Each of the two score tables keeps its own grid state; older blocks have only one.
  .migrate<BlockDataV2>("Ver_2026_09_21", (previous) => ({
    ...previous,
    ntResultsTableState: createPlDataTableStateV2(),
  }))
  // Columns become result-pool ids and the picked values column value ids.
  .migrate<BlockData>("Ver_2026_10_21", toColumnIds)
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

// Internals

/**
 * Moves stored data to column ids. A ref to an upstream output becomes the result-pool id of that
 * output, which names the same block and column. The condition, gate and sort-fraction columns
 * were picked by ids anchored against the dataset and the gates, excluded conditions and input
 * gate stored as plain values; neither names the block that produced the metadata, so they
 * cannot become column ids and column value ids and are dropped, to be picked again. The
 * snapshots of the gate and condition columns' values were plain values too and go with their
 * columns; the next pick of a column writes its snapshot again.
 */
function toColumnIds(data: BlockDataV2): BlockData {
  const column = (stored: string | undefined) => (isColumnUniversalId(stored) ? stored : undefined);
  const value = (picked: string | undefined) => (isColumnValueId(picked) ? picked : undefined);
  const conditionColumnRef = column(data.conditionColumnRef);
  const gateColumnRef = column(data.gateColumnRef);
  return {
    ...data,
    abundanceRef: data.abundanceRef === undefined ? undefined : toColumnId(data.abundanceRef),
    conditionColumnRef,
    gateColumnRef,
    sortFractionColumnRef: column(data.sortFractionColumnRef),
    // The label and the snapshots describe their column, so they go with it.
    gateColumnLabel: gateColumnRef === undefined ? undefined : data.gateColumnLabel,
    gateValues: gateColumnRef === undefined ? [] : data.gateValues.filter(isColumnValueId),
    conditionValues:
      conditionColumnRef === undefined ? [] : data.conditionValues.filter(isColumnValueId),
    gateOrder: data.gateOrder.filter(isColumnValueId),
    excludedConditions: data.excludedConditions.filter(isColumnValueId),
    inputGate: value(data.inputGate),
  };
}
