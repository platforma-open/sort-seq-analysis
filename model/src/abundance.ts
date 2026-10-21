import type {
  ColumnUniversalId,
  DatasetOption,
  DatasetSelection,
  PlRef,
  RenderCtxBase,
} from "@platforma-sdk/model";
import {
  buildDatasetOptions,
  createDatasetSelection,
  createGlobalPObjectId,
  createPrimaryRef,
  deriveColumnOptions,
  isPColumnSpec,
  isPlRef,
  parseColumnIdSafely,
} from "@platforma-sdk/model";
import { findColumn, resultPool } from "./column_access";
import { Alphabet, AlphabetDomain, Annotation, abundanceSelector } from "./columns";

/** The dataset and the subset it is restricted to, as the block stores them. */
export type AbundancePick = {
  abundanceRef: ColumnUniversalId | undefined;
  filterRef: ColumnUniversalId | undefined;
};

/**
 * Per-sample abundances on the variant grain of upstream blocks, as dataset picker options, each
 * with its subset columns (e.g. Repertoire Labeling labels) as filters. Every option is a
 * result-pool leaf, so it names the block that produced the column.
 */
export function getAbundanceOptions(ctx: RenderCtxBase): DatasetOption[] {
  // Only the filters are taken from here: the datasets below are matched to them by column id.
  const withFilters =
    buildDatasetOptions(ctx, {
      primary: (spec) =>
        isPColumnSpec(spec) &&
        spec.axesSpec.length === 2 &&
        spec.annotations?.[Annotation.AbundanceIsPrimary] === "true" &&
        spec.annotations?.[Annotation.AbundanceNormalized] === "false",
      // Only subsets keyed by the dataset's key axis alone
      filter: (spec) =>
        isPColumnSpec(spec) &&
        spec.axesSpec.length === 1 &&
        DATASET_KEY_AXES.has(spec.axesSpec[0].name),
      requireEnrichments: false,
    }) ?? [];
  const columns = resultPool(ctx).filter({ include: abundanceSelector });
  return deriveColumnOptions(columns).flatMap(({ id, label }): DatasetOption[] => {
    const ref = toPlRef(id);
    if (ref === undefined) return [];
    const primary = { ref, label };
    const filters = withFilters.find((o) => toColumnId(o.primary.ref) === id)?.filters;
    return [filters === undefined ? { primary } : { primary, filters }];
  });
}

/** The dataset picker's selection of the stored dataset and subset. */
export function toAbundanceSelection(pick: AbundancePick): DatasetSelection | undefined {
  const column = pick.abundanceRef === undefined ? undefined : toPlRef(pick.abundanceRef);
  if (column === undefined) return undefined;
  const filter = pick.filterRef === undefined ? undefined : toPlRef(pick.filterRef);
  return createDatasetSelection(createPrimaryRef(column, filter));
}

/** The dataset and subset a dataset picker selection stores. */
export function fromAbundanceSelection(selection: DatasetSelection | undefined): AbundancePick {
  const primary = selection?.primary;
  return {
    abundanceRef: primary === undefined ? undefined : toColumnId(primary.column),
    filterRef: primary?.filter === undefined ? undefined : toColumnId(primary.filter),
  };
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

// Internals

/** Key axes of the datasets this block filters: bulk and single-cell clonotypes, and variants. */
const DATASET_KEY_AXES: ReadonlySet<string> = new Set([
  "pl7.app/vdj/clonotypeKey",
  "pl7.app/vdj/scClonotypeKey",
  "pl7.app/variantKey",
]);

/** The upstream output a result-pool id names, as the ref the dataset picker works with. */
function toPlRef(id: ColumnUniversalId): PlRef | undefined {
  const key = parseColumnIdSafely(id);
  return isPlRef(key) ? key : undefined;
}
