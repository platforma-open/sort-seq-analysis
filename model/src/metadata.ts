import type { ColumnUniversalId, ColumnValueOption, RenderCtxBase } from "@platforma-sdk/model";
import {
  deriveColumnOptions,
  deriveColumnValueOptions,
  readColumnValues,
} from "@platforma-sdk/model";
import type { ColumnPickerOption } from "./column_access";
import { axisSelector, findColumn, resultPool } from "./column_access";
import { metadataSelector, sampleLabelSelector } from "./columns";
import type { BlockData } from "./types";

/** The three roles a sample-metadata column is picked for. */
export type MetadataRole = "conditionColumnRef" | "gateColumnRef" | "sortFractionColumnRef";

/** The column picked for each role. */
export type MetadataPicks = Pick<BlockData, MetadataRole>;

/** The values of one sample-metadata column, as options of the value pickers. */
export type MetadataColumnValues = {
  column: ColumnUniversalId;
  options: ColumnValueOption[];
};

/**
 * Sample-metadata columns of upstream blocks whose only axis is the dataset's sample axis
 * (axis 0), as options of the three role pickers. Every option id is a result-pool leaf, so it
 * names the block that produced the column. `undefined` only while the result pool is still
 * resolving; a dataset that is gone from a settled pool offers no options.
 */
export function getMetadataOptions(
  ctx: RenderCtxBase,
  abundanceRef: ColumnUniversalId,
): ColumnPickerOption[] | undefined {
  const sampleAxis = findColumn(ctx, abundanceRef)?.getSpec().axesSpec[0];
  if (sampleAxis === undefined) return resultPool(ctx).isFinal() ? [] : undefined;

  const columns = resultPool(ctx).filter({
    include: { ...metadataSelector, axes: [axisSelector(sampleAxis)], partialAxesMatch: false },
  });
  return deriveColumnOptions(columns).map(({ id, label }) => ({ value: id, label }));
}

/**
 * The metadata options minus what the other two roles hold. The distinctness refusal stays in
 * `args`; this only keeps the user away from it. A role keeps its own pick among the options
 * while the column is offered, or the control renders empty.
 */
export function narrowToRole(
  options: ColumnPickerOption[],
  picks: MetadataPicks,
  role: MetadataRole,
): ColumnPickerOption[] {
  const taken = new Set(
    METADATA_ROLES.filter((other) => other !== role).map((other) => picks[other]),
  );
  return options.filter((option) => !taken.has(option.value));
}

/**
 * The values of every offered sample-metadata column and of the picked condition and gate
 * columns, each value a column value id naming its column, and through it the block that
 * produced the value.
 *
 * Every offered column rather than the picked ones: a column's values are snapshotted, and the
 * gate order seeded, in the same gesture as the pick, so they must be in hand before it.
 *
 * `undefined` while the metadata options are. A column whose values cannot be read now — still
 * resolving, not computed, gone, or not stored inline — offers no values, so its picks show as
 * not available.
 */
export function getMetadataValues(
  ctx: RenderCtxBase,
  abundanceRef: ColumnUniversalId,
  picks: MetadataPicks,
): MetadataColumnValues[] | undefined {
  const options = getMetadataOptions(ctx, abundanceRef);
  if (options === undefined) return undefined;

  const columns = new Set(options.map((option) => option.value));
  for (const picked of [picks.conditionColumnRef, picks.gateColumnRef]) {
    if (picked !== undefined) columns.add(picked);
  }
  return [...columns].map((column) => ({ column, options: readValueOptions(ctx, column) }));
}

/**
 * Sample names by sample id, read off the label column of the dataset's sample axis.
 * `undefined` while the dataset or its label column is not known or not readable.
 */
export function getSampleLabels(
  ctx: RenderCtxBase,
  abundanceRef: ColumnUniversalId,
): Record<string, string> | undefined {
  const sampleAxis = findColumn(ctx, abundanceRef)?.getSpec().axesSpec[0];
  if (sampleAxis === undefined) return undefined;

  const [column] = resultPool(ctx)
    .filter({
      include: {
        ...sampleLabelSelector,
        axes: [axisSelector(sampleAxis)],
        partialAxesMatch: false,
      },
    })
    .getColumns();
  if (column === undefined) return undefined;

  const entries = readColumnValues(column);
  if (entries === undefined) return undefined;
  // One axis, so the key's only entry is the sample id.
  return Object.fromEntries(entries.map((entry) => [String(entry.key[0]), String(entry.value)]));
}

// Internals

const METADATA_ROLES: readonly MetadataRole[] = [
  "conditionColumnRef",
  "gateColumnRef",
  "sortFractionColumnRef",
];

function readValueOptions(ctx: RenderCtxBase, columnRef: ColumnUniversalId): ColumnValueOption[] {
  const column = findColumn(ctx, columnRef);
  const entries = column === undefined ? undefined : readColumnValues(column);
  return deriveColumnValueOptions(entries ?? []);
}
