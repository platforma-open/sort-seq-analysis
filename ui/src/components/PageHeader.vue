<script setup lang="ts">
/**
 * The Settings button, and the drawer it opens.
 *
 * Two things follow the shape every other block uses, and both are load-bearing:
 *
 * 1. **`@click.stop`.** `PlSlideModal` closes on an outside click. Without `.stop` the
 *    button's own click bubbles up, the modal reads it as "outside", and it closes in the
 *    same tick it opened — which presents as the button doing nothing.
 * 2. **The drawer is mounted here, beside the button**, not separately on each page. One
 *    button, one drawer, one place. Mounting it per page gave three `PlSlideModal`s racing
 *    over one shared open flag.
 */
import { PlBtnGhost, PlMaskIcon24 } from "@platforma-sdk/ui-vue";
import { useApp } from "../app";
import { useSettingsDrawer } from "../useSettingsDrawer";
import SettingsDrawer from "./SettingsDrawer.vue";

const { isOpen } = useSettingsDrawer(useApp());
</script>

<template>
  <PlBtnGhost @click.stop="isOpen = true">
    Settings
    <template #append>
      <PlMaskIcon24 name="settings" />
    </template>
  </PlBtnGhost>

  <SettingsDrawer v-model="isOpen" />
</template>
