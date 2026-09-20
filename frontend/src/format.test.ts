import { expect, test } from "vitest";
import { formatINR, formatIndex, formatPercent } from "./format";

test("formats index levels to two decimals", () => {
  expect(formatIndex("100.00000000")).toBe("100.00");
  expect(formatIndex(null)).toBe("—");
});

test("formats coverage as a whole percent", () => {
  expect(formatPercent("24.0")).toBe("24%");
});

test("formats fares in Indian rupees", () => {
  expect(formatINR("4521.00")).toMatch(/₹/);
});
