<script setup lang="ts">
/**
 * One control per argument. Two things are easy to "fix" wrongly:
 *
 * 1. The read-count floor is clearable — cleared IS the answer, and the normal first run.
 * 2. Column values are snapshotted on the user's gesture, never by a watcher: a watcher on an
 *    output writing to `data` is the hairpin, and two clients would race.
 */
import { BASELINE_AVAILABLE } from "@platforma-open/milaboratories.sort-seq-analysis.model";
import type { SUniversalPColumnId } from "@platforma-sdk/model";
import { getSingleColumnData, type PObjectId } from "@platforma-sdk/model";
import {
  PlAccordion,
  PlAccordionSection,
  PlAlert,
  PlBtnGhost,
  PlDropdown,
  PlCheckbox,
  PlElementList,
  PlDropdownMulti,
  PlDropdownRef,
  PlMaskIcon24,
  PlNumberField,
  PlSlideModal,
  PlTextField,
  PlTooltip,
  useWatchFetch,
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
 * Distinct values of EVERY metadata column, keyed by ref rather than role: the snapshot is
 * written in the same gesture as the pick, so the values must already be in hand. Fetching only
 * picked columns lags by a round trip and the gate-order control never appears.
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

/**
 * The run is read off two facts, not chosen. An enrichment needs a reference, so naming one
 * turns it on; ranks need an order, so the toggle below turns those on.
 */
const isEnrichment = computed(() => app.model.data.inputGate !== undefined);

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
  gateValues.value
    .filter((value) => !app.model.data.gateOrder.includes(value))
    .map((value) => ({ label: value, value })),
);

/**
 * What `setGateColumn` seeds, minus the input gate — the input can never be a ranked gate, so
 * removing it is not a modification to offer undoing.
 */
const defaultGateOrder = computed(() =>
  gateValues.value.filter((value) => value !== app.model.data.inputGate),
);

const gateOrderModified = computed(() => {
  const current = app.model.data.gateOrder;
  const base = defaultGateOrder.value;
  return current.length !== base.length || current.some((value, i) => value !== base[i]);
});

function resetGateOrder() {
  app.model.data.gateOrder = [...defaultGateOrder.value];
}

/** `undefined` before a dataset is picked, so an unknown grain never hides a valid option. */
const isNucleotide = computed(() => app.model.outputs.datasetIsNucleotide);

/**
 * The synonymous option is withheld on a protein-level dataset, where nothing would be
 * selected — the SDK option type has no per-option `disabled`.
 *
 * Except when it is already the current pick: a dropdown whose value matches no option renders
 * empty and looks broken. It stays listed, and the warning below says why it produces nothing.
 */
const baselineOptions = computed(() => {
  const options = [
    {
      label: "Wild-type sequence",
      value: "wild-type" as const,
      description: "The parent row. One variant, so no spread.",
    },
    {
      label: "Synonymous variants",
      value: "synonymous" as const,
      description: "Same protein, different nucleotides. Needs a nucleotide-level dataset.",
    },
    {
      label: "A specific nucleotide sequence",
      value: "sequence" as const,
      description: "One variant you name below.",
    },
  ];
  if (isNucleotide.value === false && app.model.data.baseline !== "synonymous") {
    return options.filter((option) => option.value !== "synonymous");
  }
  // Gate ranking takes only the synonymous option. The other two name a single variant, which
  // repeats the reference "Mean bin vs parent" already subtracts and adds no spread. The
  // current pick stays listed either way, or the dropdown renders empty and looks broken.
  if (!isEnrichment.value) {
    return options.filter(
      (option) => option.value === "synonymous" || option.value === app.model.data.baseline,
    );
  }
  return options;
});

/**
 * Shown rather than corrected: clearing `data.baseline` from a watcher on an output is the
 * hairpin. The run is not broken either — it produces no baseline and the manifest says why.
 */
const synonymousUnavailable = computed(
  () => app.model.data.baseline === "synonymous" && isNucleotide.value === false,
);

