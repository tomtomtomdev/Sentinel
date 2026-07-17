import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";

import { AppRoutes } from "../src/App";

vi.mock("../src/lib/api", () => ({
  api: {
    get: vi.fn().mockResolvedValue([]),
    post: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
  },
  ApiError: class ApiError extends Error {},
}));

function renderAt(path: string) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[path]}>
        <AppRoutes />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("app shell", () => {
  it("shows the Sentinel brand and Monitors nav in the sidebar", () => {
    renderAt("/monitors");

    expect(screen.getByText("Sentinel")).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /^monitors$/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /auth sources/i }),
    ).toBeInTheDocument();
  });

  it("renders the auth-sources screen at /auth-sources", async () => {
    renderAt("/auth-sources");

    expect(
      await screen.findByRole("heading", { level: 1, name: "Auth sources" }),
    ).toBeInTheDocument();
  });

  it("renders the dashboard at /monitors with an Add monitor action", () => {
    renderAt("/monitors");

    expect(
      screen.getByRole("heading", { level: 1, name: "Monitors" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /add monitor/i }),
    ).toBeInTheDocument();
  });

  it("redirects / to the dashboard", () => {
    renderAt("/");

    expect(
      screen.getByRole("heading", { level: 1, name: "Monitors" }),
    ).toBeInTheDocument();
  });

  it("renders the add-monitor screen at /monitors/new", () => {
    renderAt("/monitors/new");

    expect(
      screen.getByRole("heading", { level: 1, name: "Add a monitor" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /back to monitors/i }),
    ).toBeInTheDocument();
  });
});
