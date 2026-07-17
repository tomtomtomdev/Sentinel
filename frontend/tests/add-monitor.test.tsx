import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import { api } from "../src/lib/api";
import { AddMonitorPage } from "../src/pages/AddMonitorPage";

vi.mock("../src/lib/api", () => ({
  api: {
    get: vi.fn().mockResolvedValue([]),
    post: vi.fn(),
    postForm: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
  },
  ApiError: class ApiError extends Error {},
}));

const mockedPost = vi.mocked(api.post);
const mockedPostForm = vi.mocked(api.postForm);

const CURL_DRAFT = {
  name: "POST /v1/checkout",
  method: "POST",
  url: "https://api.stripe.com/v1/checkout",
  headers: { "X-Api-Key": "k1" },
  query_params: {},
  body: '{"amount":100}',
  body_kind: "json",
  follow_redirects: false,
  assertions: [],
  warnings: [],
};

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/monitors/new"]}>
        <Routes>
          <Route path="/monitors/new" element={<AddMonitorPage />} />
          <Route path="/monitors" element={<h1>Monitors</h1>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("add monitor — tabs", () => {
  it("shows the three tabs with Paste cURL active by default", () => {
    renderPage();

    expect(screen.getByRole("tab", { name: /paste curl/i })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(
      screen.getByRole("tab", { name: /import collection/i }),
    ).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /manual setup/i })).toBeInTheDocument();
  });
});

describe("add monitor — paste cURL", () => {
  it("parses via POST /imports/curl and previews the detected request", async () => {
    mockedPost.mockResolvedValue({ drafts: [CURL_DRAFT] });
    renderPage();

    await userEvent.type(
      screen.getByPlaceholderText(/curl/i),
      "curl -X POST https://api.stripe.com/v1/checkout",
    );
    await userEvent.click(screen.getByRole("button", { name: /parse request/i }));

    expect(mockedPost).toHaveBeenCalledWith("/imports/curl", {
      command: "curl -X POST https://api.stripe.com/v1/checkout",
    });
    const preview = await screen.findByText(/detected request/i);
    const card = preview.closest("section")!;
    expect(within(card).getByText("POST")).toBeInTheDocument();
    expect(
      within(card).getByText("https://api.stripe.com/v1/checkout"),
    ).toBeInTheDocument();
    expect(within(card).getByText("X-Api-Key:")).toBeInTheDocument();
    expect(within(card).getByText('{"amount":100}')).toBeInTheDocument();
  });

  it("creates the monitor from the draft plus the monitoring rules", async () => {
    mockedPost
      .mockResolvedValueOnce({ drafts: [CURL_DRAFT] }) // parse
      .mockResolvedValueOnce({ id: "m1", name: "POST /v1/checkout" }); // create
    renderPage();

    await userEvent.type(screen.getByPlaceholderText(/curl/i), "curl …");
    await userEvent.click(screen.getByRole("button", { name: /parse request/i }));
    await screen.findByText(/detected request/i);
    await userEvent.click(screen.getByRole("button", { name: /create monitor/i }));

    expect(mockedPost).toHaveBeenLastCalledWith("/monitors", {
      name: "POST /v1/checkout",
      method: "POST",
      url: "https://api.stripe.com/v1/checkout",
      headers: { "X-Api-Key": "k1" },
      query_params: {},
      body: '{"amount":100}',
      body_kind: "json",
      follow_redirects: false,
      interval_seconds: 60,
      assertions: [{ type: "status_code", params: { equals: 200 } }],
    });
    // returns to the dashboard route after creating
    expect(await screen.findByText("Monitors")).toBeInTheDocument();
  });

  it("shows a toast when parsing fails", async () => {
    mockedPost.mockRejectedValue(new Error("could not parse curl command"));
    renderPage();

    await userEvent.type(screen.getByPlaceholderText(/curl/i), "not a curl");
    await userEvent.click(screen.getByRole("button", { name: /parse request/i }));

    expect(
      await screen.findByText(/could not detect a request/i),
    ).toBeInTheDocument();
    expect(screen.queryByText(/detected request/i)).not.toBeInTheDocument();
  });
});

