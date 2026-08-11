<script setup lang="ts">
/**
 * The shared page shell, so views cannot drift apart in layout.
 *
 * `mode: "graph"` suppresses GraphMaker's own chart title, which renders under the page title
 * and reads as two stacked headers, and drops the body gutters so the chart gets full width.
 */
import { PlBlockPage } from "@platforma-sdk/ui-vue";
import { useApp } from "../app";
import PageHeader from "./PageHeader.vue";

defineProps<{ title: string; mode: "graph" | "table" }>();

const app = useApp();
</script>

<template>
  <PlBlockPage
    v-model:subtitle="app.model.data.customBlockLabel"
    :subtitle-placeholder="app.model.outputs.defaultBlockLabel"
    :title="title"
    :no-body-gutters="mode === 'graph'"
  >
    <template #append>
      <slot name="actions" />
      <PageHeader />
    </template>
    <slot />
  </PlBlockPage>
</template>

<style scoped>
/* GraphMaker ships its own editable chart title. On a page that already has a title it is a
   second header — hide it and remove the space it occupied. */
:deep(.graph-maker .chart_title),
:deep(.graph-maker .chart_titleEdit) {
  display: none;
}
:deep(.graph-maker .chart_header) {
  margin-bottom: 0;
}
:deep(.graph-maker .chart_container) {
  padding-top: 0;
}
</style>
