import { assertParamsObject, defineBlockKind } from "@platforma-sdk/block-kind";
import type { ColumnUniversalId, ColumnValueId } from "@platforma-sdk/model";
import { isColumnUniversalId, isColumnValueId } from "@platforma-sdk/model";
import { name, version } from "../package.json" with { type: "json" };

/**
 * This block's init-params contract — what a creator, or a project template, supplies to seed a
 * new instance. A subset of the model's `BlockData`.
 *
 * The subset is **the metadata reading of a sort-seq run**: which column says condition, which
 * says gate, which says sort fraction, and what the gate ladder is. A lab that runs the same
 * FACS ladder over library after library pins that once and then only picks the dataset.
 *
 * The three columns are result-pool column ids, each naming the block that produced the column.
 * The gates of the ladder are column value ids of the gate column: each names the column it was
 * picked from, and through it the block that produced the value. A gate the column no longer
 * carries stays in the ladder and is shown as not available.
 *
 * `gateColumnLabel` travels with the gate column because the subtitle is a pure function of the
 * block's data, and only the column's option knows its label.
 *
 * Left out, and why:
 *
 * - **`abundanceRef`** — the dataset of one project's result pool, picked against the data in
 *   front of you.
 * - **`excludedConditions`, `inputGate` and `readFloor`** — run recipe. They are out because the
 *   operator scoped the contract to the metadata reading; a run's exclusions, its reference and
 *   its floor are decisions taken against the data in front of you.
 * - **View state** — `customBlockLabel`, `resultsTableState`, `distributionGraphStates`. Not
 *   configuration.
 *
 * Every field is optional. A block may be created with no template at all, so the model's
 * `init` keeps its own default behind each one.
 */
export type BlockParams = {
  conditionColumnRef?: ColumnUniversalId;
  gateColumnRef?: ColumnUniversalId;
  sortFractionColumnRef?: ColumnUniversalId;
  gateOrder?: ColumnValueId[];
  gateColumnLabel?: string;
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
 * that the ladder holds values of the gate column — those are refused by `settingsIssues` in the
 * model, where the whole configuration is in view. A parser stricter than the settings drawer
 * would make this block export a template its own kind then refuses to apply.
 */
function parseInitializationParams(value: unknown): BlockParams {
  assertParamsObject(value);

  const { conditionColumnRef, gateColumnRef, sortFractionColumnRef, gateOrder, gateColumnLabel } =
    value;

  return {
    conditionColumnRef: optionalColumnRef(conditionColumnRef, "conditionColumnRef"),
    gateColumnRef: optionalColumnRef(gateColumnRef, "gateColumnRef"),
    sortFractionColumnRef: optionalColumnRef(sortFractionColumnRef, "sortFractionColumnRef"),
    gateOrder: optionalValueList(gateOrder, "gateOrder"),
    gateColumnLabel: optionalString(gateColumnLabel, "gateColumnLabel"),
  };
}

/**
 * Any result-pool column id form is accepted — a leaf, filtered, discovered or overridden one.
 * An id anchored against the dataset names no producing block and is refused.
 */
function optionalColumnRef(value: unknown, field: string): ColumnUniversalId | undefined {
  if (value === undefined) return undefined;
  if (!isColumnUniversalId(value)) {
    throw new Error(`'${field}' must be a metadata column, written as a column id.`);
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
