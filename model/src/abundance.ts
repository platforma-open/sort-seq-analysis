import type { ColumnUniversalId, PlRef, RenderCtxBase } from "@platforma-sdk/model";
import { createGlobalPObjectId, deriveColumnOptions } from "@platforma-sdk/model";
import type { ColumnPickerOption } from "./column_access";
import { findColumn, resultPool } from "./column_access";
import { Alphabet, AlphabetDomain, abundanceSelector } from "./columns";

/**
 * Per-sample abundances on the variant grain of upstream blocks, as dataset picker options. Every
 * option id is a result-pool leaf, so it names the block that produced the column.
 */
export function getAbundanceOptions(ctx: RenderCtxBase): ColumnPickerOption[] {
  const columns = resultPool(ctx).filter({ include: abundanceSelector });
  return deriveColumnOptions(columns).map(({ id, label }) => ({ value: id, label }));
}

/**
 * Whether the dataset is at the nucleotide grain; `undefined` while its spec is not known or it
 * declares no alphabet.
 */
export function isNucleotideDataset(
  ctx: RenderCtxBase,
  abundanceRef: ColumnUniversalId,
): boolean | undefined {
  // Axis 1 is the variant axis; the abundance selector admits only two-axis columns.
  const alphabet = findColumn(ctx, abundanceRef)?.getSpec().axesSpec[1]?.domain?.[AlphabetDomain];
  return alphabet === undefined ? undefined : alphabet === Alphabet.Nucleotide;
}

/** The result-pool id of the upstream output a ref points to: it names the same block and column. */
export function toColumnId(ref: PlRef): ColumnUniversalId {
  return createGlobalPObjectId(ref.blockId, ref.name);
}
