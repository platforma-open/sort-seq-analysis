import { assertParamsObject, defineBlockKind } from "@platforma-sdk/block-kind";
import type { ColumnUniversalId, ColumnValueId } from "@platforma-sdk/model";
import { isColumnValueId, isGlobalPObjectId } from "@platforma-sdk/model";
import { name, version } from "../package.json" with { type: "json" };

/** What a per-gate enrichment is read against. `synonymous` needs the nucleotide grain. */
export type BaselineOption = "wild-type" | "synonymous" | "sequence";

/**
 * This block's init-params contract — what a creator, or a project template, supplies to seed a
 * new instance. A subset of the model's `BlockData`: everything the user sets in the drawer.
 *
 * - **The dataset** — `abundanceRef`, and `filterRef` when the run is narrowed to a subset of it.
 * - **The metadata reading** — which column says condition, which says gate, which says sort
 *   fraction, and what the gate ladder is.
 * - **The run recipe** — the excluded conditions, the read-count floor, whether the gates are
 *   ordered, the unsorted input, and the baseline.
 *
 * The dataset, the subset and the three columns are result-pool column ids, each naming the block
 * that produced the column. The gates of the ladder, the input, the exclusions and the two value
 * snapshots are column value ids of their columns: each names the column it was picked from, and
 * through it the block that produced the value. A project template names its blocks, and a block
 * created from one receives every one of these pointing at the blocks made from the same entries,
 * so a project made from a template computes what the original one did. A lab that runs the same
 * FACS ladder over library after library may leave the dataset out of a template and pick it
 * afterwards.
 *
 * **The three value snapshots are params for a reason that is easy to miss.** `gateValues`,
 * `conditionValues` and `gateColumnLabel` are snapshots the UI writes when a column is picked,
 * and they look like derived state that a fresh block should rebuild. But the model's
 * `settingsIssues` validates `gateOrder` against `gateValues`, so a template carrying a gate
 * ladder and an empty snapshot arrives with Run disabled and two complaints; and the only way
 * to refill the snapshot from the UI is to re-pick the gate column, which overwrites
 * `gateOrder` with every value of the column. The templated ladder would be destroyed by the
 * act of making the block runnable. Carrying the snapshots keeps the template usable on
 * arrival.
 *
 * Left out: view state — `customBlockLabel`, the table states and `distributionGraphStates`.
 * Not configuration.
 *
 * Every field is optional. A block may be created with no template at all, so the model's
 * `init` keeps its own default behind each one.
 */
export type BlockParams = {
  abundanceRef?: ColumnUniversalId;
  filterRef?: ColumnUniversalId;
  conditionColumnRef?: ColumnUniversalId;
  gateColumnRef?: ColumnUniversalId;
  sortFractionColumnRef?: ColumnUniversalId;
  gateOrder?: ColumnValueId[];
  gateValues?: ColumnValueId[];
  gateColumnLabel?: string;
  conditionValues?: ColumnValueId[];
  excludedConditions?: ColumnValueId[];
  readFloor?: number;
  gatesOrdered?: boolean;
  inputGate?: ColumnValueId;
  baseline?: BaselineOption;
  baselineSequence?: string;
};

// Identity (`name`/`version`) comes from this package's own `package.json`, so the on-wire
// `{name}@{version}` reference can never drift from what npm publishes; the bundler inlines the
// JSON import.
export const kind = defineBlockKind<BlockParams>({
  name,
  version,
  parseInitializationParams,
});

// Internals

/**
 * The same contract at runtime, for params arriving from a template file rather than from typed
 * code — the only point that can catch a hand-written entry being wrong.
 *
 * Each field the contract names is read and checked; nothing else is. A key this function never
 * reads is dropped rather than refused, so a misspelled key in a template file is not caught
 * here — it surfaces later as a block that started on its defaults. That cost is accepted: a
 * key-set check would mean this file keeping its own field names as strings, and nothing holds
 * that list in step with the type above.
 *
 * The checks stop at the form of a value. That a gate column is not also the condition column,
 * that `gateOrder` names only values `gateValues` carries — those are refused by
 * `settingsIssues` in the model, where the whole configuration is in view. A parser stricter than
 * the settings drawer would make this block export a template its own kind then refuses to apply.
 */
