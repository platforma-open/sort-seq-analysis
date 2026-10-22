/**
 * The values of many columns at once, each read through the frame the model gives for it. A
 * value picker follows one picked column; the drawer needs the values of every offered column
 * before any of them is picked, so a pick can snapshot them in its own gesture.
 */
import type {
  ColumnFrame,
  PresentColumnFrame,
} from "@platforma-open/milaboratories.sort-seq-analysis.model";
import type { ColumnUniversalId, ColumnValueOption, PFrameHandle } from "@platforma-sdk/model";
import { deriveColumnValueOptions, PFrameImpl, pTableValue } from "@platforma-sdk/model";
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
  sources: () => readonly ColumnFrame[] | undefined,
): Readonly<ShallowRef<ReadonlyMap<ColumnUniversalId, ColumnValueOptionsState>>> {
  const states = shallowRef<ReadonlyMap<ColumnUniversalId, ColumnValueOptionsState>>(new Map());
  // The source each state comes from. A read whose source has been replaced since is dropped.
  let readFrom = new Map<ColumnUniversalId, ColumnFrame>();

  function settle(source: PresentColumnFrame, state: ColumnValueOptionsState) {
    if (readFrom.get(source.column) !== source) return;
    states.value = new Map(states.value).set(source.column, state);
  }

  function read(source: PresentColumnFrame) {
    readValueOptions(source).then(
      (options) => settle(source, { type: "read", options }),
      (error: unknown) => settle(source, { type: "failed", message: messageOf(error) }),
    );
  }

  watch(
    // An output recomputed after its producer reruns keeps its objects and changes the frames
    // inside them; copying them makes the reads follow the frames.
    () => sources()?.map((source) => ({ ...source })),
    (next) => {
      const nextReadFrom = new Map<ColumnUniversalId, ColumnFrame>();
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

/** More distinct values than any picker can usefully list. */
const VALUES_LIMIT = 100_000;

const LOADING: ColumnValueOptionsState = { type: "loading" };

const ABSENT: ColumnValueOptionsState = { type: "absent" };

/** Two sources of one column are the same while they agree on its status and its frame. */
function isSame(a: ColumnFrame, b: ColumnFrame): boolean {
  return a.type === b.type && frameOf(a) === frameOf(b);
}

function frameOf(source: ColumnFrame): PFrameHandle | undefined {
  return source.type === "present" ? source.frame : undefined;
}

/**
 * The distinct values of the column `source` holds, read through its frame, as options of a
 * value picker in natural order. Missing values are not offered. Rejects when the column has more
 * distinct values than a picker can offer.
 */
async function readValueOptions(source: PresentColumnFrame): Promise<ColumnValueOption[]> {
  const response = await new PFrameImpl(source.frame).getUniqueValues({
    columnId: source.frameColumn,
    filters: [],
    limit: VALUES_LIMIT,
  });
  if (response.overflow) {
    throw new Error(`The column has more than ${VALUES_LIMIT} distinct values`);
  }

  const values: string[] = [];
  for (let row = 0; row < response.values.data.length; row++) {
    const value = pTableValue(response.values, row, { na: null });
    if (value !== null) values.push(String(value));
  }
  return deriveColumnValueOptions(source.column, values);
}

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
