import { platforma } from "@platforma-open/milaboratories.sort-seq-analysis.model";
import { defineAppV3 } from "@platforma-sdk/ui-vue";
import DistributionPage from "./pages/DistributionPage.vue";
import MainPage from "./pages/MainPage.vue";
import NtScoresPage from "./pages/NtScoresPage.vue";

export const sdkPlugin = defineAppV3(platforma, (app) => ({
  progress: () => app.model.outputs.isRunning,
  // Routes are keyed on pathname alone, so every condition's distribution link resolves to the
  // one entry and the condition rides in the query string.
  routes: {
    "/": () => MainPage,
    "/nt": () => NtScoresPage,
    "/distribution": () => DistributionPage,
  },
}));

export const useApp = sdkPlugin.useApp;
