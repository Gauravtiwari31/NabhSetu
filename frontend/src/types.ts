export type SimulatedMeta = {
  is_simulated: boolean;
  data_mode: string;
  notice: string | null;
};

export type IndexPoint = {
  period: string;
  value: string;
  se: string | null;
  ci_low: string | null;
  ci_high: string | null;
  coverage_pct: string | null;
  n_matched: number;
  route: string | null;
  apw_days: number | null;
  is_simulated: boolean;
  method_version: string;
  basket_version: string;
  weights_version: string;
  frequency: string;
  series: string;
};

export type StatusPayload = {
  data_mode: string;
  egress_mode: string;
  is_simulated: boolean;
  notice: string | null;
  latest_run_id: string | null;
  latest_run_status: string | null;
  blocked_sources: number;
  enabled_sources: number;
  pending_jobs: number;
  banner: "mock" | "live" | "unavailable" | "policy_denied";
  meta: SimulatedMeta;
};
