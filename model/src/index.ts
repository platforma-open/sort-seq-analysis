import {
  BlockModelV3,
  createPFrameForGraphs,
  createPlDataTableV3,
  DataColumn,
  discoverTableColumnSnaphots,
  type InferOutputsType,
  type PColumn,
  type PColumnSpec,
  type PColumnValues,
  type StringMatcher,
  type SUniversalPColumnId,
} from "@platforma-sdk/model";
import { Annotation, FacsBin, isAbundanceAnchor, metadataSelector, PColumnName } from "./columns";
import { blockDataModel } from "./dataModel";
import type { BlockArgs, BlockData, RunManifest } from "./types";

export { blockDataModel, defaultDistributionGraphState } from "./dataModel";
export * from "./columns";
export * from "./types";

/**
 * Every configuration rule, checked here and **nowhere else**. These six are decidable from the
 * arguments and snapshotted column values alone, so they are refused before the run starts.
 *
 * The two data-value rules — sort fractions, one sample per condition-and-gate group — belong
 * to the computation and are deliberately not approximated here: a duplicated rule is one that
 * will disagree, and it fails by drifting looser, so the settings pass and the run fails anyway
 * with a different message.
 */
export function settingsIssues(data: BlockData): string[] {
  const issues: string[] = [];
  // 1, 2, 3 absent — nothing to read.
  if (data.abundanceRef === undefined) issues.push("Select an abundance dataset");
  if (data.conditionColumnRef === undefined) issues.push("Select the condition column");
  if (data.gateColumnRef === undefined) issues.push("Select the gate column");

  // 2, 3 and 7 not three distinct columns. Each role is a different fact about a sample and
  // one column cannot carry two of them. Nothing else would catch the confusion: condition
  // and gate picked identically would map every gate to its own condition, rank one value
  // per condition and score single-gate conditions — output of ordinary shape, silently
  // meaningless.
  const roles = [data.conditionColumnRef, data.gateColumnRef, data.sortFractionColumnRef].filter(
    (ref): ref is NonNullable<typeof ref> => ref !== undefined,
  );
  if (new Set(roles).size !== roles.length) {
    issues.push("The condition, gate and sort-fraction columns must be three different columns");
  }

  // 4 the order is a **selection**, not a ranking of everything the column carries. The
  // gates it lists, in the order it lists them, are the run's binding ladder; a gate the
  // user removed is not part of the run at all, exactly as an excluded condition is not.
  //
  // So coverage is deliberately not checked. A gate column carrying values that are not
  // rungs on this ladder — an unsorted input, a specificity arm, a stability arm — is the
  // ordinary case for a sort-seq run, and demanding a rank for each would refuse a
  // configuration the computation runs perfectly well.
  //
  // What is left is that the list is not empty, and that it names nothing the column does
  // not carry; the latter can drift if upstream re-emits the column and the user does not
  // re-pick it.
  // Only once a gate column is picked. Collecting every issue rather than throwing on the
  // first means an unguarded check here would tell a freshly added block that "the gate column
  // has no values to rank" while also telling it to select a gate column — two complaints for
  // one unmade choice.
  if (data.gateColumnRef !== undefined) {
    if (data.gateValues.length === 0) {
      issues.push("The gate column has no values to rank");
    } else if (data.gateOrder.length === 0) {
      issues.push("Keep at least one gate in the order — every gate has been removed");
    }
    const unknown = data.gateOrder.filter((value) => !data.gateValues.includes(value));
    if (unknown.length > 0) {
      issues.push(`Ordered value(s) the gate column does not carry: ${unknown.join(", ")}`);
    }
  }

  // 5 excluding every value. Refused rather than allowed to produce nothing, because an
  // empty result is indistinguishable from a failed run and the user's own last action
  // caused it — naming the cause while the settings are still on screen is the point.
  if (
    data.conditionValues.length > 0 &&
    data.conditionValues.every((value) => data.excludedConditions.includes(value))
  ) {
    issues.push("At least one condition must remain — every value is currently excluded");
  }

  // 6 negative.
  if (data.readFloor !== undefined && data.readFloor < 0) {
    issues.push("The read-count floor cannot be negative");
  }

  return issues;
}

/**
 * A bare string in a column selector is treated as a **regex**, so an exact name has to say so
 * — otherwise `pl7.app/label` would also match any longer name containing it.
 */
function exact(name: string): StringMatcher {
  return { type: "exact", value: name };
}

