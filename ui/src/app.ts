import { platforma } from "@platforma-open/milaboratories.sort-seq-analysis.model";
import { defineAppV3 } from "@platforma-sdk/ui-vue";
import DistributionPage from "./pages/DistributionPage.vue";
import MainPage from "./pages/MainPage.vue";

export const sdkPlugin = defineAppV3(platforma, (app) => ({
  progress: () => app.model.outputs.isRunning,
  // Two routes for any number of pages: every condition's distribution link resolves here,
  // because routes are keyed on the pathname and the condition rides in the query string.
  // The run statistics have no route — they are a dialog on Main.
  routes: {
    "/": () => MainPage,
    "/distribution": () => DistributionPage,
  },
}));

export const useApp = sdkPlugin.useApp;
