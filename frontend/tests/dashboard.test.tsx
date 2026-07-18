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

/** A minimal CheckResult for the sparkline — only what the bars read. */
function result(id: string, success: boolean, latency_ms: number | null) {
  return {
    id,
    monitor_id: "00000000-0000-0000-0000-000000000001",
    started_at: "2026-07-17T09:00:00Z",
    finished_at: "2026-07-17T09:00:00Z",
    status_code: success ? 200 : null,
    latency_ms,
    response_size_bytes: null,
    cert_expires_at: null,
    success,
    error: success ? null : "timeout",
    assertion_results: [],
  };
}

function stubDashboard(
  list: MonitorListItem[] = FIXTURES,
  resultsById: Record<string, unknown[]> = {},
) {
  mockedGet.mockImplementation((path: string) => {
    if (path === "/monitors?include=summary") return Promise.resolve(list);
    const match = /^\/monitors\/([^/]+)\/results/.exec(path);
    if (match) return Promise.resolve(resultsById[match[1]] ?? []);
    return Promise.reject(new Error(`unexpected GET ${path}`));
  });
}

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
    stubDashboard();
    renderDashboard();

    await screen.findByText("Prod health");
    expect(mockedGet).toHaveBeenCalledWith(
      "/monitors?include=summary",
      expect.anything(),
    );
  });

  it("renders a card per monitor: status pill, method chip, stripped URL, metrics", async () => {
    stubDashboard();
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
    stubDashboard();
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
    stubDashboard();
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
    stubDashboard();
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

  it("renders a sparkline bar per recent check, colored by result (S12.2)", async () => {
    stubDashboard(FIXTURES, {
      "00000000-0000-0000-0000-000000000001": [
        result("r3", false, null), // newest
        result("r2", true, 200),
        result("r1", true, 100), // oldest
      ],
    });
    renderDashboard();

    const upCard = (await screen.findByText("Prod health")).closest("article")!;
    const spark = await within(upCard).findByTestId("sparkline");
    // per-monitor results are fetched with the design's 26-bar budget
    expect(mockedGet).toHaveBeenCalledWith(
      "/monitors/00000000-0000-0000-0000-000000000001/results?limit=26",
      expect.anything(),
    );

    const bars = Array.from(spark.children);
    expect(bars).toHaveLength(3);
    // oldest→newest left-to-right: green, green, red (failed check)
    expect(bars[0].className).toContain("bg-up");
    expect(bars[1].className).toContain("bg-up");
    expect(bars[2].className).toContain("bg-down");
  });

  it("does not fetch results or render a sparkline for a no-data monitor", async () => {
    stubDashboard();
    renderDashboard();

    const unknownCard = (await screen.findByText("New endpoint")).closest(
      "article",
    )!;
    expect(within(unknownCard).queryByTestId("sparkline")).not.toBeInTheDocument();
    expect(mockedGet).not.toHaveBeenCalledWith(
      "/monitors/00000000-0000-0000-0000-000000000003/results?limit=26",
      expect.anything(),
    );
  });

  it("shows an empty state with an add CTA when there are no monitors", async () => {
    stubDashboard([]);
    renderDashboard();

    expect(await screen.findByText(/no monitors yet/i)).toBeInTheDocument();
  });

  it("surfaces a load failure instead of an empty dashboard", async () => {
    mockedGet.mockRejectedValue(new Error("boom"));
    renderDashboard();

    expect(await screen.findByText(/could not load monitors/i)).toBeInTheDocument();
  });
});