/**
 * A multi-condition run's column pairs are told apart by the condition domain key alone, so
 * that key is the only place the condition can be read from. Sorted, because conditions carry
 * no order of their own and callers must agree on one.
 */
function distributionConditionsOf<C extends { spec: PColumnSpec }>(
  columns: readonly C[],
): string[] {
  const conditions = new Set<string>();
  for (const column of columns) {
    const condition = column.spec.domain?.[FacsBin.ConditionDomain];
    if (condition !== undefined) conditions.add(condition);
  }
  return [...conditions].sort();
}

/**
 * Called two ways: with an entry for the plot's own title, carrying the drawn-variant count,
 * and without one for the nav, which should name where a link goes rather than how much of it
 * is drawn.
 *
 * The count comes from what the run actually drew, not from the cut the computation applies —
 * that cut is a maximum, so repeating it here would read "Top 20" over a library of twelve. And
 * where nothing was left out the suffix is absent entirely, rather than claiming a caveat.
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

export const platforma = BlockModelV3.create(blockDataModel)
  .args<BlockArgs>((data) => {
    // Throwing marks args invalid and disables Run, but carries no reason to the user — the
    // `settingsIssues` output below is what names the offending input.
    const issues = settingsIssues(data);
    if (issues.length > 0) throw new Error(issues.join("; "));

    return {
      abundanceRef: data.abundanceRef!,
      conditionColumnRef: data.conditionColumnRef!,
      gateColumnRef: data.gateColumnRef!,
      // Canonicalised so an edit that does not change what the workflow would do — a gate
      // re-ranked back to where it started, an exclusion added and removed — produces the
      // same bytes and does not fire the staleness gate.
      // Position becomes the rank: first in the list is gate 1, the weakest binder. The
      // computation weights by these integers, so the list's order is the whole signal.
      // Ranks are contiguous over the gates the list actually holds — a removed gate leaves
      // no gap, because the ladder is the selection and rank values enter the weighted mean
      // as numbers. A gap would move every score without naming a reason.
      // The map is also what tells the computation which gates the run covers: a gate absent
      // from it is dropped along with its samples.
      gateRanks: Object.fromEntries(data.gateOrder.map((gate, index) => [gate, index + 1])),
      excludedConditions: [...data.excludedConditions].sort(),
      // Both optional arguments are passed through as `undefined` when unset rather than
      // being given a value. The workflow omits the field entirely and the computation
      // reads the absence as the behaviour this spec states.
      readFloor: data.readFloor,
      sortFractionColumnRef: data.sortFractionColumnRef,
    };
  })

  // ---------------------------------------------------------------------------
  // Option lists. Four pickers, two predicates.
  // ---------------------------------------------------------------------------

  /** The anchor. Matched on axis count plus the two abundance annotations, never on a name. */
  .output("abundanceOptions", (ctx) => ctx.resultPool.getOptions(isAbundanceAnchor))

  /**
   * Every per-sample metadata column in the anchor's context, as one list: the anchored id
   * the pickers store, the label they display, and the PObjectId the UI needs to read the
   * column's values out of the published PFrame.
   *
   * One query feeding four consumers, rather than one query per picker.
   */
  .output("metadataColumns", (ctx) => {
    const anchor = ctx.data.abundanceRef;
    if (!anchor) return undefined;

    const anchorCtx = ctx.resultPool.resolveAnchorCtx({ main: anchor });
    if (!anchorCtx) return undefined;

    const columns = ctx.resultPool.getAnchoredPColumns({ main: anchor }, [metadataSelector]);
    if (!columns) return undefined;

    return columns.map((column) => ({
      // Derived from the column's own spec rather than by position, so the anchored id and
      // the PObjectId are correlated by construction — pairing two same-length lists by
      // index would break the first time the pool returned them in a different order.
      value: anchorCtx.deriveS(column.spec),
      objectId: column.id,
      label: column.spec.annotations?.[Annotation.Label] ?? column.spec.name,
    }));
  })

  /** The pickers, each offering what the other two roles do not already hold. */
  .output("conditionOptions", (ctx) => narrowTo(ctx, "conditionColumnRef"))
  .output("gateOptions", (ctx) => narrowTo(ctx, "gateColumnRef"))
  .output("sortFractionOptions", (ctx) => narrowTo(ctx, "sortFractionColumnRef"))

  // ---------------------------------------------------------------------------
  // The two controls that need a picked column's values rather than its spec.
  // ---------------------------------------------------------------------------

  /**
   * **Every** metadata column, published so the UI can fetch their values.
   *
   * Not just the picked ones — and that distinction is the whole point. The gate-order and
   * exclusion controls are driven by a snapshot the UI writes at the moment the user picks a
   * column, so the values have to be in hand *before* the pick. Publishing only what was
   * already picked makes the frame lag the gesture by one round trip: the snapshot writes an
   * empty list, the gate-order control never appears, and nothing says why.
   *
   * Sample metadata is a handful of columns over the sample count, so fetching all of them
   * up front is cheap.
   */
  .output("metadataColumnsPframe", (ctx) => {
    const anchor = ctx.data.abundanceRef;
    if (!anchor) return undefined;

    const columns = ctx.resultPool.getAnchoredPColumns({ main: anchor }, [metadataSelector]);
    if (!columns || columns.length === 0) return undefined;

    return ctx.createPFrame(columns as PColumn<PColumnValues>[]);
  })

  // ---------------------------------------------------------------------------
  // The three views.
  // ---------------------------------------------------------------------------

  /**
   * Main — one row per variant, carrying both scored columns for every retained condition
   * together with the pool columns that share the variant axis.
   *
   * **This run's scored columns and no other block's.** A second sort-seq block on the same
   * project exports columns whose specs are indistinguishable from this one's by anything
   * discovery matches on, so the columns are supplied from this block's own output and the
   * whole `pl7.app/facsBin/` namespace is excluded from the pool query — see the two comments
   * in the body.
   *
   * Anchored on `gateRankMean` rather than `binScore`, because the anchor decides whether the
   * table renders at all and `binScore` is legitimately absent at a condition whose parent
   * went unscored. Anchored on that, a run that scored perfectly well everywhere else would
   * show an empty table.
   *
   * **The anchor is one concrete column's spec, taken from this block's own output.** Two
   * things rule out the obvious alternative of a selector naming `pl7.app/facsBin/gateRankMean`:
   * a run over N conditions emits N such columns, so the selector is ambiguous and
   * `createPlDataTableV3` refuses it outright; and the result pool cannot tell this instance's
   * columns from a second instance of this block on the same project. Reading the frame the
   * workflow hands back sidesteps both — those columns are ours by construction.
   *
   * Which condition's `gateRankMean` anchors is deliberately unfixed by the spec: conditions
   * carry no order, so "the first" names nothing, and the choice cannot change what the table
   * shows, which carries every condition's columns either way. Sorting by the condition domain
   * value only makes the pick stable across renders.
   */
  .outputWithStatus("resultsTable", (ctx) => {
    const own = ctx.outputs?.resolve("scoresPf")?.getPColumns();
    if (!own) return undefined;

    const anchor = own
      .filter((column) => column.spec.name === FacsBin.GateRankMean)
      .sort((a, b) =>
        (a.spec.domain?.[FacsBin.ConditionDomain] ?? "").localeCompare(
          b.spec.domain?.[FacsBin.ConditionDomain] ?? "",
        ),
      )[0];
    if (!anchor) return undefined;

    // This block's own scored columns, every one of them, taken from the workflow output.
    // They are the table's primary columns, so they are always shown and never compete with
    // a namesake from the pool.
    const primaryColumns = own.map((column) => DataColumn.fromColumn(column));

    // Everything else the variant axis reaches — the variant label, the mutation list, the
    // per-variant columns of the upstream profiler.
    //
    // **Every `pl7.app/facsBin/` column is excluded here, this block's own included.** The
    // pool carries the exports of *every* sort-seq block on the project, and their specs are
    // identical in every part the discovery matches on: same name, same variant axis. Only
    // the `pl7.app/block` domain key tells them apart, and a selector can require a domain
    // value but cannot refuse one — so there is no selector that admits this instance's
    // columns and refuses a sibling's. Dropping the whole namespace and supplying this
    // block's own columns above is what makes the table show one run.
    //
    // Excluding them also removes the duplicate this block creates for itself: its scores
    // reach the pool through `exports.pf` as well, and discovery would find that copy
    // alongside the output columns.
    const { primary, secondary } = discoverTableColumnSnaphots(ctx, {
      anchors: { main: anchor.spec },
      // Strict axis equality, so only columns keyed on the variant axis and nothing else get
      // in. "related" would let both sides' axes float and reach every column the variant
      // axis participates in — the per-position state matrix, this block's own per-gate
      // distribution — giving a row per variant per position per gate.
      selector: {
        mode: "exact",
        exclude: [{ name: [{ type: "regex", value: "^pl7\\.app/facsBin/.*$" }] }],
      },
    });

    return createPlDataTableV3(ctx, {
      primaryColumns,
      columns: [...primary, ...secondary],
      tableState: ctx.data.resultsTableState,
      displayOptions: {
        /**
         * First match wins, and an **unmatched column keeps its own annotation** — which
         * upstream sets to `default` on nearly everything, so without the catch-all last the
         * table opens with every reachable column on screen.
         *
         * `optional` rather than `hidden` for the remainder: they stay one click away in the
         * column picker. Hiding a column a user wants, with no way to bring it back, is the
         * worse failure.
         *
         * The two score rules are the block's own columns, which are primary and therefore
         * always on screen; the rules state their visibility for the column picker's sake.
         */
        visibility: [
          { match: { name: exact(FacsBin.GateRankMean) }, visibility: "default" },
          { match: { name: exact(FacsBin.BinScore) }, visibility: "default" },
          { match: { name: exact(PColumnName.VariantLabel) }, visibility: "default" },
          { match: { name: exact(PColumnName.Mutations) }, visibility: "default" },
          { match: { name: ".*" }, visibility: "optional" },
        ],
      },
    });
  })

  /**
   * The conditions a distribution page can be opened for, sorted.
   *
   * Taken from the columns rather than the manifest, because the columns are what the frame can
   * actually render. Lets a page tell a route naming a dropped condition from one whose data has
   * simply not arrived yet.
   */
  .output("distributionConditions", (ctx) => {
    const columns = ctx.outputs?.resolve("distributionPf")?.getPColumns();
    if (!columns) return undefined;
    return distributionConditionsOf(columns);
  })

  /**
   * The graph frame, held out of exports and the pool.
   *
   * **One frame covering every condition, not one per condition.** A condition is part of a
   * column's identity here, not a dimension of it, so each page binds `y` to its own condition's
   * column out of this shared frame. The frame therefore never swaps, which is what keeps each
   * page's saved chart state pointing at a column that still exists.
   *
   * **`createPFrameForGraphs` rather than a bare `ctx.createPFrame`**: the variant axis's labels
   * live in a separate pool column that only this helper pulls in. A frame of just this block's
   * columns draws variants as raw keys. The cost is extra entries in the chart's source
   * dropdowns, which is the better of the two.
   */
  .outputWithStatus("distributionPf", (ctx) => {
    const columns = ctx.outputs?.resolve("distributionPf")?.getPColumns();
    if (!columns) return undefined;
    return createPFrameForGraphs(ctx, columns);
  })

  /**
   * The same columns as id+spec pairs, so a page can bind to real specs instead of guessing
   * names. Every condition is here; a page picks its own by the condition domain key.
   */
  .output("distributionPfCols", (ctx) => {
    const columns = ctx.outputs?.resolve("distributionPf")?.getPColumns();
    if (!columns) return undefined;
    return columns.map((column) => ({ id: column.id, spec: column.spec }));
  })

  /**
   * The not-ready-safe accessor is required here, not a preference: plain `getDataAsJson` throws
   * mid-run against a remote backend, and this is read while a run is in progress.
   */
  .output("manifest", (ctx) =>
    ctx.outputs?.resolve("manifest")?.getDataAsJsonOrUndefined<RunManifest>(),
  )

  .output("logHandle", (ctx) => ctx.outputs?.resolve("logHandle")?.getLogHandle())
  .output("isRunning", (ctx) => ctx.outputs?.getIsReadyOrError() === false)

  /**
   * Why the block is not runnable, in the user's words, or an empty list. Naming the missing
   * input is the block's own job — the platform reports only that the settings are incomplete.
   */
  .output("settingsIssues", (ctx) => settingsIssues(ctx.data))

  /** Exposed so the UI can show it as the subtitle field's placeholder. */
  .output("defaultBlockLabel", (ctx) => deriveBlockLabel(ctx.data))

  /**
   * The block's own name, and nothing else. What this *instance* is configured for belongs
   * in the subtitle — a title that changes with configuration makes the block list read as
   * several different blocks, and every sibling keeps the title constant for that reason.
   */
  .title(() => "Sort-Seq Analysis")

  /** The user's override wins; otherwise the label derived from the gate selection. */
  .subtitle((ctx) => ctx.data.customBlockLabel || deriveBlockLabel(ctx.data))

  /**
   * The scores table, then one distribution page per condition.
   *
   * The condition rides in the query string and every such link resolves to the single
   * `/distribution` route, routes being keyed on the pathname alone.
   *
   * Encoding matters beyond the obvious `&`, `=` and `#`: `encodeURIComponent` escapes `+` to
   * `%2B`, and the reading side would otherwise decode a bare `+` as a space — `CD4+` being an
   * entirely ordinary condition value.
   *
   * Built from the columns a run produced, so a page appears only where there is something to
   * draw on it, and none do before the first run.
   */
  .sections((ctx) => {
    const columns = ctx.outputs?.resolve("distributionPf")?.getPColumns();

    // Each entry must stay an `as const` literal with no annotation on the array: the href's
    // template literal type is what the route's query type is derived from, so widening it
    // stops `queryParams.condition` type-checking in the page.
    return [
      // Must stay identical to the page's own title.
      { type: "link" as const, href: "/" as const, label: "Variant Scores" },
      ...(columns ? distributionConditionsOf(columns) : []).map((condition) => ({
        type: "link" as const,
        href: `/distribution?condition=${encodeURIComponent(condition)}` as const,
        // Deliberately no manifest entry: the count belongs on the plot, not repeated down a
        // list of links where it would shift under the reader mid-run.
        label: distributionPlotTitle(condition),
      })),
    ];
  })

  .done();

