import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { formatIndex } from "../format";

export function MethodologyPage() {
  const methodology = useQuery({ queryKey: ["methodology"], queryFn: api.methodology });
  const basket = useQuery({ queryKey: ["basket"], queryFn: api.basket });
  const weights = useQuery({ queryKey: ["weights"], queryFn: api.weights });
  const provenance = useQuery({ queryKey: ["provenance"], queryFn: api.provenance });
  const method = methodology.data as
    | {
        method_version?: string;
        variant?: string;
        basis?: string;
        omega_preset?: string;
        n_min?: number;
        notes?: string[];
        omega?: Record<string, string>;
      }
    | undefined;
  const basketData = basket.data as
    | { version?: string; name?: string; routes?: string[]; lead_windows?: number[]; config_hash?: string }
    | undefined;
  const weightData = weights.data as
    | { version?: string; source?: string; route_weights?: Record<string, string> }
    | undefined;
  const prov = provenance.data as { run_id?: string | null; input_hash?: string | null; output_hash?: string | null } | undefined;
  return (
    <section>
      <header className="page-head">
        <div>
          <h2>Methodology, basket, and provenance</h2>
          <p className="muted">Declared method v{method?.method_version ?? "—"}. Late entrants are not chain-linked.</p>
        </div>
      </header>
      <div className="grid">
        <div className="card">
          <h3>
            APIx-{method?.variant ?? "T"} · {method?.basis ?? "book"}
          </h3>
          <p>
            Omega preset <strong>{method?.omega_preset ?? "—"}</strong> · n_min {method?.n_min ?? "—"}
          </p>
          <ul>
            {(method?.notes ?? []).map((note) => (
              <li key={note}>{note}</li>
            ))}
          </ul>
        </div>
        <div className="card">
          <h3>{basketData?.name ?? "Basket"}</h3>
          <p className="muted">{basketData?.version}</p>
          <div className="chips">
            {(basketData?.routes ?? []).map((route) => (
              <span className="chip chip-neutral" key={route}>
                {route}
              </span>
            ))}
          </div>
          <p className="muted hash">{basketData?.config_hash}</p>
        </div>
      </div>
      <div className="card">
        <h3>Route weights ({weightData?.source ?? "declared"})</h3>
        <div className="table-container">
          <table>
          <thead>
            <tr>
              <th>Route</th>
              <th>Weight</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(weightData?.route_weights ?? {}).map(([route, value]) => (
              <tr key={route}>
                <td>{route}</td>
                <td>{formatIndex(value, 4)}</td>
              </tr>
            ))}
          </tbody>
          </table>
        </div>
      </div>
      <div className="card">
        <h3>Latest publication hashes</h3>
        <p>Run {prov?.run_id ?? "—"}</p>
        <p className="muted hash">input {prov?.input_hash ?? "—"}</p>
        <p className="muted hash">output {prov?.output_hash ?? "—"}</p>
      </div>
    </section>
  );
}
