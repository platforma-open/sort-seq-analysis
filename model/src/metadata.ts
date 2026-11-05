import type { ColumnUniversalId, ColumnValueOptionsModel } from "@platforma-sdk/model";
import {
  createColumnValueOptions,
  deriveAxisValuesLabels,
  deriveColumnOptions,
} from "@platforma-sdk/model";
import type { ColumnPickerOption } from "./column_access";
import { axisSelector, findColumn, resultPool } from "./column_access";
import { metadataSelector, sampleLabelSelector } from "./columns";
import type { BlockData } from "./types";

/** The three roles a sample-metadata column is picked for. */
export type MetadataRole = "conditionColumnRef" | "gateColumnRef" | "sortFractionColumnRef";

/** The column picked for each role. */
export type MetadataPicks = Pick<BlockData, MetadataRole>;

/**
 * Sample-metadata columns of upstream blocks whose only axis is the dataset's sample axis
 * (axis 0), as options of the three role pickers. Every option id is a result-pool leaf, so it
 * names the block that produced the column. `undefined` only while the result pool is still
 * resolving; a dataset that is gone from a settled pool offers no options.
 */
export function getMetadataOptions(
  abundanceRef: ColumnUniversalId,
): ColumnPickerOption[] | undefined {
  const sampleAxis = findColumn(abundanceRef)?.getSpec().axesSpec[0];
  if (sampleAxis === undefined) return resultPool().isFinal() ? [] : undefined;

  const columns = resultPool().filter({
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
 * Where the UI reads the values of every offered sample-metadata column and of the picked
 * condition and gate columns: one value-options model per column.
 *
 * Every offered column rather than the picked ones: a column's values are snapshotted, and the
 * gate order seeded, in the same gesture as the pick, so they must be in hand before it.
 *
 * `undefined` while the metadata options are. A picked column that is gone has an `absent`
 * model, so its picks show as not available.
 */
export function getMetadataValueSources(
  abundanceRef: ColumnUniversalId,
  picks: MetadataPicks,
): ColumnValueOptionsModel[] | undefined {
  const options = getMetadataOptions(abundanceRef);
  if (options === undefined) return undefined;

  const columns = new Set(options.map((option) => option.value));
  for (const picked of [picks.conditionColumnRef, picks.gateColumnRef]) {
    if (picked !== undefined) columns.add(picked);
  }
  return [...columns].map((valueColumn) => createColumnValueOptions({ valueColumn }));
}

/**
 * Sample names by sample id, from the label column of the dataset's sample axis. `undefined`
 * while the dataset is not known.
 */
export function getSampleLabels(
  abundanceRef: ColumnUniversalId,
): Record<string | number, string> | undefined {
  const sampleAxis = findColumn(abundanceRef)?.getSpec().axesSpec[0];
  if (sampleAxis === undefined) return undefined;

  const labelColumns = resultPool().filter({
    include: { ...sampleLabelSelector, axes: [axisSelector(sampleAxis)], partialAxesMatch: false },
  });
  return deriveAxisValuesLabels(labelColumns)(sampleAxis);
}

// Internals

const METADATA_ROLES: readonly MetadataRole[] = [
  "conditionColumnRef",
  "gateColumnRef",
  "sortFractionColumnRef",
];
