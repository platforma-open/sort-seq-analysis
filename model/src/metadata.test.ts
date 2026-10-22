import { describe, expect, test } from "vitest";
import { pairSampleLabels } from "./metadata";

describe("pairSampleLabels", () => {
  test("pairs each sample id with the label of its row", () => {
    expect(pairSampleLabels(["s1", "s2"], ["Donor A", "Donor B"])).toEqual({
      s1: "Donor A",
      s2: "Donor B",
    });
  });

  test("keys and labels read as numbers become strings", () => {
    expect(pairSampleLabels([7], [42])).toEqual({ "7": "42" });
  });

  test("a row missing its id or its label is left out", () => {
    expect(pairSampleLabels(["s1", null, "s3", "s4"], ["A", "B", null])).toEqual({ s1: "A" });
  });
});
