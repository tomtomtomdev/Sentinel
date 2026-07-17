import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import { api } from "../src/lib/api";
import { MonitorDetailPage } from "../src/pages/MonitorDetailPage";

vi.mock("../src/lib/api", () => ({
  api: {
    get: vi.fn(),
    post: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
  },
  ApiError: class ApiError extends Error {},
}));

const mockedGet = vi.mocked(api.get);
const mockedPatch = vi.mocked(api.patch);
const mockedDelete = vi.mocked(api.delete);

const MONITOR = {
  id: "m1",
  name: "Checkout API",
  method: "POST",
  url: "https://api.acme.io/v1/checkout",
  headers: {},
  interval_seconds: 60,
  timeout_seconds: 10,
  enabled: true,
  auth_source_id: null,
  assertions: [{ type: "status_code", params: { equals: 200 } }],
};

const STATS = {
  window: "24h",
  checks: 1440,
  failures: 3,
  uptime_pct: 99.79,
  latency_ms: { p50: 120, p95: 340, p99: 510 },
  status: "up",
  since: "2026-07-16T08:00:00Z",
};

const SOURCES = [
  {
    id: "as1",
    name: "Staging login",
    mode: "custom",
    enabled: true,
    token_state: {
      status: "valid",
      obtained_at: "2026-07-17T09:00:00Z",
      expires_at: "2026-07-17T13:00:00Z",
      last_refresh_error: null,
    },
  },
];

function stubRoutes() {
  mockedGet.mockImplementation((path: string) => {
    if (path === "/monitors/m1") return Promise.resolve(MONITOR);
    if (path.startsWith("/monitors/m1/stats")) return Promise.resolve(STATS);
    if (path === "/auth-sources") return Promise.resolve(SOURCES);
    return Promise.reject(new Error(`unexpected GET ${path}`));
  });
}

function renderDetail() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/monitors/m1"]}>
        <Routes>
          <Route path="/monitors/:id" element={<MonitorDetailPage />} />
          <Route path="/monitors" element={<h1>Monitors</h1>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("monitor detail", () => {
  it("shows identity, 24h stats, and config summary", async () => {
    stubRoutes();
    renderDetail();

    expect(
      await screen.findByRole("heading", { level: 1, name: "Checkout API" }),
    ).toBeInTheDocument();
    expect(screen.getByText("POST")).toBeInTheDocument();
    expect(screen.getByText("api.acme.io/v1/checkout")).toBeInTheDocument();
    expect(await screen.findByText("Operational")).toBeInTheDocument();
    expect(screen.getByText("99.79%")).toBeInTheDocument();
    expect(screen.getByText("340ms")).toBeInTheDocument();
    expect(screen.getByText("1440")).toBeInTheDocument(); // checks
    expect(screen.getByText("3")).toBeInTheDocument(); // failures
    expect(mockedGet).toHaveBeenCalledWith(
      "/monitors/m1/stats?window=24h",
      expect.anything(),
    );
  });

  it("links an auth source via PATCH", async () => {
    stubRoutes();
    mockedPatch.mockResolvedValue({ ...MONITOR, auth_source_id: "as1" });
    renderDetail();

    await screen.findByRole("heading", { level: 1, name: "Checkout API" });
    await userEvent.selectOptions(
      screen.getByLabelText(/auth source/i),
      "as1",
    );

    expect(mockedPatch).toHaveBeenCalledWith("/monitors/m1", {
      auth_source_id: "as1",
    });
  });

  it("deletes the monitor and returns to the dashboard", async () => {
    stubRoutes();
    mockedDelete.mockResolvedValue(undefined);
    renderDetail();

    await screen.findByRole("heading", { level: 1, name: "Checkout API" });
    await userEvent.click(screen.getByRole("button", { name: /delete monitor/i }));
    await userEvent.click(screen.getByRole("button", { name: /confirm delete/i }));

    expect(mockedDelete).toHaveBeenCalledWith("/monitors/m1");
    expect(await screen.findByText("Monitors")).toBeInTheDocument();
  });
});
