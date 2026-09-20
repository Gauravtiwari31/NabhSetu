import { expect, test } from "vitest";
import { collapseHeatmapCells } from "./heatmap";

test("heatmap prefers a live carrier cell over a suppressed one", () => {
  const collapsed = collapseHeatmapCells([
    { route: "DEL-BOM", apw_days: 7, adjusted: "100.0", suppressed: false, n_matched: 55 },
    { route: "DEL-BOM", apw_days: 7, adjusted: "100.0", suppressed: true, n_matched: 2 },
  ]);
  expect(collapsed).toHaveLength(1);
  expect(collapsed[0].suppressed).toBe(false);
  expect(collapsed[0].n_matched).toBe(55);
});
