import { createGlobalPObjectId } from "@platforma-sdk/model";
import { describe, expect, test, vi } from "vitest";
import { getMetadataValueSources } from "./metadata";

vi.mock("@platforma-sdk/model", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@platforma-sdk/model")>()),
  createColumnValueOptions: ({ valueColumn }: { valueColumn: string }) => ({
    type: "absent",
    valueColumn,
  }),
}));

const condition = createGlobalPObjectId("samples", "pf.metadata.condition");
const gate = createGlobalPObjectId("samples", "pf.metadata.gate");
const fraction = createGlobalPObjectId("samples", "pf.metadata.fraction");

describe("metadata value sources", () => {
  test("without a dataset the picked condition and gate columns are still read", () => {
    const sources = getMetadataValueSources(undefined, {
      conditionColumnRef: condition,
      gateColumnRef: gate,
      sortFractionColumnRef: fraction,
    });
    expect(sources.map((source) => source.valueColumn)).toEqual([condition, gate]);
  });

  test("without a dataset or picks nothing is read", () => {
    expect(getMetadataValueSources(undefined, {})).toEqual([]);
  });
});
