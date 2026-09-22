import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { EmptyState } from "../components/EmptyState";
import { formatIndex } from "../format";

export function ElasticityPage() {
  const elasticity = useQuery({ queryKey: ["elasticity"], queryFn: api.elasticity });
  const items = ((elasticity.data as { items?: Array<Record<string, unknown>> } | undefined)?.items ?? []) as Array<{
    period: string;
    near_far_elasticity: string | null;
    pairs: Array<{ from_apw: number; to_apw: number; elasticity: string | null }>;
  }>;
  return (
    <section>
      <header className="page-head">
        <div>
          <h2>Lead-time elasticity</h2>
          <p className="muted">
            Log-log elasticity of APIx-T across official T+ windows. Negative values mean cheaper fares further from
            departure.
          </p>
        </div>
      </header>
      <div className="card">
        {items.length === 0 ? (
          <EmptyState title="No elasticity yet" body="Elasticity appears after more than one published lead window." />
        ) : (
          <div className="table-container">
            <table>
            <thead>
              <tr>
                <th>Period</th>
                <th>Near vs far</th>
                <th>Adjacent pairs</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr key={item.period}>
                  <td>{item.period}</td>
                  <td>{item.near_far_elasticity ? formatIndex(item.near_far_elasticity, 3) : "—"}</td>
                  <td>
                    {item.pairs
                      .map(
                        (pair) =>
                          `T+${pair.from_apw}→${pair.to_apw}: ${pair.elasticity ? formatIndex(pair.elasticity, 3) : "—"}`,
                      )
                      .join(" · ")}
                  </td>
                </tr>
              ))}
            </tbody>
            </table>
          </div>
        )}
      </div>
    </section>
  );
}