/**
 * The block subtitle when the user has not overridden it.
 *
 * The gate selection is what distinguishes two instances of this block on one project —
 * same dataset, different gate column or different gate order — so that is what the label
 * names. It reads along the binding axis: weakest gate first, strongest last.
 *
 * A pure function of `data`, which is what keeps the subtitle out of hairpin territory.
 */
export function deriveBlockLabel(data: BlockData): string {
  // The declared order, which the drag list keeps populated from the moment a gate column is
  // picked — so the label appears on the pick rather than waiting for a ranking step.
  const ordered = data.gateOrder;
  if (!data.gateColumnLabel || ordered.length === 0) return "Select gates";

  // Every gate, in order — not just the ends. The ordering is what distinguishes two
  // instances of this block on one dataset, and first-to-last hides a reordering of the
  // middle, which is precisely the change that silently moves every score.
  return `${data.gateColumnLabel}: ${ordered.join("-")}`;
}

/**
 * The metadata options minus whatever the other two roles already hold.
 *
 * The pickers narrow; they do not re-check distinctness. That refusal stays the single check
 * in `args` — hiding a column another role holds keeps the user away from a refusal whose
 * cause is not visible on the control. A role never hides its own current pick, or the
 * control would render with no matching option and look empty.
 */
function narrowTo(
  ctx: {
    data: BlockData;
    resultPool: unknown;
    outputs?: unknown;
  } & { data: BlockData },
  role: "conditionColumnRef" | "gateColumnRef" | "sortFractionColumnRef",
): { label: string; value: SUniversalPColumnId }[] | undefined {
  const all = metadataColumnsOf(ctx);
  if (!all) return undefined;

  const roles = ["conditionColumnRef", "gateColumnRef", "sortFractionColumnRef"] as const;
  const taken = new Set(
    roles
      .filter((other) => other !== role)
      .map((other) => ctx.data[other])
      .filter((ref): ref is SUniversalPColumnId => ref !== undefined),
  );

  return all
    .filter((column) => !taken.has(column.value))
    .map((column) => ({ label: column.label, value: column.value }));
}

/** The same query `metadataColumns` runs; the runtime memoizes it across both. */
function metadataColumnsOf(ctx: {
  data: BlockData;
  resultPool: unknown;
}): { value: SUniversalPColumnId; label: string }[] | undefined {
  const anchor = ctx.data.abundanceRef;
  if (!anchor) return undefined;

  const pool = ctx.resultPool as {
    resolveAnchorCtx: (
      a: Record<string, unknown>,
    ) => { deriveS: (spec: unknown) => SUniversalPColumnId } | undefined;
    getAnchoredPColumns: (
      a: Record<string, unknown>,
      s: unknown[],
    ) => { id: string; spec: { name: string; annotations?: Record<string, string> } }[] | undefined;
  };

  const anchorCtx = pool.resolveAnchorCtx({ main: anchor });
  if (!anchorCtx) return undefined;
  const columns = pool.getAnchoredPColumns({ main: anchor }, [metadataSelector]);
  if (!columns) return undefined;

  return columns.map((column) => ({
    value: anchorCtx.deriveS(column.spec),
    label: column.spec.annotations?.[Annotation.Label] ?? column.spec.name,
  }));
}

export type BlockOutputs = InferOutputsType<typeof platforma>;
