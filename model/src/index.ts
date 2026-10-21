import {
  BlockModelV3,
  type BlockRenderCtx,
  type ColumnRecipe,
  columnValueLabel,
  createPFrameForGraphs,
  createPlDataTableV3,
  discoverTableColumnSnaphots,
  type InferOutputsType,
  parseColumnValueId,
} from "@platforma-sdk/model";
import { kind } from "@platforma-open/milaboratories.sort-seq-analysis.kind";
import { getAbundanceOptions, isNucleotideDataset } from "./abundance";
import type { ColumnPickerOption } from "./column_access";
import { exact, getOutputColumns, toPColumns } from "./column_access";
import { Alphabet, AlphabetDomain, FacsBin, PColumnName } from "./columns";
import { blockDataModel } from "./dataModel";
import type { MetadataRole } from "./metadata";
import { getMetadataOptions, getMetadataValues, getSampleLabels, narrowToRole } from "./metadata";
import type { BlockArgs, BlockData, RunManifest } from "./types";

export { blockDataModel, defaultDistributionGraphState } from "./dataModel";
export * from "./columns";
export * from "./types";
export type { ColumnPickerOption } from "./column_access";
export type { MetadataColumnValues } from "./metadata";

/**
 * Whether the baseline is offered. Pairs with `EMIT_BASELINE_COLUMNS` in
 * `build-columns.tpl.tengo` — the two must hold the same value. On alone, the user picks a
 * baseline and no column carries it; off alone, the columns claim a baseline nobody chose.
 */
export const BASELINE_AVAILABLE = true;

/**
 * Every configuration rule, checked here and nowhere else. The one data-value rule (sort
 * fractions) belongs to the computation and is deliberately not duplicated here.
 */
export function settingsIssues(data: BlockData): string[] {
  const issues: string[] = [];
  // 1, 2, 3 absent — nothing to read.
  if (data.abundanceRef === undefined) issues.push("Select an abundance dataset");
  if (data.conditionColumnRef === undefined) issues.push("Select the condition column");
  if (data.gateColumnRef === undefined) issues.push("Select the gate column");

  // The three roles must be distinct columns. Condition and gate picked identically would
  // score single-gate conditions — ordinary-looking output, silently meaningless.
  const roles = [data.conditionColumnRef, data.gateColumnRef, data.sortFractionColumnRef].filter(
    (ref): ref is NonNullable<typeof ref> => ref !== undefined,
  );
  if (new Set(roles).size !== roles.length) {
    issues.push("The condition, gate and sort-fraction columns must be three different columns");
  }

  // The order is a selection, so coverage is deliberately NOT checked: a gate column carrying
  // an input or a specificity arm is the ordinary case. Only non-emptiness and that every gate
  // was picked from the gate column. A gate the column no longer carries is shown as not
  // available in the drawer; `data` does not hold the column's values, so it is not refused
  // here, and neither is excluding every condition.
  //
  // Guarded on the pick so a fresh block does not get two complaints for one unmade choice.
  const gateColumn = data.gateColumnRef;
  if (gateColumn !== undefined) {
    if (data.gateOrder.length === 0) {
      issues.push(
        "Keep at least one gate in the order — the gate column has none, or every gate has been removed",
      );
    }
    const foreign = [...data.gateOrder, ...(data.inputGate === undefined ? [] : [data.inputGate])]
      .filter((picked) => parseColumnValueId(picked).column !== gateColumn)
      .map(columnValueLabel);
    if (foreign.length > 0) {
      issues.push(`Gate value(s) picked from another column: ${foreign.join(", ")}`);
    }
  }

  const conditionColumn = data.conditionColumnRef;
  if (conditionColumn !== undefined) {
    const foreign = data.excludedConditions
      .filter((picked) => parseColumnValueId(picked).column !== conditionColumn)
      .map(columnValueLabel);
    if (foreign.length > 0) {
      issues.push(`Excluded condition(s) picked from another column: ${foreign.join(", ")}`);
    }
  }

  if (data.readFloor !== undefined && data.readFloor < 0) {
    issues.push("The read-count floor cannot be negative");
  }

  // Neither fact holds, so there is nothing to compute.
  if (data.gatesOrdered === false && data.inputGate === undefined) {
    issues.push(
      "Order the gates, or name an unsorted input — with neither there is nothing to compute",
    );
  }

  if (data.inputGate !== undefined) {
    if (data.gateOrder.includes(data.inputGate)) {
      // A gate that referenced itself would give exactly 1 everywhere. Reachable by
      // reordering after the pick, so the option list alone is not enough.
      issues.push(
        `The input '${columnValueLabel(data.inputGate)}' is also a ranked gate — remove it from the gate order`,
      );
    }
  }

  // The baseline's grain requirement is NOT checked here: the args lambda cannot read a spec,
  // and the run degrades loudly anyway. The drawer shows a warning instead.

  return issues;
}

