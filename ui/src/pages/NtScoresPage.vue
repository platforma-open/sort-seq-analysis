<script setup lang="ts">
/**
 * One row per nucleotide variant. `ntResultsTable` is an `outputWithStatus`, so the table owns
 * the loading, not-ready and error states and this page only supplies the text.
 */
import { PlAgDataTableV2, usePlDataTableSettingsV2 } from "@platforma-sdk/ui-vue";
import { useApp } from "../app";
import BlockPage from "../components/BlockPage.vue";
import { NOT_READY_TEXT } from "../text";

const app = useApp();

const tableSettings = usePlDataTableSettingsV2({
  model: () => app.model.outputs.ntResultsTable,
  /**
   * Set only once there is a table, or the running state never appears: a truthy `sourceId`
   * passes the undefined model through without setting `pending`. Needed because this table can
   * change without a block run — another block emitting a per-variant column changes it.
   */
  sourceId: () => {
    const table = app.model.outputs.ntResultsTable;
    return table.ok && table.value !== undefined ? app.model.data.abundanceRef : undefined;
  },
});
</script>

<template>
  <!-- Must stay identical to the nav label. -->
  <BlockPage title="NT Scores" mode="table">
    <PlAgDataTableV2
      v-model="app.model.data.ntResultsTableState"
      :settings="tableSettings"
      :not-ready-text="NOT_READY_TEXT"
      show-columns-panel
      show-export-button
    />
  </BlockPage>
</template>
