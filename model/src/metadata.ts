import type { ColumnUniversalId, ColumnValuesSource, RenderCtxBase } from "@platforma-sdk/model";
import { createColumnValuesSource, deriveColumnOptions } from "@platforma-sdk/model";
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
 * Where the UI reads the values of every offered sample-metadata column and of the picked
 * condition and gate columns: one source per column, each a frame of that column alone.
 *
 * Every offered column rather than the picked ones: a column's values are snapshotted, and the
 * gate order seeded, in the same gesture as the pick, so they must be in hand before it.
 *
 * `undefined` while the metadata options are. A picked column that is gone has an `absent`
 * source, so its picks show as not available.
 */
export function getMetadataValueSources(
  ctx: RenderCtxBase,
  abundanceRef: ColumnUniversalId,
  picks: MetadataPicks,
): ColumnValuesSource[] | undefined {
  const options = getMetadataOptions(ctx, abundanceRef);
  if (options === undefined) return undefined;

  const columns = new Set(options.map((option) => option.value));
  for (const picked of [picks.conditionColumnRef, picks.gateColumnRef]) {
    if (picked !== undefined) columns.add(picked);
  }
  return [...columns].map((column) => createColumnValuesSource(ctx, column));
}

/**
 * Where the UI reads the sample names from: a frame of the label column of the dataset's sample
 * axis alone. `undefined` while the dataset or its label column is not known.
 */
export function getSampleLabelSource(
  ctx: RenderCtxBase,
  abundanceRef: ColumnUniversalId,
): ColumnValuesSource | undefined {
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
  return createColumnValuesSource(ctx, column.id);
}

/**
 * Sample names by sample id, from the rows of the label column: `sampleIds[i]` is the key of the
 * row whose label is `labels[i]`. A row missing either is left out.
 */
export function pairSampleLabels(
  sampleIds: readonly SampleLabelCell[],
  labels: readonly SampleLabelCell[],
): Record<string, string> {
  const pairs: Record<string, string> = {};
  for (const [index, sampleId] of sampleIds.entries()) {
    const label = labels[index];
    if (sampleId !== null && label !== null && label !== undefined) {
      pairs[String(sampleId)] = String(label);
    }
  }
  return pairs;
}

/** One cell of the label column as a frame reads it: a key or a label, `null` where missing. */
export type SampleLabelCell = string | number | null;

// Internals

const METADATA_ROLES: readonly MetadataRole[] = [
  "conditionColumnRef",
  "gateColumnRef",
  "sortFractionColumnRef",
];
