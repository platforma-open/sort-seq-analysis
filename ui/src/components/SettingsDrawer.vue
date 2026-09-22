<script setup lang="ts">
/**
 * One control per argument. Two things are easy to "fix" wrongly:
 *
 * 1. The read-count floor is clearable — cleared IS the answer, and the normal first run.
 * 2. Column values are snapshotted on the user's gesture, never by a watcher: a watcher on an
 *    output writing to `data` is the hairpin, and two clients would race.
 */
import type { SUniversalPColumnId } from "@platforma-sdk/model";
import { getSingleColumnData, type PObjectId } from "@platforma-sdk/model";
import {
  PlAccordion,
  PlAccordionSection,
  PlAlert,
  PlBtnGroup,
  PlDropdown,
  PlElementList,
  PlDropdownMulti,
  PlDropdownRef,
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

const isEnrichment = computed(() => app.model.data.mode === "enrichment");

const modeOptions = [
  { label: "Gate ranking", value: "gate-ranking" as const },
  { label: "Per-gate enrichment", value: "enrichment" as const },
];

/**
 * `data.mode` is optional, so an older block holds `undefined` and the button group would open
 * with neither option lit. The getter supplies the default for display; the setter runs only
 * on a click.
 */
const mode = computed({
  get: () => app.model.data.mode ?? "gate-ranking",
  set: (value) => {
    app.model.data.mode = value;
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

    <!-- After the gate order because both modes read it. -->
    <PlBtnGroup v-model="mode" :options="modeOptions" label="What to measure">
      <template #tooltip>
        <b>Gate ranking</b> needs your gates ordered weakest to strongest, and scores where along
        that ladder each variant sorted. <b>Per-gate enrichment</b> needs an unsorted input sample,
        and scores how much each variant gained or lost in every gate against it.
      </template>
    </PlBtnGroup>

    <!-- Enrichment only: outside it the run does not use this. -->
    <PlDropdown
      v-if="isEnrichment"
      v-model="app.model.data.inputGate"
      :options="inputGateOptions"
      label="Input sample"
      clearable
      helper="The unsorted reference every gate is compared against."
    >
      <template #tooltip>
        Pick the gate value holding your unsorted library. It must not be one of the ranked gates —
        remove it from the gate order above and it will appear here. Each factor level uses its own
        samples carrying this value, so one choice covers every arm.
      </template>
    </PlDropdown>

    <PlDropdown
      v-if="isEnrichment"
      v-model="app.model.data.baseline"
      :options="baselineOptions"
      label="Baseline"
      clearable
      helper="The level enrichment is read against. Leave empty to report the ratios alone."
    >
      <template #tooltip>
        Sets where "no change" sits on every map. Synonymous variants give the only baseline with a
        real spread, because it is measured over many variants rather than one.
      </template>
    </PlDropdown>

    <PlTextField
      v-if="isEnrichment && app.model.data.baseline === 'sequence'"
      v-model="app.model.data.baselineSequence"
      label="Baseline variant key"
      clearable
      helper="The variant key of the nucleotide sequence to use as the baseline."
    />

    <PlAlert v-if="synonymousUnavailable" type="warn" label="Synonymous baseline unavailable">
      This dataset is protein-level, where synonymous variants have already been merged into the
      wild type. The run will succeed and report no baseline. Pick a nucleotide-level dataset, or
      choose another baseline.
    </PlAlert>

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
