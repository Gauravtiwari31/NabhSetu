import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { expect, test, vi } from "vitest";
import { Banner } from "./Banner";

vi.mock("../api", () => ({
  api: {
    status: vi.fn().mockResolvedValue({
      banner: "mock",
      data_mode: "mock",
      is_simulated: true,
      notice: "simulated",
      egress_mode: "direct",
      latest_run_id: null,
      latest_run_status: null,
      blocked_sources: 0,
      enabled_sources: 1,
      pending_jobs: 0,
      meta: { is_simulated: true, data_mode: "mock", notice: "simulated" },
    }),
  },
}));

test("banner labels simulated data", async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <Banner />
    </QueryClientProvider>,
  );
  expect(await screen.findByText(/SIMULATED DATA/i)).toBeInTheDocument();
});
