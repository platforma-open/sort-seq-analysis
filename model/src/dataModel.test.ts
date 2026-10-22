import {
  createColumnValueId,
  createGlobalPObjectId,
  createPlDataTableStateV2,
} from "@platforma-sdk/model";
import { describe, expect, test } from "vitest";
import { blockDataModel } from "./dataModel";

const datasetRef = { __isRef: true, blockId: "mixcr", name: "abundance" };
const dataset = createGlobalPObjectId("mixcr", "abundance");

/** An id anchored against the dataset, the way the condition, gate and fraction were stored. */
const anchored = (name: string) =>
  JSON.stringify({ axes: [{ anchor: "main", idx: 0 }], name, domain: { column: name } });

const tableState = createPlDataTableStateV2();
const graphState = { title: "Variant Frequency — A", template: "line", currentTab: null };

const storedAtV2 = {
  abundanceRef: datasetRef,
  conditionColumnRef: anchored("condition"),
  gateColumnRef: anchored("gate"),
  sortFractionColumnRef: anchored("fraction"),
  gateOrder: ["NEG", "LOW", "HIGH"],
  excludedConditions: ["B"],
  readFloor: 10,
  gatesOrdered: false,
  inputGate: "INPUT",
  baseline: "wild-type",
  gateValues: ["HIGH", "INPUT", "LOW", "NEG"],
  gateColumnLabel: "Gate",
  conditionValues: ["A", "B"],
  customBlockLabel: "My sort",
  resultsTableState: tableState,
  ntResultsTableState: tableState,
  distributionGraphStates: { A: graphState },
};

describe("Ver_2026_10_21 migration", () => {
  const { data } = blockDataModel.migrate({ version: "Ver_2026_09_21", data: storedAtV2 });

  test("the dataset ref becomes the result-pool id of the same output", () => {
    expect(data.abundanceRef).toBe(dataset);
  });

  test("the anchored condition, gate and sort-fraction columns are reset", () => {
    expect(data.conditionColumnRef).toBeUndefined();
    expect(data.gateColumnRef).toBeUndefined();
    expect(data.sortFractionColumnRef).toBeUndefined();
  });

  test("the plain gate order, excluded conditions and input gate are reset", () => {
    expect(data.gateOrder).toEqual([]);
    expect(data.excludedConditions).toEqual([]);
    expect(data.inputGate).toBeUndefined();
  });

  test("the value snapshots and the gate column label go with their columns", () => {
    expect(data.gateValues).toEqual([]);
    expect(data.conditionValues).toEqual([]);
    expect(data.gateColumnLabel).toBeUndefined();
  });

  test("settings that are not picks are kept", () => {
    expect(data).toMatchObject({
      readFloor: 10,
      gatesOrdered: false,
      baseline: "wild-type",
      customBlockLabel: "My sort",
      resultsTableState: tableState,
      ntResultsTableState: tableState,
      distributionGraphStates: { A: graphState },
    });
  });

  test("picks already stored as column ids and column value ids are kept", () => {
    const gate = createGlobalPObjectId("samples", "metadata.gate");
    const condition = createGlobalPObjectId("samples", "metadata.condition");
    const fraction = createGlobalPObjectId("samples", "metadata.fraction");
    const gateValue = (value: string) => createColumnValueId({ column: gate, value });
    const conditionValue = (value: string) => createColumnValueId({ column: condition, value });
    const stored = {
      ...storedAtV2,
      conditionColumnRef: condition,
      gateColumnRef: gate,
      sortFractionColumnRef: fraction,
      gateOrder: [gateValue("NEG"), gateValue("HIGH")],
      excludedConditions: [conditionValue("B")],
      inputGate: gateValue("INPUT"),
      gateValues: [gateValue("HIGH"), gateValue("INPUT"), gateValue("NEG")],
      conditionValues: [conditionValue("A"), conditionValue("B")],
    };
    expect(blockDataModel.migrate({ version: "Ver_2026_09_21", data: stored }).data).toEqual({
      ...stored,
      abundanceRef: dataset,
    });
  });

  test("migrating its own output again changes nothing", () => {
    // The stored type of the dataset is a ref, so the output's dataset goes back in as one.
    const again = blockDataModel.migrate({
      version: "Ver_2026_09_21",
      data: { ...data, abundanceRef: datasetRef },
    }).data;
    expect(again).toEqual(data);
  });

  test("a block without a dataset stays without one", () => {
    const { abundanceRef: _, ...withoutDataset } = storedAtV2;
    const migrated = blockDataModel.migrate({
      version: "Ver_2026_09_21",
      data: withoutDataset,
    }).data;
    expect(migrated.abundanceRef).toBeUndefined();
  });

  test("a Ver_2026_08_07 block reaches the current shape through every step", () => {
    const { ntResultsTableState: _, ...storedAtV1 } = storedAtV2;
    const migrated = blockDataModel.migrate({ version: "Ver_2026_08_07", data: storedAtV1 }).data;
    expect(migrated.abundanceRef).toBe(dataset);
    expect(migrated.gateOrder).toEqual([]);
    expect(migrated.ntResultsTableState).toEqual(createPlDataTableStateV2());
  });
});
