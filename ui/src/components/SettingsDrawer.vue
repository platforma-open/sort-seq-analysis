<script setup lang="ts">
/**
 * One control per argument. Two things are easy to "fix" wrongly:
 *
 * 1. The read-count floor is clearable — cleared IS the answer, and the normal first run.
 * 2. The gate order is seeded on the user's gesture, never by a watcher: a watcher on an
 *    output writing to `data` is the hairpin, and two clients would race.
 *
 * Picked gates, the input and excluded conditions are column value ids of their columns. One no
 * longer among the column's values stays picked and is shown as not available, with the reason
 * in a tooltip; only picking another column clears them.
 */
import { BASELINE_AVAILABLE } from "@platforma-open/milaboratories.sort-seq-analysis.model";
import type { ColumnUniversalId, ColumnValueId, ColumnValueOption } from "@platforma-sdk/model";
import {
  PlAccordion,
  PlAccordionSection,
  PlAlert,
  PlBtnGhost,
  PlDropdown,
  PlCheckbox,
  PlElementList,
  PlDropdownMulti,
  PlIcon24,
  PlNumberField,
  PlSlideModal,
  PlTooltip,
  PlValueLabel,
} from "@platforma-sdk/ui-vue";
import { computed, ref } from "vue";
import { useApp } from "../app";

const app = useApp();

const gateOrderOpen = ref(true);
const enrichmentOpen = ref(true);
const armsOpen = ref(true);

// Open state belongs to the parent, which mounts this beside the button that opens it.
const isOpen = defineModel<boolean>({ required: true });

/**
 * Values of a metadata column, as the model read them. `undefined` while they are not known, so
 * picks are not marked as not available before the model has caught up.
 */
function valueOptionsOf(column: ColumnUniversalId | undefined): ColumnValueOption[] | undefined {
  if (column === undefined) return undefined;
  return app.model.outputs.metadataValues?.find((entry) => entry.column === column)?.options;
}

/** The values of a column, in the order the model offers them. */
function valuesOf(column: ColumnUniversalId | undefined): ColumnValueId[] {
  return (valueOptionsOf(column) ?? []).map((option) => option.value);
}

const conditionValueOptions = computed(() => valueOptionsOf(app.model.data.conditionColumnRef));

/**
 * Every condition excluded leaves nothing to score: the run would produce no results, which
 * reads like a failed run.
 */
const everyConditionExcluded = computed(() => {
  const options = conditionValueOptions.value;
  if (options === undefined || options.length === 0) return false;
  return options.every((option) => app.model.data.excludedConditions.includes(option.value));
});

const gateValueOptions = computed(() => valueOptionsOf(app.model.data.gateColumnRef));

/** `undefined` means ordered, which is the ordinary case and every block made before this. */
const gatesOrdered = computed({
  get: () => app.model.data.gatesOrdered !== false,
  set: (value) => {
    app.model.data.gatesOrdered = value ? undefined : false;
  },
});

/**
 * The gate values that are NOT rungs — the reference cannot also be a gate the run ranks. So
 * the control offers what the gate-order list has had removed.
 */
const inputGateOptions = computed(() =>
  gateValueOptions.value?.filter((option) => !app.model.data.gateOrder.includes(option.value)),
);

/**
 * What `setGateColumn` seeds, minus the input gate — the input can never be a ranked gate, so
 * removing it is not a modification to offer undoing. `undefined` while the gate column's values
 * are not known, so a reset cannot wipe the order before they arrive.
 */
const defaultGateOrder = computed(() =>
  gateValueOptions.value
    ?.map((option) => option.value)
    .filter((value) => value !== app.model.data.inputGate),
);

const gateOrderModified = computed(() => {
  const current = app.model.data.gateOrder;
  const base = defaultGateOrder.value;
  if (base === undefined) return false;
  return current.length !== base.length || current.some((value, i) => value !== base[i]);
});

function resetGateOrder() {
  const base = defaultGateOrder.value;
  if (base !== undefined) app.model.data.gateOrder = [...base];
}

/** `undefined` before a dataset is picked, so an unknown grain never hides a valid option. */
const isNucleotide = computed(() => app.model.outputs.datasetIsNucleotide);