/**
 * With an entry for the plot's title, without one for the nav. The count is what the run drew,
 * not the computation's cut — that is a maximum, and would read "Top 20" over twelve variants.
 */
export function distributionPlotTitle(
  condition: string,
  entry?: { variantsPlotted: number; variantsScored: number },
): string {
  const truncated = entry !== undefined && entry.variantsPlotted < entry.variantsScored;
  return truncated
    ? `Variant Frequency Top ${entry.variantsPlotted} — ${condition}`
    : `Variant Frequency — ${condition}`;
}

export const platforma = BlockModelV3.create({ dataModel: blockDataModel, kind })
  .args<BlockArgs>((data) => {
    // Throwing disables Run but carries no reason to the user; `settingsIssues` names it.
    const issues = settingsIssues(data);
    if (issues.length > 0) throw new Error(issues.join("; "));

    // `settingsIssues` refuses each of these absent; checked again so the type says so.
    const { abundanceRef, conditionColumnRef, gateColumnRef } = data;
    if (
      abundanceRef === undefined ||
      conditionColumnRef === undefined ||
      gateColumnRef === undefined
    ) {
      throw new Error("Select the dataset, the condition column and the gate column");
    }

    // Two facts, not a mode. An enrichment needs a reference, so naming one is what asks for
    // it; ranks need an order, so the toggle is what asks for those. `inputGate` carries the
    // first straight through, so only the second needs a local.
    const ordered = data.gatesOrdered !== false;

    return {
      abundanceRef,
      conditionColumnRef,
      gateColumnRef,
      // Position becomes the rank, contiguous over the gates the list holds — a gap would
      // move every score, since ranks enter the weighted mean as numbers. The key set also
      // tells the computation which gates the run covers.
      //
      // Canonicalised so an edit with no effect produces the same bytes and does not fire
      // the staleness gate. Keyed by the gate's column value id, which the workflow turns back
      // into the gate value.
      gateRanks: Object.fromEntries(data.gateOrder.map((gate, index) => [gate, index + 1])),
      excludedConditions: [...data.excludedConditions].sort(),
      // `undefined` rather than a value: the workflow omits the field and the computation
      // reads the absence as the behaviour.
      readFloor: data.readFloor,
      sortFractionColumnRef: data.sortFractionColumnRef,
      // Projected only when in use: four `undefined`s drop out of the args JSON, so an
      // existing block's bytes are unchanged and no instance goes stale on upgrade.
      inputGate: data.inputGate,
      // Projected only when false, so an ordered run's bytes are unchanged.
      gatesOrdered: ordered ? undefined : false,
      // Every baseline output sits beside a per-gate enrichment, so without an input there is
      // nothing for it to reach and the field is dropped. `BaselineOption` still admits two
      // values the drawer does not offer, so they pass through for a block already holding one.
      baseline: BASELINE_AVAILABLE && data.inputGate !== undefined ? data.baseline : undefined,
      baselineSequence:
        BASELINE_AVAILABLE && data.inputGate !== undefined && data.baseline === "sequence"
          ? data.baselineSequence
          : undefined,
    };
  })

  // ---------------------------------------------------------------------------
  // Option lists. Four pickers, two predicates.
  // ---------------------------------------------------------------------------

  /** The anchor. Matched on axis count plus the two abundance annotations, never on a name. */
  .output("abundanceOptions", (ctx) => getAbundanceOptions(ctx))

  /**
   * Whether the selected dataset is at the nucleotide grain. The one fact the drawer needs that
   * `data` cannot hold. Feeds the synonymous-baseline option, deliberately not
   * `settingsIssues` — that choice is not a broken run, just an empty baseline.
   */
  .output("datasetIsNucleotide", (ctx) => {
    const abundanceRef = ctx.data.abundanceRef;
    if (abundanceRef === undefined) return undefined;
    return isNucleotideDataset(ctx, abundanceRef);
  })

  /** The pickers, each offering what the other two roles do not already hold. */
  .output("conditionOptions", (ctx) => roleOptions(ctx, "conditionColumnRef"))
  .output("gateOptions", (ctx) => roleOptions(ctx, "gateColumnRef"))
  .output("sortFractionOptions", (ctx) => roleOptions(ctx, "sortFractionColumnRef"))

  // ---------------------------------------------------------------------------
  // The controls that need a picked column's values rather than its spec.
  // ---------------------------------------------------------------------------

  /**
   * The values of every metadata column on offer, so the gate order can be seeded in the same
   * gesture as the gate pick, and the picked gates, input and excluded conditions be shown by
   * the values they pick.
   */
  .output("metadataValues", (ctx) => {
    const abundanceRef = ctx.data.abundanceRef;
    if (abundanceRef === undefined) return undefined;
    return getMetadataValues(ctx, abundanceRef, ctx.data);
  })

  /** Sample names by sample id, for the pooling report's sample ids. */
  .output("sampleLabels", (ctx) => {
    const abundanceRef = ctx.data.abundanceRef;
    if (abundanceRef === undefined) return undefined;
    return getSampleLabels(ctx, abundanceRef);
  })

  // ---------------------------------------------------------------------------
  // The three views.
  // ---------------------------------------------------------------------------

  /**
   * Main — one row per variant, every retained condition's scores plus the pool columns on the
   * variant axis.
   *
   * Anchored on `gateRankMean`, not `binScore`: the anchor decides whether the table renders
   * at all, and `binScore` is legitimately absent where a parent went unscored.
   *
   * The anchor is one CONCRETE column's spec from this block's own output. A selector naming
   * the column would be ambiguous over N conditions and could not tell this instance from a
   * second sort-seq block. Which condition anchors is arbitrary; sorting only makes it stable.
   */
  .outputWithStatus("resultsTable", (ctx) => buildScoresTable(ctx, Alphabet.AminoAcid))

  /**
   * The nucleotide table, present only on a run that measured at that grain. A second table
   * rather than more columns: the two levels sit on different axes with different row counts,
   * so one table would repeat each protein's score down its variants.
   */
  .outputWithStatus("ntResultsTable", (ctx) => buildScoresTable(ctx, Alphabet.Nucleotide))

  /** Which levels the run produced, so the UI shows one table or two. */
  .output("scoreLevels", (ctx) => {
    const own = getOutputColumns(ctx, ctx.outputs?.resolve("scoresPf"))?.getColumns();
    if (!own) return undefined;
    return scoreLevelsOf(own);
  })
  .output("distributionConditions", (ctx) => {
    const columns = getOutputColumns(ctx, ctx.outputs?.resolve("distributionPf"))?.getColumns();
    if (!columns) return undefined;
    return distributionConditionsOf(columns);
  })

  /**
   * The graph frame, held out of exports and the pool. ONE frame covering every condition, so
   * it never swaps and each page's saved chart state keeps pointing at a live column.
   *
   * `createPFrameForGraphs` rather than `ctx.createPFrame`: only it pulls in the variant
   * axis's label column, without which charts draw raw keys.
   */
  .outputWithStatus("distributionPf", (ctx) => {
    const columns = getOutputColumns(ctx, ctx.outputs?.resolve("distributionPf"))?.getColumns();
    if (!columns) return undefined;
    return createPFrameForGraphs(ctx, toPColumns(columns));
  })

  /** The same columns as id+spec pairs, so a page binds to real specs instead of names. */
  .output("distributionPfCols", (ctx) => {
    const columns = getOutputColumns(ctx, ctx.outputs?.resolve("distributionPf"))?.getColumns();
    if (!columns) return undefined;
    return columns.map((column) => ({ id: column.id, spec: column.getSpec() }));
  })

  /** The not-ready-safe accessor is required: plain `getDataAsJson` throws mid-run. */
  .output("manifest", (ctx) =>
    ctx.outputs?.resolve("manifest")?.getDataAsJsonOrUndefined<RunManifest>(),
  )

  .output("logHandle", (ctx) => ctx.outputs?.resolve("logHandle")?.getLogHandle())
  .output("isRunning", (ctx) => ctx.outputs?.getIsReadyOrError() === false)

  /** Why the block is not runnable, in the user's words — the platform only says "incomplete". */
  .output("settingsIssues", (ctx) => settingsIssues(ctx.data))

  /**
   * What this configuration will produce, in the user's words. It replaces the mode control:
   * the two facts decide the run, and this states the consequence rather than asking for it.
   */
  .output("runShape", (ctx) => {
    const ordered = ctx.data.gatesOrdered !== false;
    const enrichment = ctx.data.inputGate !== undefined;
    // Neither fact holds, so this states a setting to fix rather than a result to expect.
    if (!ordered && !enrichment) {
      return {
        level: "warn" as const,
        message: "Order the gates, or name an unsorted input to run the block.",
      };
    }

    const metrics = [
      ...(ordered ? ["Mean bin", "Mean bin vs parent"] : []),
      ...(enrichment ? ["Enrichment per gate"] : []),
    ];
    const gates = ordered ? "ordered gates" : "unordered gates";
    const input = enrichment ? " and an unsorted input" : "";
    const noun = metrics.length === 1 ? "metric" : "metrics";

    return {
      level: "info" as const,
      message: `With ${gates}${input}, the following ${noun} will be produced: ${metrics.join(", ")}.`,
    };
  })

  /** Exposed so the UI can show it as the subtitle field's placeholder. */
  .output("defaultBlockLabel", (ctx) => deriveBlockLabel(ctx.data))

  /** The inverse of the data model's `init`, field for field. Mandatory — `done()` throws without it. */
  .templateParams((data) => ({
    conditionColumnRef: data.conditionColumnRef,
    gateColumnRef: data.gateColumnRef,
    sortFractionColumnRef: data.sortFractionColumnRef,
    gateOrder: data.gateOrder,
    gateColumnLabel: data.gateColumnLabel,
  }))

  /** Constant. What an instance is configured for belongs in the subtitle. */
  .title(() => "Sort-Seq Analysis")

  /** The user's override wins; otherwise the label derived from the gate selection. */
  .subtitle((ctx) => ctx.data.customBlockLabel || deriveBlockLabel(ctx.data))

  /**
   * The scores tables, then one distribution page per condition. The condition rides in the
   * query string; routes are keyed on pathname alone.
   *
   * `encodeURIComponent` matters beyond `&=#`: it escapes `+` to `%2B`, and a bare `+` decodes
   * back as a space — `CD4+` being an ordinary condition value.
   */
  .sections((ctx) => {
    const columns = getOutputColumns(ctx, ctx.outputs?.resolve("distributionPf"))?.getColumns();

    // Each entry must stay an `as const` literal with no annotation on the array: the route's
    // query type is derived from the href's template literal type.
    const levels = getOutputColumns(ctx, ctx.outputs?.resolve("scoresPf"))?.getColumns();
    const hasNt = scoreLevelsOf(levels ?? []).includes(Alphabet.Nucleotide);

    return [
      // Must match the page's own title.
      { type: "link" as const, href: "/" as const, label: "AA Scores" },
      ...(hasNt ? [{ type: "link" as const, href: "/nt" as const, label: "NT Scores" }] : []),
      ...(columns ? distributionConditionsOf(columns) : []).map((condition) => ({
        type: "link" as const,
        href: `/distribution?condition=${encodeURIComponent(condition)}` as const,
        // No manifest entry: the count belongs on the plot, not shifting in a nav list mid-run.
        label: distributionPlotTitle(condition),
      })),
    ];
  })

  .done();

