import type { StatusPayload } from "./types";

const API_BASE = import.meta.env.VITE_API_BASE ?? "";
const API_KEY = import.meta.env.VITE_API_KEY ?? "change-me";

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      "X-API-Key": API_KEY,
      ...(init.headers ?? {}),
    },
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `Request failed: ${response.status}`);
  }
  return (await response.json()) as T;
}

export const api = {
  status: () => request<StatusPayload>("/v1/status"),
  health: () => request("/health"),
  index: (frequency = "daily", series = "headline") =>
    request(`/v1/index?frequency=${frequency}&series=${series}`),
  cells: () => request("/v1/index/cells"),
  coverage: () => request("/v1/coverage"),
  elasticity: () => request("/v1/elasticity"),
  methodology: () => request("/v1/methodology"),
  basket: () => request("/v1/basket"),
  weights: () => request("/v1/weights"),
  provenance: () => request("/v1/provenance"),
  backtest: () => request("/v1/backtest"),
  sources: () => request("/sources"),
  sourceStatus: (id: string) => request(`/sources/${id}/status`),
  fares: (origin?: string, destination?: string) => {
    const params = new URLSearchParams();
    if (origin) params.set("origin", origin);
    if (destination) params.set("destination", destination);
    const suffix = params.toString() ? `?${params}` : "";
    return request(`/fares/latest${suffix}`);
  },
  jobs: () => request("/collection-jobs"),
  collect: (body: Record<string, unknown>) =>
    request("/collection-jobs", { method: "POST", body: JSON.stringify(body) }),
  publish: () => request("/v1/index/publish", { method: "POST" }),
};
