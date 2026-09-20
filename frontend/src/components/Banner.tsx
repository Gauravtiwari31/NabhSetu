import { useQuery } from "@tanstack/react-query";
import { api } from "../api";

const COPY: Record<string, string> = {
  mock: "SIMULATED DATA — these numbers are not measurements of Indian airfares.",
  live: "LIVE MODE — collection is limited to currently permitted sources. Denied OTAs are not substituted.",
  unavailable: "INDEX UNAVAILABLE — collect permitted fares and publish before a series appears.",
  policy_denied: "POLICY DENIED — a source was blocked without substitution.",
};

export function Banner() {
  const status = useQuery({ queryKey: ["status"], queryFn: api.status });
  const kind = status.data?.banner ?? "unavailable";
  return (
    <div className={`banner ${kind}`} role="status">
      {COPY[kind] ?? COPY.unavailable}
    </div>
  );
}