/**
 * The block subtitle when the user has not overridden it. The gate selection is what
 * distinguishes two instances on one project. A pure function of `data`.
 */
export function deriveBlockLabel(data: BlockData): string {
  const ordered = data.gateOrder;
  if (!data.gateColumnLabel || ordered.length === 0) return "Select gates";

  // Every gate, not just the ends: a reordering of the middle is exactly the change that
  // silently moves every score.
  return `${data.gateColumnLabel}: ${ordered.map(columnValueLabel).join("-")}`;
}

export type BlockOutputs = InferOutputsType<typeof platforma>;

// Internals

/** The metadata options a role picker offers. */
function roleOptions(
  ctx: BlockRenderCtx<BlockArgs, BlockData>,
  role: MetadataRole,
): ColumnPickerOption[] | undefined {
  const abundanceRef = ctx.data.abundanceRef;
  if (abundanceRef === undefined) return undefined;
  const options = getMetadataOptions(ctx, abundanceRef);
  if (options === undefined) return undefined;
  return narrowToRole(options, ctx.data, role);
}

/** The grains the run scored at, read off the alphabet domain of its score columns. */
function scoreLevelsOf(columns: readonly ColumnRecipe[]): string[] {
  const levels = new Set<string>();
  for (const column of columns) {
    const alphabet = column.getSpec().domain?.[AlphabetDomain];
    if (alphabet !== undefined) levels.add(alphabet);
  }
  return [...levels].sort();
}

