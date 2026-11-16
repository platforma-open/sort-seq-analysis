import {
  createColumnValueId,
  createColumnValueIds,
  createGlobalPObjectId,
  createLocalPObjectId,
} from "@platforma-sdk/model";
import { describe, expect, it } from "vitest";
import { kind } from "./index";

const parse = (params: unknown) => kind.parseInitializationParams(params);

/** A metadata column of an upstream block, as the settings drawer stores it. */
const GATE = createGlobalPObjectId("samples", "metadata.gate");
const CONDITION = createGlobalPObjectId("samples", "metadata.condition");

/** The id the drawer stored before columns became result-pool ids: anchored to the dataset. */
const ANCHORED_ID =
  '{"axes":[{"anchor":"main","idx":0}],"domain":{"pl7.app/columnId":"Gate"},"name":"pl7.app/metadata","type":"String"}';
/** Other column id forms, which name no single output of an upstream block. */
const LOCAL_ID = createLocalPObjectId(["a", "b"], "pl7.app/metadata");
const FILTERED_ID = `{"__isFiltered":true,"axisFilters":[[0,"s1"]],"source":${JSON.stringify(GATE)}}`;

/** Each column field, with what its refusal calls the column. */
const COLUMN_FIELDS = [
  ["abundanceRef", "a dataset"],
  ["filterRef", "a subset column"],
  ["conditionColumnRef", "a metadata column"],
  ["gateColumnRef", "a metadata column"],
  ["sortFractionColumnRef", "a metadata column"],
] as const;
const VALUE_FIELDS = ["gateOrder", "gateValues", "conditionValues", "excludedConditions"] as const;

describe.each(COLUMN_FIELDS)("%s", (field, what) => {
  it("accepts the result-pool id of an upstream output", () => {
    expect(parse({ [field]: GATE })).toEqual({ [field]: GATE });
  });

  it.each([
    ["an anchored id", ANCHORED_ID],
    ["a local id", LOCAL_ID],
    ["a filtered id", FILTERED_ID],
    ["a ref object rather than its id", { __isRef: true, blockId: "samples", name: "metadata" }],
    ["a string that is not JSON", "Gate"],
    ["a number", 42],
    ["null", null],
  ])("rejects %s", (_label, id) => {
    expect(() => parse({ [field]: id })).toThrow(`'${field}' must be ${what}`);
  });
});

describe.each(VALUE_FIELDS)("%s", (field) => {
  it.each([
    ["an empty list", []],
    ["column value ids", createColumnValueIds({ column: GATE, values: ["NEG", "LOW", "HIGH"] })],
  ])("accepts %s", (_label, values) => {
    expect(parse({ [field]: values })).toEqual({ [field]: values });
  });

  it("rejects plain values, as stored before column value ids", () => {
    expect(() => parse({ [field]: ["NEG", "LOW"] })).toThrow(
      `'${field}[0]' must be a column value`,
    );
  });

  it("rejects a list with a hole", () => {
    const values = [createColumnValueId({ column: GATE, value: "NEG" }), null];
    expect(() => parse({ [field]: values })).toThrow(`'${field}[1]' must be a column value`);
  });

  it("rejects a bare value rather than a list", () => {
    expect(() => parse({ [field]: createColumnValueId({ column: GATE, value: "NEG" }) })).toThrow(
      `'${field}' must be a list.`,
    );
  });
});

describe("inputGate", () => {
  it("accepts a column value id", () => {
    const input = createColumnValueId({ column: GATE, value: "INPUT" });
    expect(parse({ inputGate: input })).toEqual({ inputGate: input });
  });

  it("rejects a plain value", () => {
    expect(() => parse({ inputGate: "INPUT" })).toThrow("'inputGate' must be a column value");
  });
});

describe("the run recipe's plain values", () => {
  it.each([
    ["readFloor", 10],
    ["readFloor", 0],
    ["gatesOrdered", false],
    ["baseline", "synonymous"],
    ["baselineSequence", "ACGT"],
  ])("accepts %s: %s", (field, value) => {
    expect(parse({ [field]: value })).toEqual({ [field]: value });
  });

  it.each([
    ["readFloor", "10", "'readFloor' must be a number."],
    ["readFloor", Number.NaN, "'readFloor' must be a number."],
    ["gatesOrdered", "no", "'gatesOrdered' must be true or false."],
    ["baseline", "parent", "'baseline' must be one of wild-type, synonymous, sequence."],
    ["baselineSequence", 1, "'baselineSequence' must be a string."],
  ])("rejects %s: %s", (field, value, message) => {
    expect(() => parse({ [field]: value })).toThrow(message);
  });
});

describe("the params envelope", () => {
  it("accepts an empty object — every field is optional", () => {
    expect(parse({})).toEqual({});
  });

  it("accepts a fully configured block", () => {
    const gates = createColumnValueIds({ column: GATE, values: ["NEG", "LOW", "HIGH", "INPUT"] });
    const conditions = createColumnValueIds({ column: CONDITION, values: ["CD4+", "CD8+"] });
    const params = {
      abundanceRef: createGlobalPObjectId("profiler", "variants.read-count"),
      filterRef: createGlobalPObjectId("labeling", "subset.leads"),
      conditionColumnRef: CONDITION,
      gateColumnRef: GATE,
      sortFractionColumnRef: createGlobalPObjectId("samples", "metadata.fraction"),
      gateOrder: gates.slice(0, 3),
      gateValues: gates,
      gateColumnLabel: "Gate",
      conditionValues: conditions,
      excludedConditions: conditions.slice(1),
      readFloor: 5,
      gatesOrdered: false,
      inputGate: gates[3],
      baseline: "synonymous",
      baselineSequence: undefined,
    };
    expect(parse(params)).toEqual(params);
  });

  it("drops keys the contract does not name", () => {
    expect(parse({ gateColumnLabel: "Gate", customBlockLabel: "Mine" })).toEqual({
      gateColumnLabel: "Gate",
    });
  });

  it("rejects a gateColumnLabel that is not a string", () => {
    expect(() => parse({ gateColumnLabel: 1 })).toThrow("'gateColumnLabel' must be a string.");
  });

  it("rejects params that are not an object", () => {
    expect(() => parse(null)).toThrow();
    expect(() => parse([GATE])).toThrow();
  });
});
