import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";

import { api } from "../src/lib/api";
import type { MonitorListItem } from "../src/lib/monitors";
import { DashboardPage } from "../src/pages/DashboardPage";

vi.mock("../src/lib/api", () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  ApiError: class ApiError extends Error {},
}));

const mockedGet = vi.mocked(api.get);

function monitor(overrides: Partial<MonitorListItem>): MonitorListItem {
  return {
    id: "00000000-0000-0000-0000-000000000001",
    name: "Prod health",
    method: "GET",
    url: "https://api.acme.io/v1/health",
    enabled: true,
    summary: {
      status: "up",
      since: "2026-07-16T00:00:00Z",
      last_check_at: "2026-07-17T11:59:00Z",
      uptime_pct: 99.95,
      latency_p95_ms: 73,
      checks: 1440,
    },
    ...overrides,
  };
}

const FIXTURES: MonitorListItem[] = [
  monitor({}),
  monitor({
    id: "00000000-0000-0000-0000-000000000002",
    name: "Inventory Sync",
    method: "PUT",
    url: "https://api.acme.io/v1/inventory/sync",
    summary: {
      status: "down",
      since: "2026-07-17T10:00:00Z",
      last_check_at: "2026-07-17T11:58:00Z",
      uptime_pct: 91.21,
      latency_p95_ms: null,
      checks: 1440,
    },
  }),
  monitor({
    id: "00000000-0000-0000-0000-000000000003",
    name: "New endpoint",
    method: "POST",
    url: "https://api.acme.io/v1/orders",
    summary: {
      status: "unknown",
      since: null,
      last_check_at: null,
      uptime_pct: 0,
      latency_p95_ms: null,
      checks: 0,
    },
  }),
];

function renderDashboard() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/monitors"]}>
        <DashboardPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("dashboard", () => {
  it("requests the monitor list with the 24h summary include", async () => {
    mockedGet.mockResolvedValue(FIXTURES);
    renderDashboard();

    await screen.findByText("Prod health");
    expect(mockedGet).toHaveBeenCalledWith(
      "/monitors?include=summary",
      expect.anything(),
    );
  });

  it("renders a card per monitor: status pill, method chip, stripped URL, metrics", async () => {
    mockedGet.mockResolvedValue(FIXTURES);
    renderDashboard();

    const upCard = (await screen.findByText("Prod health")).closest("article")!;
    expect(upCard.closest("a")).toHaveAttribute(
      "href",
      "/monitors/00000000-0000-0000-0000-000000000001",
    );
    expect(within(upCard).getByText("Operational")).toBeInTheDocument();
    expect(within(upCard).getByText("GET")).toBeInTheDocument();
    expect(within(upCard).getByText("api.acme.io/v1/health")).toBeInTheDocument();
    expect(within(upCard).getByText("99.95%")).toBeInTheDocument();
    expect(within(upCard).getByText("73ms")).toBeInTheDocument();

    const downCard = screen.getByText("Inventory Sync").closest("article")!;
    expect(within(downCard).getByText("Down")).toBeInTheDocument();
    expect(within(downCard).getByText("—")).toBeInTheDocument();

    const unknownCard = screen.getByText("New endpoint").closest("article")!;
    expect(within(unknownCard).getByText("Unknown")).toBeInTheDocument();
    expect(within(unknownCard).getByText(/no data yet/i)).toBeInTheDocument();
  });

  it("computes the summary stat cards from the list", async () => {
    mockedGet.mockResolvedValue(FIXTURES);
    renderDashboard();

    const stats = await screen.findByRole("list", { name: /summary/i });
    const cards = within(stats).getAllByRole("listitem");
    const byLabel = Object.fromEntries(
      cards.map((c) => [
        within(c).getByTestId("stat-label").textContent,
        within(c).getByTestId("stat-value").textContent,
      ]),
    );
    expect(byLabel["Operational"]).toBe("1");
    expect(byLabel["Down"]).toBe("1");
    expect(byLabel["Unknown"]).toBe("1");
    // Avg over monitors WITH data (checks > 0): (99.95 + 91.21) / 2 = 95.58
    expect(byLabel["Avg uptime · 24h"]).toBe("95.58%");
  });

  it("filters cards by the search field (name or URL)", async () => {
    mockedGet.mockResolvedValue(FIXTURES);
    renderDashboard();
    await screen.findByText("Prod health");

    await userEvent.type(
      screen.getByPlaceholderText("Search monitors"),
      "inventory",
    );

    expect(screen.getByText("Inventory Sync")).toBeInTheDocument();
    expect(screen.queryByText("Prod health")).not.toBeInTheDocument();
  });

  it("shows the create toast and NEW pill when arriving from the create flow", async () => {
    mockedGet.mockResolvedValue(FIXTURES);
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter
          initialEntries={[
            {
              pathname: "/monitors",
              state: {
                toast: "Monitor created — now watching",
                newIds: ["00000000-0000-0000-0000-000000000001"],
              },
            },
          ]}
        >
          <DashboardPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(
      await screen.findByText("Monitor created — now watching"),
    ).toBeInTheDocument();
    const card = (await screen.findByText("Prod health")).closest("article")!;
    expect(within(card).getByText("NEW")).toBeInTheDocument();
  });

  it("shows an empty state with an add CTA when there are no monitors", async () => {
    mockedGet.mockResolvedValue([]);
    renderDashboard();

    expect(await screen.findByText(/no monitors yet/i)).toBeInTheDocument();
  });

  it("surfaces a load failure instead of an empty dashboard", async () => {
    mockedGet.mockRejectedValue(new Error("boom"));
    renderDashboard();

    expect(await screen.findByText(/could not load monitors/i)).toBeInTheDocument();
  });
});