describe("add monitor — manual setup", () => {
  it("creates a monitor from the manual form with headers and rules", async () => {
    mockedPost.mockResolvedValue({ id: "m2", name: "Checkout API" });
    renderPage();

    await userEvent.click(screen.getByRole("tab", { name: /manual setup/i }));
    await userEvent.type(
      screen.getByPlaceholderText("e.g. Checkout API"),
      "Checkout API",
    );
    await userEvent.type(
      screen.getByPlaceholderText("https://api.acme.io/v1/health"),
      "https://api.acme.io/v1/pay",
    );
    await userEvent.type(screen.getByPlaceholderText("Header name"), "X-Team");
    await userEvent.type(screen.getByPlaceholderText("Value"), "payments");
    await userEvent.selectOptions(
      screen.getByLabelText(/check interval/i),
      "5m",
    );
    await userEvent.click(screen.getByRole("button", { name: /create monitor/i }));

    expect(mockedPost).toHaveBeenCalledWith("/monitors", {
      name: "Checkout API",
      method: "GET",
      url: "https://api.acme.io/v1/pay",
      headers: { "X-Team": "payments" },
      interval_seconds: 300,
      assertions: [{ type: "status_code", params: { equals: 200 } }],
    });
  });

  it("refuses to create without a URL and shows a toast", async () => {
    renderPage();

    await userEvent.click(screen.getByRole("tab", { name: /manual setup/i }));
    await userEvent.click(screen.getByRole("button", { name: /create monitor/i }));

    expect(await screen.findByText(/enter an endpoint url/i)).toBeInTheDocument();
    expect(mockedPost).not.toHaveBeenCalled();
  });
});

describe("add monitor — import collection", () => {
  it("uploads the file, lists endpoints, and creates the selected ones", async () => {
    mockedPostForm.mockResolvedValue({
      drafts: [
        { ...CURL_DRAFT, name: "Login", url: "https://api.acme.io/login" },
        { ...CURL_DRAFT, name: "Health", method: "GET", url: "https://api.acme.io/health" },
      ],
    });
    mockedPost.mockResolvedValue({ id: "m3" });
    renderPage();

    await userEvent.click(screen.getByRole("tab", { name: /import collection/i }));
    const file = new File(['{"info":{},"item":[]}'], "acme.postman.json", {
      type: "application/json",
    });
    await userEvent.upload(screen.getByTestId("import-file-input"), file);

    expect(mockedPostForm).toHaveBeenCalledWith(
      "/imports/postman",
      expect.any(FormData),
    );
    expect(await screen.findByText("Login")).toBeInTheDocument();
    expect(screen.getByText("Health")).toBeInTheDocument();

    // deselect one endpoint, then create — only the selected one is posted
    await userEvent.click(screen.getByRole("checkbox", { name: /login/i }));
    await userEvent.click(
      screen.getByRole("button", { name: /create 1 monitor/i }),
    );

    expect(mockedPost).toHaveBeenCalledTimes(1);
    expect(mockedPost).toHaveBeenCalledWith(
      "/monitors",
      expect.objectContaining({ name: "Health", url: "https://api.acme.io/health" }),
    );
  });

  it("shows a toast when the upload is rejected", async () => {
    mockedPostForm.mockRejectedValue(new Error("uploaded file is not valid JSON"));
    renderPage();

    await userEvent.click(screen.getByRole("tab", { name: /import collection/i }));
    const file = new File(["not json"], "bad.json", { type: "application/json" });
    await userEvent.upload(screen.getByTestId("import-file-input"), file);

    expect(await screen.findByText(/not valid json/i)).toBeInTheDocument();
  });
});