/**
 * The baseline is the parent's synonymous variants. `BaselineOption` carries two further values
 * the drawer does not offer, so a block already holding one keeps running.
 */
const synonymousBaseline = computed({
  get: () => app.model.data.baseline === "synonymous",
  set: (value) => {
    app.model.data.baseline = value ? "synonymous" : undefined;
    app.model.data.baselineSequence = undefined;
  },
});

/**
 * Offered only where the baseline can both be measured and reach a column: the nucleotide grain
 * gives it a set to measure, and an input gate gives it an enrichment to sit beside. Without the
 * input every baseline output is empty, so the control would be a no-op.
 *
 * `undefined` grain is not-yet-known, so the control stays until it settles rather than flickering
 * away and back.
 *
 * Hiding is the whole correction here: clearing `data.baseline` from a watcher on an output would
 * be the hairpin. The args projection drops it instead, so a stale value reaches no run.
 */
const baselineAvailableHere = computed(
  () => isNucleotide.value !== false && app.model.data.inputGate !== undefined,
);

function setAbundance(ref: ColumnUniversalId | undefined) {
  // The metadata columns are picked among those on the dataset's sample axis, so another
  // dataset's picks do not carry over.
  app.model.data.abundanceRef = ref;
  app.model.data.conditionColumnRef = undefined;
  app.model.data.gateColumnRef = undefined;
  app.model.data.sortFractionColumnRef = undefined;
  app.model.data.gateColumnLabel = undefined;
  app.model.data.gateOrder = [];
  app.model.data.excludedConditions = [];
  // The input is a gate-column value, so it dies with the column.
  app.model.data.inputGate = undefined;
  // The baseline needs the nucleotide grain, which is a property of the dataset — so a new one
  // cannot inherit the old one's answer.
  app.model.data.baseline = undefined;
  app.model.data.baselineSequence = undefined;
}

function setConditionColumn(ref: ColumnUniversalId | undefined) {
  // The exclusions are values of the old column.
  app.model.data.conditionColumnRef = ref;
  app.model.data.excludedConditions = [];
}

function setGateColumn(ref: ColumnUniversalId | undefined) {
  app.model.data.gateColumnRef = ref;
  // The label too: only the option list knows it, and the subtitle derives from `data` alone.
  app.model.data.gateColumnLabel = app.model.outputs.gateOptions?.find(
    (option) => option.value === ref,
  )?.label;
  // Seed the order from the column; a previous ordering is meaningless against a new column.
  app.model.data.gateOrder = valuesOf(ref);
  // Same gesture, same reason: the old input was a value of the old column.
  app.model.data.inputGate = undefined;
}
</script>

