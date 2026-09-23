/**
 * The shared vocabulary this block reads and writes, and the predicates it locates inputs with.
 *
 * Columns are located by spec, never by instance name. The variant axis is defined twice
 * upstream with incompatible domains, so naming it resolves to the wrong axis on some projects
 * with plausible output either way — hence the abundance predicate matches on axis COUNT plus
 * annotations and never names an axis.
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
  /** The **sample** axis's label column. Same name as `VariantLabel`; the axis picks one. */
  SampleLabel: "pl7.app/label",
  /** The per-variant mutation list, shown as "Mutations". */
  Mutations: "pl7.app/repertoire/mutations",
} as const;

/** "Which gate" — an axis in the distribution view, a domain key on the enrichment columns.
 *  One constant so a rename cannot break the join silently. */
const GATE = "pl7.app/facsBin/gate";

/** Names this block mints, all under one namespace segment. */
export const FacsBin = {
  GateRankMean: "pl7.app/facsBin/gateRankMean",
  BinScore: "pl7.app/facsBin/binScore",
  GateEnrichment: "pl7.app/facsBin/gateEnrichment",
  GateFrequency: "pl7.app/facsBin/gateFrequency",
  GateReads: "pl7.app/facsBin/gateReads",
  GateAxis: GATE,
  ConditionDomain: "pl7.app/facsBin/condition",
  /**
   * A domain key, NOT an axis. The Mutation Explorer's score picker only sees columns keyed on
   * the variant axis alone, so a gate axis would hide these and add a one-choice selector.
   */
  GateDomain: GATE,
  ReferenceModeDomain: "pl7.app/facsBin/referenceMode",
  /**
   * The per-gate baseline, keyed on `[parentId]` rather than the variant axis — one row per
   * parent, so a dataset carrying several reports each. Emitted on every run.
   */
  /** Per parent, for the whole run. Emitted in every mode, so the parents are always visible. */
  ParentVariants: "pl7.app/facsBin/parentVariants",
  ParentReads: "pl7.app/facsBin/parentReads",
  /** The enrichment divided by its own parent's baseline. 1.0 is a variant of no effect. */
  GateEnrichmentVsBaseline: "pl7.app/facsBin/gateEnrichmentVsBaseline",
  /** The noise band on `binScore`, per condition. Gate-ranking mode only. */
  BinScoreBaselineLevel: "pl7.app/facsBin/binScoreBaselineLevel",
  GateBaselineLevel: "pl7.app/facsBin/gateBaselineLevel",
  GateBaselineP5: "pl7.app/facsBin/gateBaselineP5",
  GateBaselineP95: "pl7.app/facsBin/gateBaselineP95",
  GateBaselineVariants: "pl7.app/facsBin/gateBaselineVariants",
  SortYieldCorrectedAnnotation: "pl7.app/facsBin/sortYieldCorrected",
  /** The baseline as measured at this column's gate. Absent where none was resolved. */
  BaselineLevelAnnotation: "pl7.app/facsBin/baselineLevel",
  /** The four percentiles, as a JSON object. Never a standard error — see `BaselineSummary`. */
  BaselineSpreadAnnotation: "pl7.app/facsBin/baselineSpread",
  BaselineVariantsAnnotation: "pl7.app/facsBin/baselineVariants",
} as const;

/**
 * What this number is referenced to. The first two describe `binScore`'s parent cancellation;
 * the rest name the baseline a `gateEnrichment` is read against.
 *
 * `Input` covers a declared baseline that could not be resolved: the ratio is still against the
 * input, and claiming the baseline would describe a reference the column does not have.
 */
export const ReferenceMode = {
  Referenced: "referenced",
  Cancelled: "cancelled",
  Input: "input",
  BaselineWildType: "wild-type",
  BaselineSynonymous: "synonymous",
  BaselineSequence: "sequence",
} as const;

/** Domain key on the variant axis that tells the nucleotide grain from the protein grain. */
export const AlphabetDomain = "pl7.app/alphabet";
export const Alphabet = { Nucleotide: "nucleotide", AminoAcid: "aminoacid" } as const;

function isPColumnSpec(spec: PObjectSpec): spec is PColumnSpec {
  return spec.kind === "PColumn";
}

function annotation(spec: PColumnSpec, key: string): string | undefined {
  return spec.annotations?.[key];
}

/**
 * The anchor: per-sample abundance on the variant grain.
 *
 * Neither annotation is redundant. The profiler emits a second primary abundance column that is
 * normalized, and three more carry the abundance marker without the primary one — admitting
 * those computes a bin score over aggregated totals with output of ordinary shape.
 *
 * Two axes by COUNT, not name — see the file header.
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
 * Per-sample metadata — the option list the three roles are picked from, so it is expected to
 * resolve to many. Which role a column plays is the user's pick; no spec predicate can tell.
 *
 * `pl7.app/metadata` is the column's NAME, not an annotation. Matching it as an annotation
 * matches nothing silently: the list comes back empty and the pickers look broken.
 */
export const metadataSelector: AnchoredPColumnSelector = {
  axes: [{ anchor: "main", idx: 0 }],
  name: PColumnName.Metadata,
};

/**
 * The sample axis's label column. `pl7.app/isLabel` is required alongside the name, which the
 * variant label column shares.
 */
export const sampleLabelSelector: AnchoredPColumnSelector = {
  axes: [{ anchor: "main", idx: 0 }],
  name: PColumnName.SampleLabel,
  annotations: { "pl7.app/isLabel": "true" },
};

/**
 * The variants' mutation count. Resolved in the workflow; this constant keeps the two sides
 * stating one predicate.
 *
 * The grain follows the dataset and is deliberately NOT pinned to an alphabet. The axis
 * reference does the work: the profiler emits both counts on their own variant axes, so exactly
 * one is reachable from any anchor, and the nucleotide column counts nucleotide mutations — so
 * only the exact parent has zero at either grain.
 */
export const mutationCountSelector: AnchoredPColumnSelector = {
  axes: [{ anchor: "main", idx: 1 }],
  name: PColumnName.MutationCount,
};
