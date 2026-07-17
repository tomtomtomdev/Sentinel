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
