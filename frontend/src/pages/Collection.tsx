import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { api } from "../api";
import { EmptyState } from "../components/EmptyState";
import { StatusChip } from "../components/StatusChip";
import { formatWhen } from "../format";

const ROUTES = ["DEL-BOM", "BOM-DEL", "DEL-BLR", "BOM-BLR", "DEL-HYD"];
const LEADS = [1, 7, 15, 30, 45];

type SourceItem = {
  id: string;
  name: string;
  enabled: boolean;
  automation_allowed: boolean;
  temporarily_blocked: boolean;
  source_type: string;
};

function resultKind(status: string | null): "ok" | "warn" | "bad" | "neutral" {
  if (status === "success") return "ok";
  if (status === "policy_denied" || status === "blocked" || status === "captcha_blocked") return "bad";
  if (status === "no_results" || status === "rate_limited") return "warn";
  return "neutral";
}

export function CollectionPage() {
  const client = useQueryClient();
  const status = useQuery({ queryKey: ["status"], queryFn: api.status });
  const sources = useQuery({ queryKey: ["sources"], queryFn: api.sources });
  const jobs = useQuery({ queryKey: ["jobs"], queryFn: api.jobs });
  const live = status.data?.data_mode === "live";
  const catalog = ((sources.data as { items?: SourceItem[] } | undefined)?.items ?? []) as SourceItem[];
  const collectable = catalog.filter(
    (item) => item.enabled && item.automation_allowed && !item.temporarily_blocked && (live ? item.source_type !== "mock" : true),
  );
  const defaultSource = useMemo(() => {
    return collectable.find((item) => item.name === "EaseMyTrip")?.id ?? collectable[0]?.id ?? "";
  }, [collectable]);
  const [route, setRoute] = useState("DEL-BOM");
  const [lead, setLead] = useState(7);
  const [sourceId, setSourceId] = useState("");
  const selectedSource = sourceId || defaultSource;
  const collect = useMutation({
    mutationFn: () => {
      const [origin, destination] = route.split("-");
      return api.collect({
        origin,
        destination,
        lead_time_days: lead,
        source_id: selectedSource || undefined,
      });
    },
    onSuccess: () => client.invalidateQueries(),
  });
  const publish = useMutation({
    mutationFn: api.publish,
    onSuccess: () => client.invalidateQueries(),
  });
  const items = ((jobs.data as { items?: Array<Record<string, unknown>> } | undefined)?.items ?? []) as Array<{
    id: string;
    status: string;
    result_status: string | null;
    is_simulated: boolean;
    created_at: string;
    collector: string | null;
    query: { origin?: string; destination?: string; lead_time_days?: number };
  }>;
  return (
    <section>
      <header className="page-head">
        <div>
          <h2>Collection console</h2>
          <p className="muted">
            {live
              ? "Live jobs use identified research traffic only. EaseMyTrip is the currently approved OTA. Denied sources cannot be selected."
              : "Mock mode uses fixture fares. Switch APIX_DATA_MODE=live before presenting measurements."}
          </p>
        </div>
      </header>
      <div className="card toolbar">
        <label>
          Route
          <select value={route} onChange={(event) => setRoute(event.target.value)}>
            {ROUTES.map((item) => (
              <option key={item}>{item}</option>
            ))}
          </select>
        </label>
        <label>
          Lead
          <select value={lead} onChange={(event) => setLead(Number(event.target.value))}>
            {LEADS.map((item) => (
              <option key={item} value={item}>
                T+{item}
              </option>
            ))}
          </select>
        </label>
        <label>
          Source
          <select value={selectedSource} onChange={(event) => setSourceId(event.target.value)}>
            {collectable.map((item) => (
              <option key={item.id} value={item.id}>
                {item.name}
              </option>
            ))}
          </select>
        </label>
        <button className="primary" disabled={collect.isPending || !selectedSource} onClick={() => collect.mutate()}>
          {collect.isPending ? "Collecting…" : "Collect"}
        </button>
        <button className="primary" disabled={publish.isPending} onClick={() => publish.mutate()}>
          {publish.isPending ? "Publishing…" : "Publish index"}
        </button>
      </div>
      {collect.error ? <p className="muted">{String(collect.error)}</p> : null}
      {publish.error ? <p className="muted">{String(publish.error)}</p> : null}
      <div className="card">
        {items.length === 0 ? (
          <EmptyState title="No jobs yet" body="Collect a permitted city-pair. Live collection can take up to a minute." />
        ) : (
          <table>
            <thead>
              <tr>
                <th>When</th>
                <th>Query</th>
                <th>Status</th>
                <th>Result</th>
                <th>Label</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr key={item.id}>
                  <td>{formatWhen(item.created_at)}</td>
                  <td>
                    {item.query.origin}-{item.query.destination} T+{item.query.lead_time_days}
                  </td>
                  <td>{item.status}</td>
                  <td>
                    <StatusChip kind={resultKind(item.result_status)}>{item.result_status ?? "queued"}</StatusChip>
                  </td>
                  <td>
                    {item.is_simulated ? (
                      <StatusChip kind="mock">simulated</StatusChip>
                    ) : (
                      <StatusChip kind="live">live</StatusChip>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </section>
  );
}
