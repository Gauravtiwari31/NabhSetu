import { useQuery } from "@tanstack/react-query";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api } from "../api";
import { EmptyState } from "../components/EmptyState";
import { formatIndex, formatPercent } from "../format";

export function OverviewPage() {
  const series = useQuery({ queryKey: ["index", "daily"], queryFn: () => api.index("daily") });
  const coverage = useQuery({ queryKey: ["coverage"], queryFn: api.coverage });
  const items = (series.data as { items?: Array<Record<string, string>> } | undefined)?.items ?? [];
  const chart = items.map((item) => ({
    period: item.period,
    value: Number(item.value),
    ci_low: item.ci_low ? Number(item.ci_low) : undefined,
    ci_high: item.ci_high ? Number(item.ci_high) : undefined,
    coverage: item.coverage_pct ? Number(item.coverage_pct) : undefined,
  }));
  const latest = items.at(-1);
  const diag = (coverage.data as { diagnostics?: Record<string, unknown>; coverage_pct?: string } | undefined) ?? {};
  return (
    <section>
      <header className="page-head">
        <div>
          <h2>Nabhsetu-T daily index</h2>
          <p className="muted">Traveller-paid Jevons elementary index with Young aggregation. First published period is 100.</p>
        </div>
      </header>
      <div className="grid">
        <div className="card">
          <div className="muted">Latest level</div>
          <div className="metric">{formatIndex(latest?.value)}</div>
        </div>
        <div className="card">
          <div className="muted">Basket coverage</div>
          <div className="metric">{formatPercent(latest?.coverage_pct ?? diag.coverage_pct)}</div>
        </div>
        <div className="card">
          <div className="muted">90% interval</div>
          <div className="metric">
            {latest?.ci_low && latest?.ci_high
              ? `${formatIndex(latest.ci_low)} – ${formatIndex(latest.ci_high)}`
              : "—"}
          </div>
        </div>
      </div>
      <div className="card" style={{ height: 380 }}>
        {chart.length === 0 ? (
          <EmptyState
            title="No published series yet"
            body="Collect fares from a permitted source, then publish from the collection console. Live mode never fills gaps with mock fares."
          />
        ) : (
          <ResponsiveContainer>
            <LineChart data={chart}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="period" />
              <YAxis domain={["auto", "auto"]} />
              <Tooltip formatter={(value) => formatIndex(Number(value))} />
              <Legend />
              <Line type="monotone" dataKey="value" name="Nabhsetu-T" stroke="#0b2545" strokeWidth={2} dot={false} />
              <Line type="monotone" dataKey="ci_low" name="CI low" stroke="#7aa2d4" dot={false} />
              <Line type="monotone" dataKey="ci_high" name="CI high" stroke="#7aa2d4" dot={false} />
            </LineChart>
          </ResponsiveContainer>
        )}
      </div>
    </section>
  );
}
