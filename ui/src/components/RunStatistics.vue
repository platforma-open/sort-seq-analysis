<script setup lang="ts">
/**
 * The Statistics button and the dialog it opens.
 *
 * Every row here reports a failure no chart reveals: a gate order set wrong inverts the score,
 * a condition that collected only some of its gates changes what the denominator ran over, and
 * an unidentifiable parent changes what `binScore` means.
 *
 * `@click.stop` is required — the dialog closes on an outside click, and the opening click
 * would otherwise bubble up and be read as outside, closing it in the tick it opened.
 *
 * Open state is a local `ref`, not `BlockData`: in `data` it is shared, so one person opening
 * the dialog would open it for everyone with the project open.
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
 * Why no parent row was identified, or `undefined` where one was — the identified case raises
 * nothing, since an alert on every healthy run trains the reader to skip the real warning.
 *
 * Three absent cases, each changing what `binScore` means. The third — no mutation-count
 * column at all, so no bin score anywhere — arrives as a null reason rather than a named one.
 */
const parentAbsence = computed(() => {
  const value = manifest.value;
  if (!value || value.parentIdentified) return undefined;
  if (value.parentAbsenceReason === "no-variant-with-zero-mutation-count") {
    return "No variant has an amino-acid mutation count of zero. Bin scores are emitted in the cancelled form.";
  }
  if (value.parentAbsenceReason === "multiple-variants-with-zero-mutation-count") {
    return "More than one variant has an amino-acid mutation count of zero. Bin scores are emitted in the cancelled form.";
  }
  return "No mutation-count column was available, so no bin score was produced.";
});

/**
 * `sampleId` -> sample name. The label column has one axis, so `axesData`'s single entry lines
 * up with `data` by position. Empty until resolved, or where upstream published no labels.
 */
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
 * These labels are display-only. `referenceMode` is also a domain value downstream consumers
 * select on, so renaming the emitted values to match would join to nothing.
 *
 * "no parent" and "not produced" are different situations: the first is a real bin score that
 * equals the gate rank mean because the reference term cancelled, the second is no column.
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

    <!-- Hardcoding `not-ready` would tell the user the block was unconfigured during the very
         run this view exists to watch. -->
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
            <th>Bin Score</th>
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
            <!-- A sum short of 1.0 is legitimate — a partially collected condition looks like
                 this, and nothing renormalizes it. -->
            <td>{{ entry.sortFractionSum ?? "—" }}</td>
          </tr>
        </tbody>
      </table>
    </template>

    <!-- A successful run prints these same facts to stdout, so showing the log beside the
         table is the content twice. A refused run writes no manifest and prints only to the
         log, and this is the sole surface carrying that reason. -->
    <PlLogView
      v-if="!manifest && app.model.outputs.logHandle"
      :log-handle="app.model.outputs.logHandle"
    />
  </PlDialogModal>
</template>

<style scoped>
/* The SDK has no primitive for a handful of read-only key numbers, and a data table would be
   heavier than the content. */
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
