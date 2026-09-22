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
import { ArrowRight } from "lucide-react";

export function OverviewPage() {
  const series = useQuery({ queryKey: ["index", "daily"], queryFn: () => api.index("daily") });
  const coverage = useQuery({ queryKey: ["coverage"], queryFn: api.coverage });
  const methodology = useQuery({ queryKey: ["methodology"], queryFn: api.methodology });
  const publishedBase = (methodology.data as { published_base?: string } | undefined)?.published_base;
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
      <div className="hero-section">
        <div className="hero-content">
          <h1>
            Real-time insights into <span>Indian airfares</span>
          </h1>
          <p>
            Nabhsetu is a premium daily index tracking the true cost of air travel. Powered by the MoSPI methodology for high-frequency pricing intelligence.
          </p>
          <div style={{ display: 'flex', gap: '1rem', flexWrap: 'wrap' }}>
            <button className="primary" onClick={() => window.scrollTo({ top: document.body.scrollHeight, behavior: 'smooth' })}>
              View Latest Data <ArrowRight size={16} style={{ verticalAlign: 'middle', marginLeft: '0.25rem' }} />
            </button>
          </div>
        </div>
      </div>

      <div className="grid fade-in" style={{ animationDelay: '0.1s' }}>
        <div className="card">
          <div className="muted">Latest Level</div>
          <div className="metric">{formatIndex(latest?.value)}</div>
          <div className="base-note">{publishedBase ?? "—"}</div>
        </div>
        <div className="card">
          <div className="muted">Basket Coverage</div>
          <div className="metric">{formatPercent(latest?.coverage_pct ?? diag.coverage_pct)}</div>
        </div>
        <div className="card">
          <div className="muted">90% Interval</div>
          <div className="metric">
            {latest?.ci_low && latest?.ci_high
              ? `${formatIndex(latest.ci_low)} – ${formatIndex(latest.ci_high)}`
              : "—"}
          </div>
        </div>
      </div>

      <div className="card fade-in" style={{ height: 420, animationDelay: '0.2s' }}>
        {chart.length === 0 ? (
          <EmptyState
            title="No published series yet"
            body="Collect fares from a permitted source, then publish from the collection console. Live mode never fills gaps with mock fares."
          />
        ) : (
          <ResponsiveContainer>
            <LineChart data={chart} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--nu-border)" />
              <XAxis dataKey="period" stroke="var(--nu-text-muted)" tick={{ fill: 'var(--nu-text-muted)' }} tickLine={false} axisLine={false} dy={10} />
              <YAxis domain={["auto", "auto"]} stroke="var(--nu-text-muted)" tick={{ fill: 'var(--nu-text-muted)' }} tickLine={false} axisLine={false} dx={-10} />
              <Tooltip formatter={(value) => formatIndex(Number(value))} />
              <Legend wrapperStyle={{ paddingTop: '20px' }} />
              <Line type="monotone" dataKey="value" name="APIx-T" stroke="var(--nu-accent)" strokeWidth={2.5} dot={false} activeDot={{ r: 5, fill: 'var(--nu-accent)', stroke: 'var(--nu-bg)', strokeWidth: 2 }} />
              <Line type="monotone" dataKey="ci_low" name="CI Low" stroke="var(--nu-text-muted)" strokeWidth={1} strokeDasharray="5 5" dot={false} />
              <Line type="monotone" dataKey="ci_high" name="CI High" stroke="var(--nu-text-muted)" strokeWidth={1} strokeDasharray="5 5" dot={false} />
            </LineChart>
          </ResponsiveContainer>
        )}
      </div>
    </section>
  );
}
