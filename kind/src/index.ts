import { assertParamsObject, defineBlockKind } from "@platforma-sdk/block-kind";
import {
  isAnchoredPColumnId,
  isColumnUniversalKey,
  type SUniversalPColumnId,
} from "@platforma-sdk/model";
import { name, version } from "../package.json" with { type: "json" };

/**
 * This block's init-params contract — what a creator, or a project template, supplies to seed a
 * new instance. A subset of the model's `BlockData`.
 *
 * The subset is **the metadata reading of a sort-seq run**: which column says condition, which
 * says gate, which says sort fraction, and what the gate ladder is. A lab that runs the same
 * FACS ladder over library after library pins that once and then only picks the dataset.
 *
 * **The three column refs travel, and that is not obvious — it holds because of what they
 * point at.** An `SUniversalPColumnId` is anchored: it is meaningless without the anchor map
 * that `abundanceRef` supplies, and `abundanceRef` is deliberately not a param (a `PlRef` names
 * an entry in one project's result pool and nothing in another). What the id *encodes* is the
 * column's own spec, and for a `samples-and-data` metadata column that spec's discriminator is
 * `pl7.app/columnId` set to the column's **label** — every path that creates one passes
 * `global: true`, so the value is `"Condition"`, not a generated per-project id. Two projects
 * whose metadata carries a column labelled the same way therefore derive the same anchored id,
 * and the template resolves. Where the upstream differs, it resolves to nothing and the picker
 * shows no selection — visible, not silently wrong.
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
 * Left out, and why:
 *
 * - **`abundanceRef`** — a `PlRef` into one project's result pool. Nothing can carry one.
 * - **`excludedConditions` and `readFloor`** — run recipe, and both would travel fine. They are
 *   out because the operator scoped the contract to the metadata reading; a run's exclusions
 *   and its floor are decisions taken against the data in front of you.
 * - **View state** — `customBlockLabel`, `resultsTableState`, `distributionGraphStates`. Not
 *   configuration.
 *
 * Every field is optional. A block may be created with no template at all, so the model's
 * `init` keeps its own default behind each one.
 */
export type BlockParams = {
  conditionColumnRef?: SUniversalPColumnId;
  gateColumnRef?: SUniversalPColumnId;
  sortFractionColumnRef?: SUniversalPColumnId;
  gateOrder?: string[];
  gateValues?: string[];
  gateColumnLabel?: string;
  conditionValues?: string[];
};

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
 * The checks stop at the shape of a value. That `gateOrder` names only values `gateValues`
 * carries, that a gate column is not also the condition column — those are refused by
 * `settingsIssues` in the model, where the whole configuration is in view. A parser stricter
 * than the settings drawer would make this block export a template its own kind then refuses to
 * apply.
 */
function parseInitializationParams(value: unknown): BlockParams {
  assertParamsObject(value);

  const {
    conditionColumnRef,
    gateColumnRef,
    sortFractionColumnRef,
    gateOrder,
    gateValues,
    gateColumnLabel,
    conditionValues,
  } = value;

  return {
    conditionColumnRef: optionalColumnRef(conditionColumnRef, "conditionColumnRef"),
    gateColumnRef: optionalColumnRef(gateColumnRef, "gateColumnRef"),
    sortFractionColumnRef: optionalColumnRef(sortFractionColumnRef, "sortFractionColumnRef"),
    gateOrder: optionalStringList(gateOrder, "gateOrder"),
    gateValues: optionalStringList(gateValues, "gateValues"),
    gateColumnLabel: optionalString(gateColumnLabel, "gateColumnLabel"),
    conditionValues: optionalStringList(conditionValues, "conditionValues"),
  };
}

/**
 * A column ref is a canonically serialized id, not a free string, so this checks the string
 * parses and that what comes out is a shape the SDK recognizes as a column id.
 *
 * **Not `isColumnUniversalId`, which is the obvious choice and the wrong one.** The block stores
 * what `AnchoredIdDeriver.deriveS` returns — an *anchored* id, `{name, type, domain, axes}` with
 * `{anchor, idx}` refs in the axes. `ColumnUniversalId` is a union of the PObject / filtered /
 * discovered / overridden key forms and does not include the anchored one, so
 * `isColumnUniversalId` returns `false` for every id this block actually holds. (The
 * `SUniversalPColumnId` name is a deprecated alias of `ColumnUniversalId`, which is what makes
 * the mistake look correct.) Verified against pl-model-common 1.48.0: an anchored id fails
 * `isColumnUniversalId` and passes `isAnchoredPColumnId`.
 *
 * `isColumnUniversalKey` is kept alongside so a ref that arrives in one of the other forms is
 * not refused for a reason that has nothing to do with the template being wrong.
 *
 * The cast is over a real check: both guards narrow the *parsed* value, and nothing in the SDK
 * narrows the string that carried it.
 */
function optionalColumnRef(value: unknown, field: string): SUniversalPColumnId | undefined {
  if (value === undefined) return undefined;
  if (typeof value !== "string") throw new Error(`'${field}' must be a column id.`);

  let parsed: unknown;
  try {
    parsed = JSON.parse(value);
  } catch {
    throw new Error(`'${field}' must be a column id.`);
  }

  if (!isAnchoredPColumnId(parsed) && !isColumnUniversalKey(parsed))
    throw new Error(`'${field}' must be a column id.`);

  return value as SUniversalPColumnId;
}

function optionalString(value: unknown, field: string): string | undefined {
  if (value === undefined) return undefined;
  if (typeof value !== "string") throw new Error(`'${field}' must be a string.`);
  return value;
}

function optionalStringList(value: unknown, field: string): string[] | undefined {
  if (value === undefined) return undefined;
  if (!Array.isArray(value)) throw new Error(`'${field}' must be a list.`);
  return value.map((entry, index) => {
    if (typeof entry !== "string") throw new Error(`'${field}[${index}]' must be a string.`);
    return entry;
  });
}

// Identity (`name`/`version`) comes from this package's own `package.json`, so the on-wire
// `{name}@{version}` reference can never drift from what npm publishes; the bundler inlines the
// JSON import.
export const kind = defineBlockKind<BlockParams>({
  name,
  version,
  parseInitializationParams,
});
