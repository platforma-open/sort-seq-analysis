<script setup lang="ts">
/**
 * The Statistics button and the dialog it opens. Every row reports a failure no chart reveals.
 *
 * `@click.stop` is required: the dialog closes on an outside click, and the opening click would
 * bubble up and be read as outside. Open state is a local ref — in `data` it would be shared.
 */
import { getSingleColumnData, type PObjectId } from "@platforma-sdk/model";
import {
  PlAgOverlayLoading,
  PlAlert,
  PlBtnGhost,
  PlDialogModal,
  PlLogView,
  PlMaskIcon24,
  useWatchFetch,
} from "@platforma-sdk/ui-vue";
import { computed, ref } from "vue";
import { useApp } from "../app";
import { NOT_READY_TEXT } from "../text";

const app = useApp();

const isOpen = ref(false);

const manifest = computed(() => app.model.outputs.manifest);

/**
 * Why no parent row was identified, or `undefined` where one was — an alert on every healthy
 * run trains the reader to skip the real warning. The third case, no mutation-count column at
 * all, arrives as a null reason rather than a named one.
 */
const parentAbsence = computed(() => {
  const value = manifest.value;
  if (!value || value.parentIdentified) return undefined;
  if (value.parentAbsenceReason === "no-variant-with-zero-mutation-count") {
    return 'No variant has an amino-acid mutation count of zero. "Mean bin vs parent" is emitted in the cancelled form.';
  }
  if (value.parentAbsenceReason === "multiple-variants-with-zero-mutation-count") {
    return 'More than one variant has an amino-acid mutation count of zero. "Mean bin vs parent" is emitted in the cancelled form.';
  }
  return 'No mutation-count column was available, so "Mean bin vs parent" was not produced.';
});

/**
 * Why the chosen baseline produced nothing, or `undefined` otherwise — same rule as
 * `parentAbsence`. Each reason is phrased as the action that fixes it, which is why the
 * computation reports four tokens rather than one "no baseline".
 */
const baselineAbsence = computed(() => {
  const value = manifest.value;
  if (!value || value.baselineOption === null || value.baselineIdentified) return undefined;
  if (value.baselineAbsenceReason === "synonymous-baseline-needs-nucleotide-grain") {
    return "The synonymous baseline needs a nucleotide-level dataset. At protein level those variants have already been merged into the wild type.";
  }
  if (value.baselineAbsenceReason === "no-synonymous-variants") {
    return "No variant in this library is synonymous with the wild type, so there is nothing to average.";
  }
  if (value.baselineAbsenceReason === "named-sequence-absent-from-dataset") {
    return "The variant key given as the baseline sequence appears nowhere in this dataset. Check it for a typo.";
  }
  if (value.baselineAbsenceReason === "parent-not-identified") {
    return "The wild-type baseline needs a single variant with zero mutations, and this run has none.";
  }
  return "No mutation-count column was available, so the baseline could not be resolved.";
});

/** Each condition's input depth. Every ratio rests on it and no chart shows it. */
const inputDepths = computed(() => {
  const value = manifest.value;
  if (!value || value.mode !== "enrichment") return undefined;
  return value.conditions.map((entry) => ({
    condition: entry.condition,
    depth: entry.inputDepth ?? 0,
    gates: entry.gateEnrichments.length,
  }));
});

/** `sampleId` -> sample name. One axis, so `axesData[0]` lines up with `data` by position. */
const sampleLabels = useWatchFetch(
  () => ({
    pframe: app.model.outputs.sampleLabelPframe,
    columnId: app.model.outputs.sampleLabelColumnId,
  }),
  async ({ pframe, columnId }) => {
    const out: Record<string, string> = {};
    if (!pframe || !columnId) return out;

    const column = await getSingleColumnData(pframe, columnId as PObjectId);
    const ids = Object.values(column?.axesData ?? {})[0] ?? [];
    const labels = column?.data ?? [];
    for (const [index, id] of ids.entries()) {
      const label = labels[index];
      if (id !== null && id !== undefined && label !== null && label !== undefined) {
        out[String(id)] = String(label);
      }
    }
    return out;
  },
);

/** The sample's name, falling back to the raw id. */
function labelFor(sampleId: string): string {
  return sampleLabels.value?.[sampleId] ?? sampleId;
}

/** The pooled groups, or `undefined` where nothing was pooled — see `parentAbsence` on why. */
const pooling = computed(() => {
  const groups = manifest.value?.pooledGroups;
  if (!groups || groups.length === 0) return undefined;
  return {
    lines: groups.map(
      (group) => `${group.condition} / ${group.gate}: ${group.samples.map(labelFor).join(" + ")}`,
    ),
    fractionsDiffer: groups.some((group) => group.sortFractionsDiffer === true),
  };
});

