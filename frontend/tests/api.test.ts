import { ApiError, api } from "../src/lib/api";
import { AUTH_TOKEN_STORAGE_KEY, setAuthToken } from "../src/lib/config";

function stubFetch(response: {
  status?: number;
  body?: unknown;
  contentType?: string;
}) {
  const { status = 200, body = {}, contentType = "application/json" } = response;
  // A 204 Response may not carry a body — the constructor throws otherwise.
  const payload =
    status === 204 ? null : typeof body === "string" ? body : JSON.stringify(body);
  const fetchMock = vi.fn().mockResolvedValue(
    new Response(payload, {
      status,
      headers: { "Content-Type": contentType },
    }),
  );
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function requestOf(fetchMock: ReturnType<typeof vi.fn>): Request {
  return fetchMock.mock.calls[0][0] as Request;
}

describe("api client auth (S9a: Bearer token on every call)", () => {
  it("sends Authorization: Bearer <token> when a token is stored", async () => {
    setAuthToken("tok-123");
    const fetchMock = stubFetch({ body: [] });

    await api.get("/monitors");

    expect(requestOf(fetchMock).headers.get("Authorization")).toBe(
      "Bearer tok-123",
    );
  });

  it("sends no Authorization header when no token is configured", async () => {
    const fetchMock = stubFetch({ body: [] });

    await api.get("/monitors");

    expect(requestOf(fetchMock).headers.get("Authorization")).toBeNull();
  });

  it("persists the token for later sessions", () => {
    setAuthToken("tok-456");
    expect(localStorage.getItem(AUTH_TOKEN_STORAGE_KEY)).toBe("tok-456");
  });
});

describe("api client requests", () => {
  it("GET prefixes the API base path and returns parsed JSON", async () => {
    const fetchMock = stubFetch({ body: [{ id: "m1" }] });

    const result = await api.get<{ id: string }[]>("/monitors");

    expect(requestOf(fetchMock).url).toContain("/api/v1/monitors");
    expect(result).toEqual([{ id: "m1" }]);
  });

  it("POST serializes the body as JSON with the right content type", async () => {
    const fetchMock = stubFetch({ status: 201, body: { id: "m1" } });

    await api.post("/monitors", { name: "Prod health" });

    const req = requestOf(fetchMock);
    expect(req.method).toBe("POST");
    expect(req.headers.get("Content-Type")).toBe("application/json");
    await expect(req.json()).resolves.toEqual({ name: "Prod health" });
  });

  it("DELETE tolerates an empty 204 response", async () => {
    stubFetch({ status: 204, body: "" });

    await expect(api.delete("/monitors/m1")).resolves.toBeUndefined();
  });
});

describe("api client errors (SPEC §5 envelope)", () => {
  it("maps the error envelope to a typed ApiError", async () => {
    stubFetch({
      status: 404,
      body: {
        error: {
          code: "not_found",
          message: "Monitor not found",
          details: { id: "m9" },
        },
      },
    });

    const err = await api.get("/monitors/m9").catch((e: unknown) => e);

    expect(err).toBeInstanceOf(ApiError);
    const apiErr = err as ApiError;
    expect(apiErr.status).toBe(404);
    expect(apiErr.code).toBe("not_found");
    expect(apiErr.message).toBe("Monitor not found");
    expect(apiErr.details).toEqual({ id: "m9" });
  });

  it("still raises ApiError when the error body is not the envelope", async () => {
    stubFetch({ status: 502, body: "Bad Gateway", contentType: "text/plain" });

    const err = await api.get("/monitors").catch((e: unknown) => e);

    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(502);
    expect((err as ApiError).code).toBe("http_502");
  });

  it("maps a 401 to the unauthorized code from the envelope", async () => {
    stubFetch({
      status: 401,
      body: {
        error: { code: "unauthorized", message: "Missing bearer token" },
      },
    });

    const err = await api.get("/monitors").catch((e: unknown) => e);

    expect((err as ApiError).code).toBe("unauthorized");
    expect((err as ApiError).status).toBe(401);
  });
});
