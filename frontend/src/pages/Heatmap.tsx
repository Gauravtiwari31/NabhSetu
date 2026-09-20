import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { EmptyState } from "../components/EmptyState";
import { formatIndex } from "../format";
import { collapseHeatmapCells } from "../heatmap";

export function HeatmapPage() {
  const cells = useQuery({ queryKey: ["cells"], queryFn: api.cells });
  const raw = ((cells.data as { items?: Array<Record<string, string | number | boolean>> } | undefined)?.items ??
    []) as Array<{
    route: string;
    apw_days: number;
    adjusted: string | null;
    suppressed: boolean;
    n_matched?: number;
  }>;
  const items = collapseHeatmapCells(raw);
  const routes = [...new Set(items.map((item) => item.route))];
  const windows = [...new Set(items.map((item) => item.apw_days))].sort((a, b) => a - b);
  const lookup = new Map(items.map((item) => [`${item.route}:${item.apw_days}`, item]));
  return (
    <section>
      <header className="page-head">
        <div>
          <h2>Route × lead-window heatmap</h2>
          <p className="muted">Suppressed cells stay blank. Missing basket routes are coverage gaps, not imputed fares.</p>
        </div>
      </header>
      {routes.length === 0 ? (
        <div className="card">
          <EmptyState
            title="No index cells published"
            body="Publish after a permitted collection. A single route will show here with the rest of the basket marked as uncovered."
          />
        </div>
      ) : (
        <div
          className="card heatmap"
          style={{ gridTemplateColumns: `90px repeat(${windows.length}, 1fr)` }}
        >
          <div />
          {windows.map((window) => (
            <strong key={window}>T+{window}</strong>
          ))}
          {routes.map((route) => (
            <div key={route} style={{ display: "contents" }}>
              <strong>{route}</strong>
              {windows.map((window) => {
                const cell = lookup.get(`${route}:${window}`);
                const value = cell?.adjusted ? Number(cell.adjusted) : null;
                const intensity = value == null ? 0 : Math.min(1, Math.abs(value - 100) / 20);
                return (
                  <div
                    key={`${route}-${window}`}
                    className="heat-cell"
                    style={{
                      background: `rgba(11, 37, 69, ${0.12 + intensity * 0.55})`,
                      color: intensity > 0.5 ? "white" : "#0b2545",
                    }}
                  >
                    {cell?.suppressed ? "suppressed" : value == null ? "—" : formatIndex(value, 1)}
                  </div>
                );
              })}
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
