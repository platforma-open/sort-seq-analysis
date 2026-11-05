/**
 * The values of many columns at once, each read through the frame the model gives for it. A
 * value picker follows one picked column; the drawer needs the values of every offered column
 * before any of them is picked, so a pick can snapshot them in its own gesture.
 */
import type {
  ColumnUniversalId,
  ColumnValueOption,
  ColumnValueOptionsModel,
  PFrameHandle,
  PresentColumnValueOptionsModel,
} from "@platforma-sdk/model";
import { readColumnValueOptions } from "@platforma-sdk/model";
import type { ShallowRef } from "vue";
import { shallowRef, watch } from "vue";

/** The values of a column, as far as they are read. */
export type ColumnValueOptionsState =
  | { readonly type: "loading" }
  /** The column is gone: a stored id may name a column its upstream block no longer produces. */
  | { readonly type: "absent" }
  | { readonly type: "read"; readonly options: ColumnValueOption[] }
  | { readonly type: "failed"; readonly message: string };

/**
 * The state of each column's values, by column, read through `sources`. A column has a state
 * only while it has a source; a source that changes is read again, an unchanged one is not.
 * Called from `setup`.
 */
export function useColumnValueStates(
  sources: () => readonly ColumnValueOptionsModel[] | undefined,
): Readonly<ShallowRef<ReadonlyMap<ColumnUniversalId, ColumnValueOptionsState>>> {
  const states = shallowRef<ReadonlyMap<ColumnUniversalId, ColumnValueOptionsState>>(new Map());
  // The source each state comes from. A read whose source has been replaced since is dropped.
  let readFrom = new Map<ColumnUniversalId, ColumnValueOptionsModel>();

  function settle(source: PresentColumnValueOptionsModel, state: ColumnValueOptionsState) {
    if (readFrom.get(source.valueColumn) !== source) return;
    states.value = new Map(states.value).set(source.valueColumn, state);
  }

  function read(source: PresentColumnValueOptionsModel) {
    readColumnValueOptions(source).then(
      (options) => settle(source, { type: "read", options }),
      (error: unknown) => settle(source, { type: "failed", message: messageOf(error) }),
    );
  }

  watch(
    // An output recomputed after its producer reruns keeps its objects and changes the frames
    // inside them; copying them makes the reads follow the frames.
    () => sources()?.map((source) => ({ ...source })),
    (next) => {
      const nextReadFrom = new Map<ColumnUniversalId, ColumnValueOptionsModel>();
      const nextStates = new Map<ColumnUniversalId, ColumnValueOptionsState>();
      for (const source of next ?? []) {
        const previous = readFrom.get(source.valueColumn);
        const previousState = states.value.get(source.valueColumn);
        if (previous !== undefined && previousState !== undefined && isSame(previous, source)) {
          nextReadFrom.set(source.valueColumn, previous);
          nextStates.set(source.valueColumn, previousState);
          continue;
        }
        nextReadFrom.set(source.valueColumn, source);
        if (source.type === "present") {
          nextStates.set(source.valueColumn, LOADING);
          read(source);
        } else {
          nextStates.set(source.valueColumn, source.type === "absent" ? ABSENT : LOADING);
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
function isSame(a: ColumnValueOptionsModel, b: ColumnValueOptionsModel): boolean {
  return a.type === b.type && frameOf(a) === frameOf(b);
}

function frameOf(source: ColumnValueOptionsModel): PFrameHandle | undefined {
  return source.type === "present" ? source.frame : undefined;
}

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
