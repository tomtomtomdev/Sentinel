/** Pure display formatters for the dashboard (design: docs/design Screen 1). */

export function stripProtocol(url: string): string {
  return url.replace(/^https?:\/\//, "");
}

/** "100%" for whole numbers, otherwise up to 2 decimals ("99.79%", "95.7%"). */
export function formatUptime(pct: number): string {
  return `${parseFloat(pct.toFixed(2))}%`;
}

export function formatLatency(ms: number | null): string {
  return ms === null ? "—" : `${ms}ms`;
}

export function timeAgo(at: Date | string | null, now: Date): string {
  if (at === null) {
    return "—";
  }
  const then = typeof at === "string" ? new Date(at) : at;
  const seconds = Math.max(0, Math.floor((now.getTime() - then.getTime()) / 1000));
  if (seconds < 10) {
    return "just now";
  }
  if (seconds < 60) {
    return `${seconds}s ago`;
  }
  if (seconds < 3600) {
    return `${Math.floor(seconds / 60)}m ago`;
  }
  if (seconds < 86400) {
    return `${Math.floor(seconds / 3600)}h ago`;
  }
  return `${Math.floor(seconds / 86400)}d ago`;
}