/** Already ordered by declared gate rank, so this reads along the binding axis. */
function gateList(gates: { gate: string; depth: number }[]): string {
  return gates.map((entry) => `${entry.gate} (${entry.depth})`).join(", ");
}

/**
 * Display-only: `referenceMode` is a domain value consumers select on, so renaming the emitted
 * values would join to nothing. "no parent" is a real score whose reference cancelled;
 * "not produced" is no column at all.
 */
function binScoreCell(entry: {
  binScoreFile: string | null;
  referenceMode: "referenced" | "cancelled" | null;
}): string {
  if (entry.binScoreFile === null) return "not produced";
  switch (entry.referenceMode) {
    case "referenced":
      return "parent found";
    case "cancelled":
      return "no parent";
    default:
      return "";
  }
}
</script>

<template>
  <PlBtnGhost @click.stop="isOpen = true">
    Statistics
    <template #append>
      <PlMaskIcon24 name="statistics" />
    </template>
  </PlBtnGhost>

  <PlDialogModal v-model="isOpen" width="880px" :close-on-outside-click="true">
    <template #title>Run statistics</template>

    <!-- Hardcoding `not-ready` would read as "unconfigured" during the run this view watches. -->
    <PlAgOverlayLoading
      v-if="!manifest"
      :params="{
        variant: app.model.outputs.isRunning ? 'running' : 'not-ready',
        notReadyText: NOT_READY_TEXT,
      }"
    />

    <template v-else>
      <PlAlert v-if="parentAbsence" type="warn">
        <template #title>Parent row not identified</template>
        {{ parentAbsence }}
      </PlAlert>

      <PlAlert v-if="baselineAbsence" type="warn">
        <template #title>No baseline was produced</template>
        {{ baselineAbsence }} The enrichment values are unaffected — they are still ratios against
        the input, with no baseline level marked on them.
      </PlAlert>

      <PlAlert v-if="inputDepths" type="info">
        <template #title>Enrichment against the unsorted input</template>
        Every ratio below is against these reads. A thin input makes per-cell values texture rather
        than something to threshold on.
        <ul>
          <li v-for="row in inputDepths" :key="row.condition">
            {{ row.condition }} — input depth {{ row.depth }}, {{ row.gates }} gate(s) scored
          </li>
        </ul>
      </PlAlert>

      <PlAlert v-if="pooling" type="warn">
        <template #title>Replicate samples were pooled</template>
        These gates were collected more than once, and their reads were summed. Depths, frequencies
        and every score below are over the pooled reads.
        <ul>
          <li v-for="line in pooling.lines" :key="line">{{ line }}</li>
        </ul>
        <template v-if="pooling.fractionsDiffer">
          Some replicates supplied different sort fractions; the values were averaged. Check that
          the sort-fraction column is per gate rather than per replicate sort.
        </template>
      </PlAlert>

      <table class="summary">
        <thead>
          <tr>
            <th>Condition</th>
            <th>Gates Collected (pre-floor depths)</th>
            <th>Variants Scored</th>
            <th>Mean bin vs parent</th>
            <th>Sort-Yield Correction</th>
            <th>Fraction Sum</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="entry in manifest.conditions" :key="entry.condition">
            <td>{{ entry.condition }}</td>
            <td>{{ gateList(entry.gatesCollected) }}</td>
            <td>{{ entry.variantsScored }}</td>
            <td>{{ binScoreCell(entry) }}</td>
            <td>{{ entry.sortYieldCorrected ? "applied" : "not applied" }}</td>
            <!-- A sum short of 1.0 is legitimate and is never renormalized. -->
            <td>{{ entry.sortFractionSum ?? "—" }}</td>
          </tr>
        </tbody>
      </table>
    </template>

    <!-- A refused run writes no manifest, so the log is the only surface carrying the reason. -->
    <PlLogView
      v-if="!manifest && app.model.outputs.logHandle"
      :log-handle="app.model.outputs.logHandle"
    />
  </PlDialogModal>
</template>

<style scoped>
/* The SDK has no primitive for a handful of read-only numbers. */
.summary {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
.summary th,
.summary td {
  text-align: left;
  padding: 8px 12px;
  border-bottom: 1px solid var(--border-color-div-grey, #e1e3eb);
}
.summary th {
  font-weight: 600;
  white-space: nowrap;
}
</style>