function parseInitializationParams(value: unknown): BlockParams {
  assertParamsObject(value);

  const {
    abundanceRef,
    filterRef,
    conditionColumnRef,
    gateColumnRef,
    sortFractionColumnRef,
    gateOrder,
    gateValues,
    gateColumnLabel,
    conditionValues,
    excludedConditions,
    readFloor,
    gatesOrdered,
    inputGate,
    baseline,
    baselineSequence,
  } = value;

  return {
    abundanceRef: optionalColumnRef(abundanceRef, "abundanceRef", "a dataset"),
    filterRef: optionalColumnRef(filterRef, "filterRef", "a subset column"),
    conditionColumnRef: optionalColumnRef(conditionColumnRef, "conditionColumnRef"),
    gateColumnRef: optionalColumnRef(gateColumnRef, "gateColumnRef"),
    sortFractionColumnRef: optionalColumnRef(sortFractionColumnRef, "sortFractionColumnRef"),
    gateOrder: optionalValueList(gateOrder, "gateOrder"),
    gateValues: optionalValueList(gateValues, "gateValues"),
    gateColumnLabel: optionalString(gateColumnLabel, "gateColumnLabel"),
    conditionValues: optionalValueList(conditionValues, "conditionValues"),
    excludedConditions: optionalValueList(excludedConditions, "excludedConditions"),
    readFloor: optionalNumber(readFloor, "readFloor"),
    gatesOrdered: optionalBoolean(gatesOrdered, "gatesOrdered"),
    inputGate: optionalValue(inputGate, "inputGate"),
    baseline: optionalEnum(baseline, BASELINE_OPTIONS, "baseline"),
    baselineSequence: optionalString(baselineSequence, "baselineSequence"),
  };
}

/**
 * A column of another block: the pickers offer upstream outputs only, so the result-pool id of
 * one is the only column id a template can carry. An id anchored against the dataset names no
 * producing block and is refused.
 */
function optionalColumnRef(
  value: unknown,
  field: string,
  what = "a metadata column",
): ColumnUniversalId | undefined {
  if (value === undefined) return undefined;
  if (!isGlobalPObjectId(value)) {
    throw new Error(`'${field}' must be ${what}, written as ${OUTPUT_ID}.`);
  }
  return value;
}

/** One picked value of a column, written as a column value id; a plain value is refused. */
function optionalValue(value: unknown, field: string): ColumnValueId | undefined {
  if (value === undefined) return undefined;
  if (!isColumnValueId(value)) {
    throw new Error(`'${field}' must be a column value, written as a column value id.`);
  }
  return value;
}

/** Picked values of a column, each written as a column value id; a plain value is refused. */
function optionalValueList(value: unknown, field: string): ColumnValueId[] | undefined {
  if (value === undefined) return undefined;
  if (!Array.isArray(value)) throw new Error(`'${field}' must be a list.`);
  return value.map((entry, index) => {
    if (!isColumnValueId(entry)) {
      throw new Error(`'${field}[${index}]' must be a column value, written as a column value id.`);
    }
    return entry;
  });
}

function optionalString(value: unknown, field: string): string | undefined {
  if (value === undefined) return undefined;
  if (typeof value !== "string") throw new Error(`'${field}' must be a string.`);
  return value;
}

function optionalNumber(value: unknown, field: string): number | undefined {
  if (value === undefined) return undefined;
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new Error(`'${field}' must be a number.`);
  }
  return value;
}

function optionalBoolean(value: unknown, field: string): boolean | undefined {
  if (value === undefined) return undefined;
  if (typeof value !== "boolean") throw new Error(`'${field}' must be true or false.`);
  return value;
}

function optionalEnum<T extends string>(
  value: unknown,
  allowed: readonly T[],
  field: string,
): T | undefined {
  if (value === undefined) return undefined;
  if (typeof value !== "string" || !(allowed as readonly string[]).includes(value)) {
    throw new Error(`'${field}' must be one of ${allowed.join(", ")}.`);
  }
  return value as T;
}

const BASELINE_OPTIONS: readonly BaselineOption[] = ["wild-type", "synonymous", "sequence"];

const OUTPUT_ID = "the result-pool id of another block's output";
