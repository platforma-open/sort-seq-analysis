<script setup lang="ts">
/**
 * One row per variant: both scored columns for every retained condition, plus the pool columns
 * sharing the variant axis.
 *
 * `resultsTable` is an `outputWithStatus`, so PlAgDataTableV2 owns the loading, not-ready and
 * error states; this page only supplies the text.
 */
import { PlAgDataTableV2, usePlDataTableSettingsV2 } from "@platforma-sdk/ui-vue";
import { useApp } from "../app";
import BlockPage from "../components/BlockPage.vue";
import RunStatistics from "../components/RunStatistics.vue";
import { NOT_READY_TEXT } from "../text";

const app = useApp();

const tableSettings = usePlDataTableSettingsV2({
  model: () => app.model.outputs.resultsTable,
  /**
   * The anchor, but only once there is a table to show, or the running state never appears: a
   * truthy `sourceId` passes the undefined model straight through without setting `pending`,
   * and the running overlay is only reachable while `sourceId` is null.
   *
   * Needed at all because this table can change without a block run — it carries pool columns
   * on the variant axis, so another block emitting a per-variant column changes it.
   */
  sourceId: () => {
    const table = app.model.outputs.resultsTable;
    return table.ok && table.value !== undefined ? app.model.data.abundanceRef : undefined;
  },
});
</script>

<template>
  <!-- Must stay identical to the nav label. -->
  <BlockPage title="Variant Scores" mode="table">
    <template #actions>
      <RunStatistics />
    </template>

    <PlAgDataTableV2
      v-model="app.model.data.resultsTableState"
      :settings="tableSettings"
      :not-ready-text="NOT_READY_TEXT"
      show-columns-panel
      show-export-button
    />
  </BlockPage>
</template>
