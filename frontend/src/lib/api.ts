/**
 * Typed fetch wrapper for the Sentinel API.
 *
 * Every call carries the S9a `Authorization: Bearer <AUTH_TOKEN>` header when
 * a token is configured, and non-2xx responses are raised as `ApiError` built
 * from the SPEC §5 envelope `{"error": {"code", "message", "details"}}`.
 */

import { API_BASE_URL, getAuthToken } from "./config";

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: Record<string, unknown>;

  constructor(
    status: number,
    code: string,
    message: string,
    details: Record<string, unknown> = {},
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

interface ErrorEnvelope {
  error: {
    code: string;
    message: string;
    details?: Record<string, unknown>;
  };
}

function isErrorEnvelope(body: unknown): body is ErrorEnvelope {
  if (typeof body !== "object" || body === null || !("error" in body)) {
    return false;
  }
  const error = (body as { error: unknown }).error;
  return (
    typeof error === "object" &&
    error !== null &&
    typeof (error as { code?: unknown }).code === "string" &&
    typeof (error as { message?: unknown }).message === "string"
  );
}

async function toApiError(response: Response): Promise<ApiError> {
  const body: unknown = await response.json().catch(() => null);
  if (isErrorEnvelope(body)) {
    return new ApiError(
      response.status,
      body.error.code,
      body.error.message,
      body.error.details ?? {},
    );
  }
  return new ApiError(
    response.status,
    `http_${response.status}`,
    `Request failed with HTTP ${response.status}`,
  );
}

async function apiFetch<T>(
  path: string,
  options: { method?: string; body?: unknown; signal?: AbortSignal } = {},
): Promise<T> {
  const headers = new Headers({ Accept: "application/json" });
  const token = getAuthToken();
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  if (options.body !== undefined) {
    headers.set("Content-Type", "application/json");
  }

  // Resolve against the page origin: a relative API_BASE_URL (same-origin
  // deploy) stays valid outside the browser's implicit base (e.g. in tests),
  // and an absolute one wins over the base per the URL spec.
  const url = new URL(`${API_BASE_URL}${path}`, window.location.origin);
  const request = new Request(url, {
    method: options.method ?? "GET",
    headers,
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
    signal: options.signal,
  });

  const response = await fetch(request);
  if (!response.ok) {
    throw await toApiError(response);
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

export const api = {
  get: <T>(path: string, signal?: AbortSignal) => apiFetch<T>(path, { signal }),
  post: <T>(path: string, body: unknown) =>
    apiFetch<T>(path, { method: "POST", body }),
  patch: <T>(path: string, body: unknown) =>
    apiFetch<T>(path, { method: "PATCH", body }),
  delete: <T = void>(path: string) => apiFetch<T>(path, { method: "DELETE" }),
};
