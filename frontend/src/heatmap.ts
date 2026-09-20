export type HeatCell = {
  route: string;
  apw_days: number;
  adjusted: string | null;
  suppressed: boolean;
  n_matched?: number;
};

export function collapseHeatmapCells(items: HeatCell[]): HeatCell[] {
  const map = new Map<string, HeatCell>();
  for (const item of items) {
    const key = `${item.route}:${item.apw_days}`;
    const current = map.get(key);
    if (!current) {
      map.set(key, item);
      continue;
    }
    if (current.suppressed && !item.suppressed) {
      map.set(key, item);
      continue;
    }
    if (!current.suppressed && item.suppressed) continue;
    if (Number(item.n_matched ?? 0) > Number(current.n_matched ?? 0)) {
      map.set(key, item);
    }
  }
  return [...map.values()];
}
