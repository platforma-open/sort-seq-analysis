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

const COLUMN_FIELDS = ["conditionColumnRef", "gateColumnRef", "sortFractionColumnRef"] as const;
const VALUE_FIELDS = ["gateOrder", "gateValues", "conditionValues"] as const;

describe.each(COLUMN_FIELDS)("%s", (field) => {
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
    expect(() => parse({ [field]: id })).toThrow(`'${field}' must be a metadata column`);
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

describe("the params envelope", () => {
  it("accepts an empty object — every field is optional", () => {
    expect(parse({})).toEqual({});
  });

  it("accepts a fully configured metadata reading", () => {
    const gates = createColumnValueIds({ column: GATE, values: ["NEG", "LOW", "HIGH", "INPUT"] });
    const params = {
      conditionColumnRef: CONDITION,
      gateColumnRef: GATE,
      sortFractionColumnRef: createGlobalPObjectId("samples", "metadata.fraction"),
      gateOrder: gates.slice(0, 3),
      gateValues: gates,
      gateColumnLabel: "Gate",
      conditionValues: createColumnValueIds({ column: CONDITION, values: ["CD4+", "CD8+"] }),
    };
    expect(parse(params)).toEqual(params);
  });

  it("drops keys the contract does not name", () => {
    expect(parse({ gateColumnLabel: "Gate", readFloor: 10 })).toEqual({ gateColumnLabel: "Gate" });
  });

  it("rejects a gateColumnLabel that is not a string", () => {
    expect(() => parse({ gateColumnLabel: 1 })).toThrow("'gateColumnLabel' must be a string.");
  });

  it("rejects params that are not an object", () => {
    expect(() => parse(null)).toThrow();
    expect(() => parse([GATE])).toThrow();
  });
});
