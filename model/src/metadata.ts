import type {
  ColumnUniversalId,
  PFrameHandle,
  PObjectId,
  RenderCtxBase,
} from "@platforma-sdk/model";
import { ColumnRecipe, deriveColumnOptions, extractPObjectId } from "@platforma-sdk/model";
import type { ColumnPickerOption } from "./column_access";
import { axisSelector, findColumn, resultPool } from "./column_access";
import { metadataSelector, sampleLabelSelector } from "./columns";
import type { BlockData } from "./types";

/** The three roles a sample-metadata column is picked for. */
export type MetadataRole = "conditionColumnRef" | "gateColumnRef" | "sortFractionColumnRef";

/** The column picked for each role. */
export type MetadataPicks = Pick<BlockData, MetadataRole>;

/**
 * Where the UI reads the values of a column from: a frame of the column alone, while the column
 * is there. `column` is the column the frame was made for, so the UI can tell one that still
 * describes an earlier pick; `frameColumn` is the column as the frame holds it.
 */
export type ColumnFrame =
  | { readonly type: "resolving"; readonly column: ColumnUniversalId }
  /** The column is gone: a stored id may name a column its upstream block no longer produces. */
  | { readonly type: "absent"; readonly column: ColumnUniversalId }
  | {
      readonly type: "present";
      readonly column: ColumnUniversalId;
      readonly frame: PFrameHandle;
      readonly frameColumn: PObjectId;
    };

/** A frame of a column that is there to read. */
export type PresentColumnFrame = Extract<ColumnFrame, { type: "present" }>;

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
): ColumnFrame[] | undefined {
  const options = getMetadataOptions(abundanceRef);
  if (options === undefined) return undefined;

  const columns = new Set(options.map((option) => option.value));
  for (const picked of [picks.conditionColumnRef, picks.gateColumnRef]) {
    if (picked !== undefined) columns.add(picked);
  }
  return [...columns].map((column) => columnFrame(ctx, column));
}

/**
 * Where the UI reads the sample names from: a frame of the label column of the dataset's sample
 * axis alone. `undefined` while the dataset or its label column is not known.
 */
export function getSampleLabelSource(
  ctx: RenderCtxBase,
  abundanceRef: ColumnUniversalId,
): ColumnFrame | undefined {
  const sampleAxis = findColumn(abundanceRef)?.getSpec().axesSpec[0];
  if (sampleAxis === undefined) return undefined;

  const [column] = resultPool()
    .filter({
      include: {
        ...sampleLabelSelector,
        axes: [axisSelector(sampleAxis)],
        partialAxesMatch: false,
      },
    })
    .getColumns();
  if (column === undefined) return undefined;
  return columnFrame(ctx, column.id);
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

/** A frame of `column` alone, while the column and its frame are there. */
function columnFrame(ctx: RenderCtxBase, column: ColumnUniversalId): ColumnFrame {
  const status = ColumnRecipe.getStatus(column);
  if (status !== "present") return { type: status, column };
  const frame = ctx.createPFrame([column]);
  if (frame === undefined) return { type: "resolving", column };
  // The frame holds a column by the bare id of its leaf.
  return { type: "present", column, frame, frameColumn: extractPObjectId(column) };
}
