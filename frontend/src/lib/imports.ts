/**
 * Import drafts + monitor-create payloads. Draft fields mirror
 * `MonitorDraftResponse` (backend `interface/api/schemas.py`) — draft headers
 * are intentionally unredacted (the user's own input, echoed for review).
 */

import { api } from "./api";
import type { AssertionPayload } from "./rules";

export interface MonitorDraft {
  name: string;
  method: string;
  url: string;
  headers: Record<string, string>;
  query_params: Record<string, string>;
  body: string | null;
  body_kind: string;
  follow_redirects: boolean;
  assertions: AssertionPayload[];
  warnings: string[];
}

export interface ImportResponse {
  drafts: MonitorDraft[];
}

export function importCurl(command: string): Promise<ImportResponse> {
  return api.post<ImportResponse>("/imports/curl", { command });
}

export function importPostman(file: File): Promise<ImportResponse> {
  const form = new FormData();
  form.append("file", file);
  return api.postForm<ImportResponse>("/imports/postman", form);
}

export interface CreatedMonitor {
  id: string;
  name: string;
}

/** Save one reviewed draft with the chosen monitoring rules (SPEC §3.1: the
 * import endpoints persist nothing — this create call does). */
export function createFromDraft(
  draft: MonitorDraft,
  intervalSeconds: number,
  assertions: AssertionPayload[],
): Promise<CreatedMonitor> {
  return api.post<CreatedMonitor>("/monitors", {
    name: draft.name,
    method: draft.method,
    url: draft.url,
    headers: draft.headers,
    query_params: draft.query_params,
    body: draft.body,
    body_kind: draft.body_kind,
    follow_redirects: draft.follow_redirects,
    interval_seconds: intervalSeconds,
    assertions,
  });
}
