import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api";
import { EmptyState } from "../components/EmptyState";
import { StatusChip } from "../components/StatusChip";

type SourceItem = {
  id: string;
  name: string;
  enabled: boolean;
  source_type: string;
  preferred_adapter: string | null;
  temporarily_blocked: boolean;
  automation_allowed: boolean;
  terms_review_status: string;
  robots_status: string;
  restriction_reason: string | null;
};

function termsKind(status: string): "ok" | "warn" | "bad" | "neutral" {
  if (status === "approved") return "ok";
  if (status === "denied") return "bad";
  if (status === "review_required") return "warn";
  return "neutral";
}

export function SourcesPage() {
  const sources = useQuery({ queryKey: ["sources"], queryFn: api.sources });
  const items = ((sources.data as { items?: SourceItem[] } | undefined)?.items ?? []) as SourceItem[];
  const [selected, setSelected] = useState<string | null>(null);
  const active = selected ?? items[0]?.id ?? null;
  const details = useQuery({
    queryKey: ["source-status", active],
    queryFn: () => api.sourceStatus(active as string),
    enabled: Boolean(active),
  });
  const detail = details.data as
    | {
        name?: string;
        restriction_reason?: string | null;
        robots_status?: string;
        terms_review_status?: string;
        last_successful_adapter?: string | null;
        circuit?: Record<string, { state: string; consecutive_failures: number }>;
      }
    | undefined;
  return (
    <section>
      <header className="page-head">
        <div>
          <h2>Source and circuit health</h2>
          <p className="muted">Denied and review-required OTAs stay visible. They are never scraped and never replaced with mock fares.</p>
        </div>
      </header>
      <div className="card">
        {items.length === 0 ? (
          <EmptyState title="No sources seeded" body="Start the API so the catalog can seed airline and OTA profiles." />
        ) : (
          <div className="table-container">
            <table className="clickable-rows">
            <thead>
              <tr>
                <th>Source</th>
                <th>Type</th>
                <th>Terms</th>
                <th>Robots</th>
                <th>Automation</th>
                <th>Blocked</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr
                  key={item.id}
                  className={item.id === active ? "row-active" : undefined}
                  onClick={() => setSelected(item.id)}
                >
                  <td>{item.name}</td>
                  <td>{item.source_type}</td>
                  <td>
                    <StatusChip kind={termsKind(item.terms_review_status)}>{item.terms_review_status}</StatusChip>
                  </td>
                  <td>{item.robots_status}</td>
                  <td>{item.automation_allowed && item.enabled ? "allowed" : "stopped"}</td>
                  <td>{item.temporarily_blocked ? item.restriction_reason ?? "yes" : "no"}</td>
                </tr>
              ))}
            </tbody>
            </table>
          </div>
        )}
      </div>
      {detail ? (
        <div className="card">
          <h3>{detail.name}</h3>
          <p className="muted">{detail.restriction_reason ?? "No active restriction."}</p>
          <p>
            Last successful adapter: <strong>{detail.last_successful_adapter ?? "—"}</strong>
          </p>
          <ul className="circuit-list">
            {Object.entries(detail.circuit ?? {}).map(([adapter, stats]) => (
              <li key={adapter}>
                <code>{adapter}</code> {stats.state}
                {stats.consecutive_failures ? ` · ${stats.consecutive_failures} failures` : ""}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}
