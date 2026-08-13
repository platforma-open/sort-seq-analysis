<script setup lang="ts">
/**
 * One control per argument. Two things here are deliberate and easy to "fix" wrongly:
 *
 * 1. **The read-count floor is clearable.** Cleared *is* the answer — score every variant
 *    holding reads in at least one collected gate — and it is the normal first run. Making the
 *    field required would force the user to invent a number before the run has shown them the
 *    depth distribution that number depends on.
 *
 * 2. **Column values are snapshotted on the user's gesture, never by a watcher.** Writing
 *    `data.gateValues` from a watcher on an output would be a hairpin, and two clients racing
 *    on shared data interleave non-deterministically. Every write below sits in an explicit
 *    change handler.
 */
import type { SUniversalPColumnId } from "@platforma-sdk/model";
import { getSingleColumnData, type PObjectId } from "@platforma-sdk/model";
import {
  PlAccordion,
  PlAccordionSection,
  PlDropdown,
  PlElementList,
  PlDropdownMulti,
  PlDropdownRef,
  PlNumberField,
  PlSlideModal,
  PlTooltip,
  useWatchFetch,
} from "@platforma-sdk/ui-vue";
import { computed, ref } from "vue";
import { useApp } from "../app";

const app = useApp();

const gateOrderOpen = ref(true);

// Open state belongs to the parent, which mounts this beside the button that opens it.
const isOpen = defineModel<boolean>({ required: true });

/**
 * The distinct values of **every** metadata column, keyed by the anchored id the pickers
 * store.
 *
 * Keyed by ref rather than by role, because the snapshot has to be written in the same
 * gesture as the pick — so the values must already be in hand when the user chooses. Fetching
 * only the picked columns lags the gesture by a round trip: the snapshot writes an empty
 * list, and the gate-order control never appears.
 */
const valuesByRef = useWatchFetch(
  () => ({
    pframe: app.model.outputs.metadataColumnsPframe,
    columns: app.model.outputs.metadataColumns,
  }),
  async ({ pframe, columns }) => {
    const out: Record<string, string[]> = {};
    if (!pframe || !columns) return out;

    for (const column of columns) {
      const data = await getSingleColumnData(pframe, column.objectId as PObjectId);
      const raw: unknown[] = data?.data ?? [];
      const values = raw.filter((v): v is string | number => v !== null && v !== undefined);
      out[column.value] = [...new Set(values.map((v) => String(v)))].sort();
    }
    return out;
  },
);

function valuesFor(ref: SUniversalPColumnId | undefined): string[] {
  if (!ref) return [];
  return valuesByRef.value?.[ref] ?? [];
}

const conditionValueOptions = computed(() =>
  valuesFor(app.model.data.conditionColumnRef).map((value) => ({ value, label: value })),
);

const gateValues = computed(() => app.model.data.gateValues);

function setAbundance(ref: typeof app.model.data.abundanceRef) {
  // Changing the anchor invalidates every downstream pick: the metadata option lists are
  // resolved in the anchor's context, and a stored anchored id is meaningless against a
  // different anchor.
  app.model.data.abundanceRef = ref;
  app.model.data.conditionColumnRef = undefined;
  app.model.data.gateColumnRef = undefined;
  app.model.data.sortFractionColumnRef = undefined;
  app.model.data.conditionValues = [];
  app.model.data.gateValues = [];
  app.model.data.gateColumnLabel = undefined;
  app.model.data.gateOrder = [];
  app.model.data.excludedConditions = [];
}

function setConditionColumn(ref: SUniversalPColumnId | undefined) {
  // Both writes in one gesture: the ref, and the facts the args lambda will validate
  // against. The snapshot is intentionally allowed to go stale — re-picking refreshes it.
  app.model.data.conditionColumnRef = ref;
  app.model.data.conditionValues = valuesFor(ref);
  app.model.data.excludedConditions = [];
}

