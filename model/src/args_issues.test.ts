import {
  BlockStorageFacadeCallbacks,
  createBlockStorage,
  createColumnValueId,
  createGlobalPObjectId,
  createPlDataTableStateV2,
  stringifyJson,
} from "@platforma-sdk/model";
import { beforeAll, describe, expect, test } from "vitest";
import type { BlockData } from "./types";

const callbackRegistry: Record<string, (storageJson: string) => unknown> = {};

beforeAll(async () => {
  Object.assign(globalThis, { cfgRenderCtx: { callbackRegistry } });
  await import("./index");
});

const dataset = createGlobalPObjectId("mixcr", "abundance");
const condition = createGlobalPObjectId("samples", "metadata.condition");
const gate = createGlobalPObjectId("samples", "metadata.gate");
const fraction = createGlobalPObjectId("samples", "metadata.fraction");
const other = createGlobalPObjectId("samples", "metadata.other");

const gateValue = (value: string) => createColumnValueId({ column: gate, value });
const conditionValue = (value: string) => createColumnValueId({ column: condition, value });
const foreignInput = createColumnValueId({ column: other, value: "INPUT" });

const configured: BlockData = {
  abundanceRef: dataset,
  conditionColumnRef: condition,
  gateColumnRef: gate,
  sortFractionColumnRef: fraction,
  gateOrder: [gateValue("NEG"), gateValue("HIGH")],
  excludedConditions: [conditionValue("B")],
  inputGate: gateValue("INPUT"),
  gateValues: [gateValue("HIGH"), gateValue("INPUT"), gateValue("NEG")],
  gateColumnLabel: "Gate",
  conditionValues: [conditionValue("A"), conditionValue("B")],
  customBlockLabel: "",
  resultsTableState: createPlDataTableStateV2(),
  ntResultsTableState: createPlDataTableStateV2(),
  distributionGraphStates: {},
};

describe("args issues", () => {
  test("a configured block derives runnable args", () => {
    expect(deriveArgs(configured)).toMatchObject({
      value: {
        abundanceRef: dataset,
        conditionColumnRef: condition,
        gateColumnRef: gate,
        gateRanks: { [gateValue("NEG")]: 1, [gateValue("HIGH")]: 2 },
        excludedConditions: [conditionValue("B")],
        inputGate: gateValue("INPUT"),
      },
      issues: [],
    });
  });

  test("a fresh block gets one complaint per unmade pick, and its args still derive", () => {
    const fresh: BlockData = {
      ...configured,
      abundanceRef: undefined,
      conditionColumnRef: undefined,
      gateColumnRef: undefined,
      sortFractionColumnRef: undefined,
      gateOrder: [],
      excludedConditions: [],
      inputGate: undefined,
      gateValues: [],
      conditionValues: [],
    };
    const messages = [
      "Select an abundance dataset",
      "Select the condition column",
      "Select the gate column",
    ];
    expect(deriveArgs(fresh)).toEqual({
      error: messages.join("; "),
      args: expect.objectContaining({ gateRanks: {}, excludedConditions: [] }),
      issues: messages.map((message) => ({ severity: "error", message })),
    });
  });

  test.for([
    {
      why: "no dataset",
      data: { ...configured, abundanceRef: undefined },
      message: "Select an abundance dataset",
    },
    {
      why: "no condition column",
      data: { ...configured, conditionColumnRef: undefined, excludedConditions: [] },
      message: "Select the condition column",
    },
    {
      why: "no gate column",
      data: { ...configured, gateColumnRef: undefined },
      message: "Select the gate column",
    },
    {
      why: "one column in two roles",
      data: { ...configured, sortFractionColumnRef: gate },
      message: "The condition, gate and sort-fraction columns must be three different columns",
    },
    {
      why: "a gate column without values",
      data: { ...configured, gateValues: [], gateOrder: [], inputGate: undefined },
      message: "The gate column has no values to rank",
    },
    {
      why: "an empty gate order",
      data: { ...configured, gateOrder: [] },
      message: "Keep at least one gate in the order — every gate has been removed",
    },
    {
      why: "an ordered gate the gate column does not carry",
      data: { ...configured, gateOrder: [gateValue("NEG"), gateValue("MID")] },
      message: "Ordered value(s) the gate column does not carry: MID",
    },
    {
      why: "an input gate picked from another column",
      data: {
        ...configured,
        inputGate: foreignInput,
        gateValues: [...configured.gateValues, foreignInput],
      },
      message: "Gate value(s) picked from another column: INPUT",
    },
    {
      why: "every condition excluded",
      data: {
        ...configured,
        excludedConditions: [conditionValue("A"), conditionValue("B")],
      },
      message: "At least one condition must remain — every value is currently excluded",
    },
    {
      why: "an excluded condition picked from another column",
      data: {
        ...configured,
        excludedConditions: [createColumnValueId({ column: other, value: "B" })],
      },
      message: "Excluded condition(s) picked from another column: B",
    },
    {
      why: "a negative read-count floor",
      data: { ...configured, readFloor: -1 },
      message: "The read-count floor cannot be negative",
    },
    {
      why: "neither ordered gates nor an input",
      data: { ...configured, gatesOrdered: false, inputGate: undefined },
      message:
        "Order the gates, or name an unsorted input — with neither there is nothing to compute",
    },
    {
      why: "an input that is also a ranked gate",
      data: { ...configured, inputGate: gateValue("NEG") },
      message: "The input 'NEG' is also a ranked gate — remove it from the gate order",
    },
    {
      why: "an input the gate column does not carry",
      data: { ...configured, inputGate: gateValue("UNSORTED") },
      message: "The gate column does not carry the input value 'UNSORTED'",
    },
  ])("$why blocks Run with its message", ({ data, message }) => {
    expect(deriveArgs(data)).toMatchObject({
      error: message,
      issues: [{ severity: "error", message }],
    });
  });

  test("a gate order picked from another column names each foreign gate", () => {
    const foreign = createColumnValueId({ column: other, value: "NEG" });
    expect(deriveArgs({ ...configured, gateOrder: [foreign] })).toMatchObject({
      issues: [
        { severity: "error", message: "Ordered value(s) the gate column does not carry: NEG" },
        { severity: "error", message: "Gate value(s) picked from another column: NEG" },
      ],
    });
  });

  test("an unordered run with an input is runnable", () => {
    expect(deriveArgs({ ...configured, gatesOrdered: false })).toMatchObject({
      value: { gatesOrdered: false },
      issues: [],
    });
  });

  test("no exclusions and no sort-fraction column are runnable", () => {
    expect(
      deriveArgs({ ...configured, excludedConditions: [], sortFractionColumnRef: undefined }),
    ).toMatchObject({ issues: [] });
  });
});

// Internals

function deriveArgs(data: BlockData): unknown {
  const derive = callbackRegistry[BlockStorageFacadeCallbacks.ArgsDerive];
  if (derive === undefined) throw new Error("The args derive callback is not registered");
  return derive(stringifyJson(createBlockStorage(data)));
}
