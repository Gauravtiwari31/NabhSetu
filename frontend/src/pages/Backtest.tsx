import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { StatusChip } from "../components/StatusChip";
import { formatIndex } from "../format";

function statusKind(status?: string): "ok" | "warn" | "bad" | "neutral" {
  if (status === "reportable") return "ok";
  if (status === "not_reportable") return "warn";
  if (status === "unavailable") return "neutral";
  return "neutral";
}

export function BacktestPage() {
  const backtest = useQuery({ queryKey: ["backtest"], queryFn: api.backtest });
  const data = backtest.data as
    | {
        status?: string;
        comparator?: string;
        overlap_months?: number;
        correlation?: string | null;
        mape?: string | null;
        notes?: string | null;
      }
    | undefined;
  return (
    <section>
      <header className="page-head">
        <div>
          <h2>Official-file back-test</h2>
          <p className="muted">
            DGCA and CPI comparators are imported from checksummed public files only. This page stays unavailable until
            those files are present — it will not invent official numbers.
          </p>
        </div>
      </header>
      <div className="card">
        <p>
          Comparator: <strong>{data?.comparator ?? "—"}</strong>{" "}
          <StatusChip kind={statusKind(data?.status)}>{data?.status ?? "unavailable"}</StatusChip>
        </p>
        <div className="grid">
          <div>
            <div className="muted">Overlap months</div>
            <div className="metric">{data?.overlap_months ?? 0}</div>
          </div>
          <div>
            <div className="muted">Correlation</div>
            <div className="metric">{data?.correlation ? formatIndex(data.correlation, 3) : "not reported"}</div>
          </div>
          <div>
            <div className="muted">MAPE</div>
            <div className="metric">{data?.mape ? formatPercentish(data.mape) : "not reported"}</div>
          </div>
        </div>
        <p className="muted">{data?.notes}</p>
      </div>
    </section>
  );
}

function formatPercentish(value: string): string {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return value;
  return numeric <= 1 ? `${(numeric * 100).toFixed(1)}%` : `${numeric.toFixed(1)}%`;
}
