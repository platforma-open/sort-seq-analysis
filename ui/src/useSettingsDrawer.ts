/**
 * Whether the settings drawer is open — shared across the three pages.
 *
 * **This lives in local Vue state, not in `app.model.data`, and that is load-bearing.**
 * The drawer has to close when the block starts running, which means reacting to
 * `outputs.isRunning`. Watching a server-derived output and writing back to server-stored
 * `data` is the hairpin: the write propagates to every client, every client's watcher fires
 * on it, and the interleaving is a race no client predicted. Output → local ref is the
 * sanctioned alternative — closing a drawer when a run starts is exactly the example the
 * harness gives for it.
 *
 * A module-level ref rather than one per component, so opening it from the page header and
 * reading it in the drawer refer to the same thing, and navigating between the three pages
 * does not reset it.
 */
import { ref, watch } from "vue";

const isOpen = ref(false);

/** Set once, the first time a page mounts: open on a block that is not yet configured. */
let initialised = false;
let watching = false;

export function useSettingsDrawer(app: {
  model: { data: { abundanceRef?: unknown }; outputs: { isRunning?: boolean } };
}) {
  if (!initialised) {
    // A freshly added block has no anchor, and until one is picked no other input has an
    // option list — so there is nothing else to show and the drawer opens on its own.
    isOpen.value = app.model.data.abundanceRef === undefined;
    initialised = true;
  }

  if (!watching) {
    watching = true;
    watch(
      () => app.model.outputs.isRunning,
      (running, wasRunning) => {
        // Only on the transition into running: the user has committed, so get the settings
        // out of the way and show them the run.
        if (running && !wasRunning) isOpen.value = false;
      },
    );
  }

  return {
    isOpen,
    open: () => {
      isOpen.value = true;
    },
  };
}