/** Conditions read off the domain key, sorted — they carry no order of their own. */
function distributionConditionsOf(columns: readonly ColumnRecipe[]): string[] {
  const conditions = new Set<string>();
  for (const column of columns) {
    const condition = column.getSpec().domain?.[FacsBin.ConditionDomain];
    if (condition !== undefined) conditions.add(condition);
  }
  return [...conditions].sort();
}

/**
 * One scores table for one grain. A nucleotide run emits two column families on two axes, told
 * apart by the `pl7.app/alphabet` domain. `undefined` where the run produced none.
 */
function buildScoresTable(ctx: BlockRenderCtx<BlockArgs, BlockData>, alphabet: string) {
  const all = getOutputColumns(ctx, ctx.outputs?.resolve("scoresPf"));
  if (!all) return undefined;
  // The alphabet is the only thing separating the two families: they share every name and
  // condition domain, and mixing them joins protein scores to nothing.
  const own = all
    .filter({ include: { domain: { [AlphabetDomain]: [exact(alphabet)] } } })
    .getColumns()
    .map((column) => ({ column, spec: column.getSpec() }));
  if (own.length === 0) return undefined;

  // Unordered gates produce no `gateRankMean`, so the enrichment carries the anchor there.
  // Both are keyed on the variant axes, so the key shape below is the same either way.
  const pickAnchor = (name: string) =>
    own
      .filter((column) => column.spec.name === name)
      .sort((a, b) =>
        (
          (a.spec.domain?.[FacsBin.ConditionDomain] ?? "") +
          "\0" +
          (a.spec.domain?.[FacsBin.GateDomain] ?? "")
        ).localeCompare(
          (b.spec.domain?.[FacsBin.ConditionDomain] ?? "") +
            "\0" +
            (b.spec.domain?.[FacsBin.GateDomain] ?? ""),
        ),
      )[0];
  const anchor = pickAnchor(FacsBin.GateRankMean) ?? pickAnchor(FacsBin.GateEnrichment);
  if (!anchor) return undefined;

  // Primary columns, so they are always shown and never compete with a pool namesake.
  //
  // Filtered to the anchor's own key shape: `scoresPf` also carries the per-position baseline
  // on `[parentId, position]`, and passing that in fails the whole table with
  // `discoverColumns failed`. Compared on axis names, so a new differently-keyed column does
  // not need this list updated.
  const anchorKey = anchor.spec.axesSpec.map((axis) => axis.name).join("\0");
  const primaryColumns = own
    .filter((column) => column.spec.axesSpec.map((axis) => axis.name).join("\0") === anchorKey)
    .map(({ column }) => column);

  // Everything else the variant axis reaches.
  //
  // The WHOLE `pl7.app/facsBin/` namespace is excluded, this block's own included. A second
  // sort-seq block's columns are identical in everything discovery matches on, and a selector
  // can require a domain value but cannot refuse one — so there is no selector admitting ours
  // and refusing a sibling's. This also drops the duplicate our own `exports.pf` creates.
  const { primary, secondary } = discoverTableColumnSnaphots(ctx, {
    anchors: { main: anchor.spec },
    // Strict axis equality. "related" reaches every column the variant axis participates in,
    // giving a row per variant per position per gate.
    selector: {
      mode: "exact",
      exclude: [{ name: [{ type: "regex", value: "^pl7\\.app/facsBin/.*$" }] }],
    },
  });

  return createPlDataTableV3(ctx, {
    primaryColumns,
    columns: [...primary, ...secondary],
    tableState:
      alphabet === Alphabet.Nucleotide ? ctx.data.ntResultsTableState : ctx.data.resultsTableState,
    displayOptions: {
      /**
       * First match wins, and an unmatched column keeps its own annotation — upstream sets
       * `default` on nearly everything, so the catch-all last is required.
       *
       * `optional` rather than `hidden`: they stay one click away in the column picker.
       */
      visibility: [
        { match: { name: exact(FacsBin.GateRankMean) }, visibility: "default" },
        { match: { name: exact(FacsBin.BinScore) }, visibility: "default" },
        { match: { name: exact(FacsBin.GateEnrichment) }, visibility: "default" },
        { match: { name: exact(PColumnName.VariantLabel) }, visibility: "default" },
        { match: { name: exact(PColumnName.Mutations) }, visibility: "default" },
        { match: { name: ".*" }, visibility: "optional" },
      ],
    },
  });
}
