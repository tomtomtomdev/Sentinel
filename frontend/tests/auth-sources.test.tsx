import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";

import { api } from "../src/lib/api";
import { AuthSourcesPage } from "../src/pages/AuthSourcesPage";

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
const mockedPost = vi.mocked(api.post);
const mockedPatch = vi.mocked(api.patch);
const mockedDelete = vi.mocked(api.delete);

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
  {
    id: "as2",
    name: "Broken login",
    mode: "custom",
    enabled: true,
    token_state: {
      status: "error",
      obtained_at: null,
      expires_at: null,
      last_refresh_error: "login returned HTTP 500",
    },
  },
];

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/auth-sources"]}>
        <AuthSourcesPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("auth sources", () => {
  it("lists sources with their token state (never a token value)", async () => {
    mockedGet.mockResolvedValue(SOURCES);
    renderPage();

    const staging = (await screen.findByText("Staging login")).closest("li")!;
    expect(within(staging).getByText(/valid/i)).toBeInTheDocument();

    const broken = screen.getByText("Broken login").closest("li")!;
    expect(within(broken).getByText(/error/i)).toBeInTheDocument();
    expect(
      within(broken).getByText("login returned HTTP 500"),
    ).toBeInTheDocument();
  });

  it("manually refreshes a source's token", async () => {
    mockedGet.mockResolvedValue(SOURCES);
    mockedPost.mockResolvedValue({
      status: "valid",
      obtained_at: "2026-07-17T12:00:00Z",
      expires_at: "2026-07-17T16:00:00Z",
      last_refresh_error: null,
    });
    renderPage();

    const staging = (await screen.findByText("Staging login")).closest("li")!;
    await userEvent.click(
      within(staging).getByRole("button", { name: /refresh/i }),
    );

    expect(mockedPost).toHaveBeenCalledWith("/auth-sources/as1/refresh", {});
    expect(await screen.findByText(/token refreshed/i)).toBeInTheDocument();
  });

  it("creates a custom auth source from the form", async () => {
    mockedGet.mockResolvedValue([]);
    mockedPost.mockResolvedValue({ id: "as9", name: "Prod login" });
    renderPage();

    await userEvent.click(
      await screen.findByRole("button", { name: /new auth source/i }),
    );
    await userEvent.type(screen.getByLabelText(/^name/i), "Prod login");
    await userEvent.selectOptions(screen.getByLabelText(/method/i), "POST");
    await userEvent.type(
      screen.getByLabelText(/login url/i),
      "https://api.acme.io/auth/login",
    );
    // "{{" is userEvent's escape for a literal "{"
    await userEvent.type(
      screen.getByLabelText(/request body/i),
      '{{"user":"svc"}',
    );
    // the field is prefilled with the common default — replace it explicitly
    await userEvent.clear(screen.getByLabelText(/token path/i));
    await userEvent.type(screen.getByLabelText(/token path/i), "$.access_token");
    await userEvent.click(screen.getByRole("button", { name: /create auth source/i }));

    expect(mockedPost).toHaveBeenCalledWith(
      "/auth-sources",
      expect.objectContaining({
        name: "Prod login",
        mode: "custom",
        request: expect.objectContaining({
          method: "POST",
          url: "https://api.acme.io/auth/login",
          body: '{"user":"svc"}',
        }),
        extractor: { kind: "json_path", expr: "$.access_token" },
        injection: {
          target: "header",
          name: "Authorization",
          value_template: "{token_type} {token}",
        },
      }),
    );
  });

  it("disables and deletes a source", async () => {
    mockedGet.mockResolvedValue(SOURCES);
    mockedPatch.mockResolvedValue({ ...SOURCES[0], enabled: false });
    mockedDelete.mockResolvedValue(undefined);
    renderPage();

    const staging = (await screen.findByText("Staging login")).closest("li")!;
    await userEvent.click(
      within(staging).getByRole("button", { name: /disable/i }),
    );
    expect(mockedPatch).toHaveBeenCalledWith("/auth-sources/as1", {
      enabled: false,
    });

    await userEvent.click(
      within(staging).getByRole("button", { name: /delete/i }),
    );
    expect(mockedDelete).toHaveBeenCalledWith("/auth-sources/as1");
  });
});
