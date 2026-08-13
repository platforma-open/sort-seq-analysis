<script setup lang="ts">
/**
 * The distribution chart for one condition.
 *
 * The condition comes from the route, not from `data`: every condition's section links here
 * and routes are keyed on the pathname alone, so one component serves them all. Keeping it in
 * the route makes the choice per-client, which is why there is no condition selector.
 *
 * `distributionPf` is an `outputWithStatus`, so GraphMaker draws its own not-ready and error
 * states. A `v-if` around it would replace those with a blank page.
 */
import type { GraphMakerState, PredefinedGraphOption } from "@milaboratories/graph-maker";
import { GraphMaker } from "@milaboratories/graph-maker";
// Only `GraphMaker` and types are exported from the package root; this runtime function is
// reachable solely through the `./*` wildcard, which maps literally and so needs the `.js`.
import { createDefaultMapping } from "@milaboratories/graph-maker/dist/dataBindAes.js";
import {
  defaultDistributionGraphState,
  distributionPlotTitle,
} from "@platforma-open/milaboratories.sort-seq-analysis.model";
import type { AxisSpec } from "@platforma-sdk/model";
import { PlAlert } from "@platforma-sdk/ui-vue";
import { computed, watch } from "vue";
import { useApp } from "../app";
import BlockPage from "../components/BlockPage.vue";
import { NOT_READY_TEXT } from "../text";

const app = useApp();

const condition = computed(() => app.queryParams.condition);

const plotTitle = computed(() =>
  distributionPlotTitle(
    condition.value ?? "",
    app.model.outputs.manifest?.conditions.find((entry) => entry.condition === condition.value),
  ),
);

/**
 * A re-run that excludes this condition removes its section, but a client already on the page
 * keeps the route. Without this the chart would just come back empty, reading as broken rather
 * than as an arm no longer in the run. `undefined` is not-yet-known, not stale.
 */
const isStaleCondition = computed(() => {
  const conditions = app.model.outputs.distributionConditions;
  if (conditions === undefined || condition.value === undefined) return false;
  return !conditions.includes(condition.value);
});

/**
 * Must match graph-maker's own key for this axis byte for byte: object keys sorted, and
 * `domain` always present — `{}` when the spec carries none.
 */
function gateAxisSourceKey(axis: AxisSpec): string {
  const domain = axis.domain ?? {};
  const sorted: Record<string, string> = {};
  for (const key of Object.keys(domain).sort()) sorted[key] = domain[key];
  return JSON.stringify({ domain: sorted, kind: "axis", name: axis.name, type: axis.type });
}

const gateAxis = computed((): AxisSpec | undefined => {
  const columns = app.model.outputs.distributionPfCols;
  if (!columns || condition.value === undefined) return undefined;
  const frequency = columns.find(
    (column) =>
      column.spec.name === "pl7.app/facsBin/gateFrequency" &&
      column.spec.domain?.["pl7.app/facsBin/condition"] === condition.value,
  );
  return frequency?.spec.axesSpec.find((axis) => axis.name === "pl7.app/facsBin/gate");
});

/**
 * Seed the chart state, then the gate order it draws in.
 *
 * Untouched, the chart sorts gate categories alphabetically, so `low/mid/high` reads in the
 * wrong order — the same class of error as an inverted score. For a discrete chart the order
 * lives in `dataBindAes[source].order`; `axesSettings.axisX.order` looks right but is only
 * reconciled for scatterplots. The entry must be **complete**, because every value in `order`
 * has its `mapping[value].aes` dereferenced whether or not the source is used for colour — so
 * an order without a matching mapping throws. `createDefaultMapping` returns both, in the
 * order given.
 *
 * The state has to exist before the binding below reads it: a getter that built a fresh
 * default per read handed GraphMaker a new object identity every tick and the chart never
 * settled, rendering blank. For the same reason both writes share one callback — as two
 * `immediate` watches, the order half would find no state on the first tick and never retry.
 *
 * Seeded once, so a user reordering gates in the chart keeps their choice; a gate the snapshot
 * missed is appended by graph-maker rather than lost. Watching the route and `data` rather
 * than an output keeps this clear of the hairpin.
 */
watch(
  [condition, gateAxis, () => app.model.data.gateOrder],
  ([conditionValue, axis, gateOrder]) => {
    if (conditionValue === undefined) return;

    const states = app.model.data.distributionGraphStates;
    states[conditionValue] ??= defaultDistributionGraphState(plotTitle.value);

    if (axis === undefined || gateOrder.length === 0) return;
    const state = states[conditionValue];
    const key = gateAxisSourceKey(axis);
    if (state.dataBindAes?.[key] !== undefined) return;

    states[conditionValue] = {
      ...state,
      dataBindAes: {
        ...state.dataBindAes,
        [key]: createDefaultMapping([...gateOrder], "light"),
      },
    };
  },
  { immediate: true },
);

const graphState = computed({
  get: (): GraphMakerState =>
    app.model.data.distributionGraphStates[condition.value ?? ""] ??
    defaultDistributionGraphState(""),
  set: (value: GraphMakerState) => {
    if (condition.value === undefined) return;
    app.model.data.distributionGraphStates[condition.value] = value;
  },
});

/**
 * The frame holds every condition's columns, so this condition's is picked out by the domain
 * key — the only thing telling one condition's pair from another's. Binding to specs rather
 * than names keeps it working whatever the upstream profiler called its variant grain.
 */
const defaultOptions = computed((): PredefinedGraphOption<"discrete">[] | undefined => {
  const columns = app.model.outputs.distributionPfCols;
  if (!columns || condition.value === undefined) return undefined;

  const frequency = columns.find(
    (column) =>
      column.spec.name === "pl7.app/facsBin/gateFrequency" &&
      column.spec.domain?.["pl7.app/facsBin/condition"] === condition.value,
  );
  if (!frequency) return undefined;

  const gateAxis = frequency.spec.axesSpec.find((axis) => axis.name === "pl7.app/facsBin/gate");
  const variantAxis = frequency.spec.axesSpec.find((axis) => axis.name !== "pl7.app/facsBin/gate");
  if (!gateAxis || !variantAxis) return undefined;

  // There is no `x` input for a discrete chart — categories go through primaryGrouping. Which
  // suits a gate rank: an ordinal with no calibrated spacing.
  return [
    { inputName: "y", selectedSource: frequency.spec },
    { inputName: "primaryGrouping", selectedSource: gateAxis },
    { inputName: "secondaryGrouping", selectedSource: variantAxis },
  ];
});
</script>

<template>
  <BlockPage :title="plotTitle" mode="graph">
    <PlAlert v-if="isStaleCondition" type="warn" label="This condition is not in the current run">
      The run no longer scores <strong>{{ condition }}</strong> — it is excluded, or the condition
      column changed. Pick another distribution from the sections list.
    </PlAlert>

    <!-- One component instance serves every condition, so without the key a switch between
         arms reuses the chart's mounted state against a different binding. -->
    <GraphMaker
      v-else
      :key="condition"
      v-model="graphState"
      :p-frame="app.model.outputs.distributionPf"
      chart-type="discrete"
      :default-options="defaultOptions"
      :status-text="{ noPframe: { title: NOT_READY_TEXT } }"
    />
  </BlockPage>
</template>