<template>
  <PlSlideModal v-model="isOpen" close-on-outside-click shadow>
    <template #title>Settings</template>

    <!-- 1. The anchor. Until one is picked, no other input has an option list. -->
    <PlDropdown
      :model-value="app.model.data.abundanceRef"
      :options="app.model.outputs.abundanceOptions"
      label="Select dataset"
      required
      clearable
      @update:model-value="setAbundance"
    >
      <template #tooltip>
        The sequenced sort-seq run; every setting below comes from its sample annotations.
      </template>
    </PlDropdown>

    <!-- Together because picking the column is what populates the list. -->
    <PlDropdown
      :model-value="app.model.data.gateColumnRef"
      :options="app.model.outputs.gateOptions"
      label="Gate column"
      required
      clearable
      @update:model-value="setGateColumn"
    >
      <template #tooltip>
        Which sort gate each sample was collected from. A gate collected more than once at one
        condition has its replicates' reads pooled, and the run statistics say so.
      </template>
    </PlDropdown>

    <!-- The ordering IS the signal: a wrong order inverts every score and nothing downstream
         re-checks it. A drag list makes a duplicate or skipped rank impossible to express.

         The list is also the gate selection: removing a value takes it out of the run and the
         ranks close up behind it. -->

    <PlAccordion v-if="app.model.data.gateOrder.length > 0" multiple>
      <PlAccordionSection v-model="gateOrderOpen" label="Gates">
        <!-- The first of the two facts. Off, the list below is a selection and nothing that
             claims an order is emitted. -->
        <PlCheckbox v-model="gatesOrdered">
          Gates are ordered
          <PlTooltip class="info" position="top">
            <template #tooltip> Gates are sorted low to high signal </template>
          </PlTooltip>
        </PlCheckbox>

        <div style="display: flex; margin-bottom: -15px">
          {{ gatesOrdered ? "Define gate order from low to high" : "Gates to include" }}
          <PlTooltip class="info">
            <template #label>{{
              gatesOrdered ? "Define gate order from low to high" : "Gates to include"
            }}</template>
            <template #tooltip>
              Remove any value that is not a sort gate — an unsorted input, a specificity or
              stability arm — and its samples take no part in the run.
            </template>
          </PlTooltip>
        </div>
        <PlElementList v-model:items="app.model.data.gateOrder">
          <template #item-title="{ item }">
            <PlValueLabel :value="item" :options="gateValueOptions" />
          </template>
        </PlElementList>
        <PlBtnGhost v-if="gateOrderModified" @click="resetGateOrder">
          Reset to default
          <template #append>
            <PlIcon24 name="reverse" />
          </template>
        </PlBtnGhost>
      </PlAccordionSection>
    </PlAccordion>

    <!-- What the two facts add up to. Replaces the mode control: it states the consequence
         rather than asking the user to pick it. -->
    <PlAlert v-if="app.model.outputs.runShape" :type="app.model.outputs.runShape.level">
      {{ app.model.outputs.runShape.message }}
    </PlAlert>

    <PlAccordion multiple>
      <PlAccordionSection v-model="armsOpen" label="Arms">
        <!-- The factor column and its exclusions, together. -->
        <PlDropdown
          :model-value="app.model.data.conditionColumnRef"
          :options="app.model.outputs.conditionOptions"
          label="Factor column"
          required
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

        <PlAlert v-if="everyConditionExcluded" type="warn">
          Every level is excluded, so the run would produce no results. Keep at least one.
        </PlAlert>
      </PlAccordionSection>
    </PlAccordion>

    <PlAccordion multiple>
      <PlAccordionSection v-model="enrichmentOpen" label="Per-Gate Enrichment">
        <!-- Always offered: naming an input is what asks for the enrichment. -->
        <PlDropdown
          v-model="app.model.data.inputGate"
          :options="inputGateOptions"
          label="Unsorted input"
          clearable
        >
          <template #tooltip>
            The gate value holding your unsorted library. Optional — naming one adds the per-gate
            enrichment against it. It cannot be one of the gates above.
          </template>
        </PlDropdown>

        <PlCheckbox v-if="BASELINE_AVAILABLE && baselineAvailableHere" v-model="synonymousBaseline">
          Per-position baseline
          <PlTooltip class="info" position="top">
            <template #tooltip>
              Measured from the parent's synonymous variants — same protein, different DNA — at each
              position. Gives the mutation map a reference value for the parent residue.
            </template>
          </PlTooltip>
        </PlCheckbox>
      </PlAccordionSection>
    </PlAccordion>

    <!-- Both default to absent, and absent is an answer rather than an unset field: no
         correction, and no floor. Neither is needed for a first run. -->
    <PlAccordionSection label="Advanced Settings">
      <PlDropdown
        v-model="app.model.data.sortFractionColumnRef"
        :options="app.model.outputs.sortFractionOptions"
        label="Sort-fraction column"
        clearable
      >
        <template #tooltip>
          Per-gate normalized cell yield. Corrects for gates that collected unequal numbers of
          cells, which would otherwise look enriched for every variant. Leave empty and the score is
          computed uncorrected.
        </template>
      </PlDropdown>

      <PlNumberField
        v-model="app.model.data.readFloor"
        label="Read-count floor"
        :minimum="0"
        :step="1"
        clearable
      >
        <template #tooltip>
          Drops variants with too few reads to give a meaningful gate profile. For the per-gate
          enrichment it counts the variant's reads in the unsorted input instead. Leave empty to
          score every variant with reads in at least one gate.
        </template>
      </PlNumberField>
    </PlAccordionSection>
  </PlSlideModal>
</template>
