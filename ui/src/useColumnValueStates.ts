/**
 * The values of many columns at once, each read through the source the model gives for it.
 * `useColumnValueOptions` follows one picked column; the drawer needs the values of every
 * offered column before any of them is picked, so a pick can snapshot them in its own gesture.
 */
import type {
  ColumnUniversalId,
  ColumnValuesSource,
  PFrameHandle,
  PresentColumnValuesSource,
} from "@platforma-sdk/model";
import { readColumnValueOptions } from "@platforma-sdk/model";
import type { ColumnValueOptionsState } from "@platforma-sdk/ui-vue";
import type { ShallowRef } from "vue";
import { shallowRef, watch } from "vue";

/**
 * The state of each column's values, by column, read through `sources`. A column has a state
 * only while it has a source; a source that changes is read again, an unchanged one is not.
 * Called from `setup`.
 */
export function useColumnValueStates(
  sources: () => readonly ColumnValuesSource[] | undefined,
): Readonly<ShallowRef<ReadonlyMap<ColumnUniversalId, ColumnValueOptionsState>>> {
  const states = shallowRef<ReadonlyMap<ColumnUniversalId, ColumnValueOptionsState>>(new Map());
  // The source each state comes from. A read whose source has been replaced since is dropped.
  let readFrom = new Map<ColumnUniversalId, ColumnValuesSource>();

  function settle(source: PresentColumnValuesSource, state: ColumnValueOptionsState) {
    if (readFrom.get(source.column) !== source) return;
    states.value = new Map(states.value).set(source.column, state);
  }

  function read(source: PresentColumnValuesSource) {
    readColumnValueOptions(source).then(
      (options) => settle(source, { type: "read", options }),
      (error: unknown) => settle(source, { type: "failed", message: messageOf(error) }),
    );
  }

  watch(
    sources,
    (next) => {
      const nextReadFrom = new Map<ColumnUniversalId, ColumnValuesSource>();
      const nextStates = new Map<ColumnUniversalId, ColumnValueOptionsState>();
      for (const source of next ?? []) {
        const previous = readFrom.get(source.column);
        const previousState = states.value.get(source.column);
        if (previous !== undefined && previousState !== undefined && isSame(previous, source)) {
          nextReadFrom.set(source.column, previous);
          nextStates.set(source.column, previousState);
          continue;
        }
        nextReadFrom.set(source.column, source);
        if (source.type === "present") {
          nextStates.set(source.column, LOADING);
          read(source);
        } else {
          nextStates.set(source.column, source.type === "absent" ? ABSENT : LOADING);
        }
      }
      readFrom = nextReadFrom;
      states.value = nextStates;
    },
    { immediate: true },
  );

  return states;
}

// Internals

const LOADING: ColumnValueOptionsState = { type: "loading" };

const ABSENT: ColumnValueOptionsState = { type: "absent" };

/** Two sources of one column are the same while they agree on its status and its frame. */
function isSame(a: ColumnValuesSource, b: ColumnValuesSource): boolean {
  return a.type === b.type && frameOf(a) === frameOf(b);
}

function frameOf(source: ColumnValuesSource): PFrameHandle | undefined {
  return source.type === "present" ? source.frame : undefined;
}

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