function setGateColumn(ref: SUniversalPColumnId | undefined) {
  app.model.data.gateColumnRef = ref;
  app.model.data.gateValues = valuesFor(ref);
  // The label too: only the option list knows it, and the block subtitle is derived from
  // `data` alone. Same gesture, so no watcher on an output is needed.
  app.model.data.gateColumnLabel = app.model.outputs.gateOptions?.find(
    (option) => option.value === ref,
  )?.label;
  // Seed the order with the column's own values. A different gate column has different
  // values, so any previous ordering is meaningless.
  app.model.data.gateOrder = valuesFor(ref);
}
</script>

<template>
  <PlSlideModal v-model="isOpen" close-on-outside-click shadow>
    <template #title>Settings</template>

    <!-- 1. The anchor. Until one is picked, no other input has an option list. -->
    <PlDropdownRef
      :model-value="app.model.data.abundanceRef"
      :options="app.model.outputs.abundanceOptions ?? []"
      label="Select dataset"
      clearable
      @update:model-value="setAbundance"
    >
      <template #tooltip>
        The sequenced sort-seq run; every setting below comes from its sample annotations.
      </template>
    </PlDropdownRef>

    <!-- The gate column and its order sit together: the order is meaningless without the
         column, and picking the column is what populates the list. -->
    <PlDropdown
      :model-value="app.model.data.gateColumnRef"
      :options="app.model.outputs.gateOptions ?? []"
      label="Gate column"
      clearable
      @update:model-value="setGateColumn"
    >
      <template #tooltip>
        Which sort gate each sample was collected from — one sample per gate per condition.
      </template>
    </PlDropdown>

    <!-- The ordering IS the signal: a silently wrong order inverts every score and nothing
         downstream re-checks it. A drag list makes the order the thing manipulated directly,
         and a duplicate or skipped rank impossible to express.

         The list is also the gate *selection*: removing a value takes it and its samples out
         of the run, and the ranks close up behind it. Seeded with every value the column
         carries, because a run that uses all of them should need no editing. -->

    <PlAccordion v-if="app.model.data.gateOrder.length > 0" multiple>
      <PlAccordionSection v-model="gateOrderOpen" label="Gate Order">
        <div style="display: flex; margin-bottom: -15px">
          Define gate order
          <PlTooltip class="info">
            <template #label>Define gate order</template>
            <template #tooltip>
              Weakest binder first — reversing this order inverts every score. Remove any value that
              is not a sort gate — an unsorted input, a specificity or stability arm — and its
              samples take no part in the run.
            </template>
          </PlTooltip>
        </div>
        <PlElementList v-model:items="app.model.data.gateOrder">
          <template #item-title="{ item }">{{ item }}</template>
        </PlElementList>
      </PlAccordionSection>
    </PlAccordion>

    <!-- The condition column and its exclusions, likewise together. -->
    <PlDropdown
      :model-value="app.model.data.conditionColumnRef"
      :options="app.model.outputs.conditionOptions ?? []"
      label="Factor column"
      clearable
      @update:model-value="setConditionColumn"
    >
      <template #tooltip>
        The variable separating your sorts into arms; each level is scored on its own.
      </template>
    </PlDropdown>

    <PlDropdownMulti
      v-model="app.model.data.excludedConditions"
      :options="conditionValueOptions"
      label="Exclude factors"
    >
      <template #tooltip>
        Levels to leave out, such as a failed sort; excluded levels produce no results.
      </template>
    </PlDropdownMulti>

    <!-- Absent means the score is computed uncorrected, declared on every value it emits. -->
    <PlDropdown
      v-model="app.model.data.sortFractionColumnRef"
      :options="app.model.outputs.sortFractionOptions ?? []"
      label="Sort-fraction column"
      clearable
      helper="Per-gate normalized cell yield. Absent, the score is computed uncorrected."
    >
      <template #tooltip>
        Corrects for gates that collected unequal numbers of cells, which would otherwise look
        enriched for every variant.
      </template>
    </PlDropdown>

    <!-- Clearable, and cleared is the answer — not a floor of zero. -->
    <PlNumberField
      v-model="app.model.data.readFloor"
      label="Read-count floor"
      :minimum="0"
      :step="1"
      clearable
      helper="Leave empty to score every variant with reads in at least one collected gate."
    >
      <template #tooltip>
        Drops variants with too few reads to give a meaningful gate profile.
      </template>
    </PlNumberField>
  </PlSlideModal>
</template>
