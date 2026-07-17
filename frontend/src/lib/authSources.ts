/**
 * Auth-source types + hooks (SPEC §3.9). `token_state` is metadata only — the
 * backend never returns a token value and this UI never asks for one.
 */

import { useQuery } from "@tanstack/react-query";

import { api } from "./api";

export type TokenStatus = "valid" | "expired" | "error" | "none";

export interface TokenStateSummary {
  status: TokenStatus;
  obtained_at: string | null;
  expires_at: string | null;
  last_refresh_error: string | null;
}

export interface AuthSource {
  id: string;
  name: string;
  mode: string;
  enabled: boolean;
  token_state: TokenStateSummary | null;
}

export function useAuthSources() {
  return useQuery({
    queryKey: ["auth-sources"],
    queryFn: ({ signal }) => api.get<AuthSource[]>("/auth-sources", signal),
  });
}

export function refreshAuthSource(id: string): Promise<TokenStateSummary> {
  return api.post<TokenStateSummary>(`/auth-sources/${id}/refresh`, {});
}

export interface AuthSourceCreatePayload {
  name: string;
  mode: "custom";
  request: {
    method: string;
    url: string;
    headers: Record<string, string>;
    body: string | null;
  };
  extractor: { kind: "json_path"; expr: string };
  expiry: { kind: "json_path_seconds"; value: string } | null;
  injection: { target: "header"; name: string; value_template: string };
}

export function createAuthSource(
  payload: AuthSourceCreatePayload,
): Promise<AuthSource> {
  return api.post<AuthSource>("/auth-sources", payload);
}
