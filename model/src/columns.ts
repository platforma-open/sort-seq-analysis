/**
 * The shared vocabulary this block reads and writes, and the predicates it locates inputs
 * with.
 *
 * Every column this block reads is located by its spec — axes, domain, annotations — never by a
 * literal column name. The narrowing that *is* permitted, and used below, matches a shared
 * vocabulary term: a name saying what a column *means*, identical across every block emitting
 * one. Forbidden is a lookup keyed on a particular column's own instance name.
 *
 * The variant axis is the reason this matters rather than being style. It is defined twice
 * upstream with incompatible domains, so identifying *it* by name resolves to the wrong
 * axis on some projects and the right one on others — with output of ordinary shape and
 * plausible content either way. Hence the abundance predicate below matches on axis
 * **count** plus annotations, and never names an axis.
 */

import type { AnchoredPColumnSelector, PColumnSpec, PObjectSpec } from "@platforma-sdk/model";

/** Annotation keys this block reads on upstream columns. */
export const Annotation = {
  IsAbundance: "pl7.app/isAbundance",
  AbundanceIsPrimary: "pl7.app/abundance/isPrimary",
  AbundanceNormalized: "pl7.app/abundance/normalized",
  Label: "pl7.app/label",
} as const;

/** Column *names* in the platform's shared vocabulary — what a column means, not which one it is. */
export const PColumnName = {
  /** Every per-sample metadata column upstream emits carries this name. */
  Metadata: "pl7.app/metadata",
  MutationCount: "pl7.app/repertoire/mutationCount",
  /** The variant axis's label column — shown as "Variant Id". */
  VariantLabel: "pl7.app/label",
  /** The per-variant mutation list, shown as "Mutations". */
  Mutations: "pl7.app/repertoire/mutations",
} as const;

/** Names this block mints, all under one namespace segment. */
export const FacsBin = {
  GateRankMean: "pl7.app/facsBin/gateRankMean",
  BinScore: "pl7.app/facsBin/binScore",
  GateFrequency: "pl7.app/facsBin/gateFrequency",
  GateReads: "pl7.app/facsBin/gateReads",
  GateAxis: "pl7.app/facsBin/gate",
  ConditionDomain: "pl7.app/facsBin/condition",
  ReferenceModeDomain: "pl7.app/facsBin/referenceMode",
  SortYieldCorrectedAnnotation: "pl7.app/facsBin/sortYieldCorrected",
} as const;

function isPColumnSpec(spec: PObjectSpec): spec is PColumnSpec {
  return spec.kind === "PColumn";
}

function annotation(spec: PColumnSpec, key: string): string | undefined {
  return spec.annotations?.[key];
}

/**
 * The anchor: per-sample abundance on the variant grain.
 *
 * Both annotation conditions are required and neither is redundant. The profiler emits a
 * second primary abundance column that is normalized (`pl7.app/readFraction`), so the
 * primary marker alone selects two candidates. And three further columns in the same block
 * carry the abundance marker without the primary one — one on the mutation-count axis, two
 * per-variant totals — so a predicate loose enough to admit them would compute a bin score
 * over aggregated totals and emit output of ordinary shape.
 *
 * Two axes are required by count rather than by name: the sample axis and the variant axis
 * are what a per-sample-per-variant abundance has, and naming the variant axis is the live
 * defect described at the top of this file.
 */
export function isAbundanceAnchor(spec: PObjectSpec): boolean {
  if (!isPColumnSpec(spec)) return false;
  if (spec.axesSpec.length !== 2) return false;
  return (
    annotation(spec, Annotation.AbundanceIsPrimary) === "true" &&
    annotation(spec, Annotation.AbundanceNormalized) === "false"
  );
}

/**
 * Per-sample metadata, in the anchor's context — the one option list the three roles are
 * picked from.
 *
 * **This predicate is expected to resolve to many.** It produces the option list, not an
 * answer. A spec predicate can establish that a column *is* per-sample metadata; it cannot
 * establish which role a given one plays, because the only per-column discriminator is a
 * value drawn from the user's own data. The roles are assigned by the user, one pick each.
 *
 * `pl7.app/metadata` is the column's **name**, not an annotation — every per-sample metadata
 * column upstream is literally named that, with the sample axis as its only axis and its
 * user-facing header in `pl7.app/label`. Matching it as an annotation matches nothing, and does
 * so silently: the option list comes back empty and the pickers look broken while the metadata
 * is plainly loaded.
 *
 * This is still a match on a shared-vocabulary *term*, not on a particular column's instance
 * name.
 *
 * The single axis is bound to the anchor's sample axis by the anchor context rather than by
 * name.
 */
export const metadataSelector: AnchoredPColumnSelector = {
  axes: [{ anchor: "main", idx: 0 }],
  name: PColumnName.Metadata,
};

/**
 * The variants' mutation count. Resolved in the workflow rather than here — this constant
 * exists so the model and the workflow state the same predicate, and so a reader can see
 * all three in one place.
 *
 * The alphabet domain is load-bearing rather than a detail. The profiler emits the count at
 * two grains and keeps them apart by exactly this domain. At the nucleotide grain a library
 * of synonymous barcodes for one wild-type protein yields several rows with a count of
 * zero, which reads as the parent being *unidentifiable* — so `binScore` would be emitted
 * in the cancelled form for a run whose parent is in fact perfectly well defined.
 */
export const mutationCountSelector: AnchoredPColumnSelector = {
  axes: [{ anchor: "main", idx: 1 }],
  name: PColumnName.MutationCount,
  domain: { "pl7.app/alphabet": "aminoacid" },
};
