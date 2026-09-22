import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api";
import { EmptyState } from "../components/EmptyState";
import { StatusChip } from "../components/StatusChip";
import { formatINR } from "../format";

const ROUTES = ["DEL-BOM", "BOM-DEL", "DEL-BLR", "BOM-BLR", "DEL-HYD"];

export function FaresPage() {
  const [route, setRoute] = useState("DEL-BOM");
  const [origin, destination] = route.split("-");
  const fares = useQuery({
    queryKey: ["fares", origin, destination],
    queryFn: () => api.fares(origin, destination),
  });
  const items = ((fares.data as { items?: Array<Record<string, string | number | boolean>> } | undefined)?.items ??
    []) as Array<{
    observation_id: string;
    origin: string;
    destination: string;
    travel_date: string;
    lead_time_days: number | string;
    carrier: string;
    flight_number: string;
    total_fare: string;
    disposition: string;
    is_simulated: boolean;
    collector: string;
  }>;
  return (
    <section>
      <header className="page-head">
        <div>
          <h2>Fare drill-down</h2>
          <p className="muted">Latest canonical observations per flight identity. Simulated rows stay labelled.</p>
        </div>
        <label>
          Route
          <select value={route} onChange={(event) => setRoute(event.target.value)}>
            {ROUTES.map((item) => (
              <option key={item}>{item}</option>
            ))}
          </select>
        </label>
      </header>
      <div className="card">
        {items.length === 0 ? (
          <EmptyState title="No fares for this route" body="Run a permitted collection for the selected city-pair." />
        ) : (
          <div className="table-container">
            <table>
            <thead>
              <tr>
                <th>Route</th>
                <th>Travel</th>
                <th>Lead</th>
                <th>Carrier</th>
                <th>Flight</th>
                <th>Fare</th>
                <th>Disposition</th>
                <th>Label</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr key={item.observation_id}>
                  <td>
                    {item.origin}-{item.destination}
                  </td>
                  <td>{item.travel_date}</td>
                  <td>T+{item.lead_time_days}</td>
                  <td>{item.carrier}</td>
                  <td>{item.flight_number}</td>
                  <td>{formatINR(item.total_fare)}</td>
                  <td>{item.disposition}</td>
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
          </div>
        )}
      </div>
    </section>
  );
}
