/**
 * Monitor list types + query hook. Field names mirror the backend DTOs
 * (`interface/api/schemas.py`) — only what the dashboard reads is typed here.
 */

import { useQuery } from "@tanstack/react-query";

import { api } from "./api";

export type MonitorStatus = "up" | "down" | "unknown";

export interface MonitorSummary {
  status: MonitorStatus;
  since: string | null;
  last_check_at: string | null;
  uptime_pct: number;
  latency_p95_ms: number | null;
  /** 0 marks "no data yet" — distinct from 0% uptime (SPEC §3.5). */
  checks: number;
}

export interface MonitorListItem {
  id: string;
  name: string;
  method: string;
  url: string;
  enabled: boolean;
  summary: MonitorSummary | null;
}

export function useMonitors() {
  return useQuery({
    queryKey: ["monitors", { include: "summary" }],
    queryFn: ({ signal }) =>
      api.get<MonitorListItem[]>("/monitors?include=summary", signal),
  });
}

export interface MonitorDetail {
  id: string;
  name: string;
  method: string;
  url: string;
  headers: Record<string, string>;
  interval_seconds: number;
  timeout_seconds: number;
  enabled: boolean;
  auth_source_id: string | null;
  assertions: { type: string; params: Record<string, unknown> }[];
}

export interface MonitorStats {
  window: string;
  checks: number;
  failures: number;
  uptime_pct: number;
  latency_ms: { p50: number | null; p95: number | null; p99: number | null };
  status: MonitorStatus;
  since: string | null;
}

export function useMonitor(id: string) {
  return useQuery({
    queryKey: ["monitors", id],
    queryFn: ({ signal }) => api.get<MonitorDetail>(`/monitors/${id}`, signal),
  });
}

export function useMonitorStats(id: string, window: string) {
  return useQuery({
    queryKey: ["monitors", id, "stats", window],
    queryFn: ({ signal }) =>
      api.get<MonitorStats>(`/monitors/${id}/stats?window=${window}`, signal),
  });
}