function setAbundance(ref: typeof app.model.data.abundanceRef) {
  // A stored anchored id is meaningless against a different anchor.
  app.model.data.abundanceRef = ref;
  app.model.data.conditionColumnRef = undefined;
  app.model.data.gateColumnRef = undefined;
  app.model.data.sortFractionColumnRef = undefined;
  app.model.data.conditionValues = [];
  app.model.data.gateValues = [];
  app.model.data.gateColumnLabel = undefined;
  app.model.data.gateOrder = [];
  app.model.data.excludedConditions = [];
  // The input is a gate-column value, so it dies with the column. The mode and baseline are
  // what the user is measuring and survive a change of dataset.
  app.model.data.inputGate = undefined;
}

function setConditionColumn(ref: SUniversalPColumnId | undefined) {
  // Ref and snapshot in one gesture. The snapshot may go stale; re-picking refreshes it.
  app.model.data.conditionColumnRef = ref;
  app.model.data.conditionValues = valuesFor(ref);
  app.model.data.excludedConditions = [];
}

function setGateColumn(ref: SUniversalPColumnId | undefined) {
  app.model.data.gateColumnRef = ref;
  app.model.data.gateValues = valuesFor(ref);
  // The label too: only the option list knows it, and the subtitle derives from `data` alone.
  app.model.data.gateColumnLabel = app.model.outputs.gateOptions?.find(
    (option) => option.value === ref,
  )?.label;
  // Seed the order from the column; a previous ordering is meaningless against a new column.
  app.model.data.gateOrder = valuesFor(ref);
  // Same gesture, same reason: the old input was a value of the old column.
  app.model.data.inputGate = undefined;
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
      required
      clearable
      @update:model-value="setAbundance"
    >
      <template #tooltip>
        The sequenced sort-seq run; every setting below comes from its sample annotations.
      </template>
    </PlDropdownRef>

    <!-- Together because picking the column is what populates the list. -->
    <PlDropdown
      :model-value="app.model.data.gateColumnRef"
      :options="app.model.outputs.gateOptions ?? []"
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
          <template #item-title="{ item }">{{ item }}</template>
        </PlElementList>
        <PlBtnGhost v-if="gateOrderModified" @click="resetGateOrder">
          Reset to default
          <template #append>
            <PlMaskIcon24 name="reverse" />
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
          :options="app.model.outputs.conditionOptions ?? []"
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
      </PlAccordionSection>
    </PlAccordion>

    <PlAccordion multiple>
      <PlAccordionSection v-model="enrichmentOpen" label="Per-Gate Enrichment">
        <!-- Always offered: naming an input is what asks for the enrichment. -->
        <PlDropdown
          v-model="app.model.data.inputGate"
          :options="inputGateOptions"
          label="Input sample"
          clearable
        >
          <template #tooltip>
            The gate value holding your unsorted library. Optional — naming one adds the per-gate
            enrichment against it. It cannot be one of the gates above.
          </template>
        </PlDropdown>

        <!-- Offered whether or not there is an input: both runs benefit, for different reasons.
             Hidden while the workflow withholds the baseline columns — see `BASELINE_AVAILABLE`. -->
        <PlDropdown
          v-if="BASELINE_AVAILABLE"
          v-model="app.model.data.baseline"
          :options="baselineOptions"
          label="Baseline"
          clearable
        >
          <template #tooltip>
            A set of variants known to have no effect. With an input it sets where "no change" sits,
            which is not 1.0. Without one it shows how wide the noise is. Only the synonymous option
            has a spread, being measured over many variants rather than one.
          </template>
        </PlDropdown>

        <PlTextField
          v-if="BASELINE_AVAILABLE && isEnrichment && app.model.data.baseline === 'sequence'"
          v-model="app.model.data.baselineSequence"
          label="Baseline variant key"
          clearable
        >
          <template #tooltip> The key of the one nucleotide sequence to measure against. </template>
        </PlTextField>

        <PlAlert
          v-if="BASELINE_AVAILABLE && synonymousUnavailable"
          type="warn"
          label="Synonymous baseline unavailable"
        >
          This dataset is protein-level, where synonymous variants have already been merged into the
          wild type. The run will succeed and report no baseline. Pick a nucleotide-level dataset,
          or choose another baseline.
        </PlAlert>
      </PlAccordionSection>
    </PlAccordion>

    <!-- Both default to absent, and absent is an answer rather than an unset field: no
         correction, and no floor. Neither is needed for a first run. -->
    <PlAccordionSection label="Advanced Settings">
      <PlDropdown
        v-model="app.model.data.sortFractionColumnRef"
        :options="app.model.outputs.sortFractionOptions ?? []"
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
