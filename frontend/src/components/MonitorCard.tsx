import { useMonitorResults, type MonitorListItem, type MonitorStatus } from "../lib/monitors";
import { formatLatency, formatUptime, stripProtocol, timeAgo } from "../lib/format";

/** Backend statuses mapped to the design's palette. The design's "Degraded"
 * slot renders the backend's `unknown` (no degraded status exists in v1). */
export const STATUS = {
  up: { label: "Operational", dot: "bg-up", pill: "text-up-text bg-up-bg", metric: "text-up-text" },
  down: { label: "Down", dot: "bg-down", pill: "text-down-text bg-down-bg", metric: "text-down-text" },
  unknown: {
    label: "Unknown",
    dot: "bg-degraded",
    pill: "text-degraded-text bg-degraded-bg",
    metric: "text-degraded-text",
  },
} satisfies Record<MonitorStatus, { label: string; dot: string; pill: string; metric: string }>;

const METHOD_CHIP: Record<string, string> = {
  GET: "text-[#15803d] bg-[#dcfce7]",
  POST: "text-[#1d4ed8] bg-[#dbeafe]",
  PUT: "text-[#b45309] bg-[#fef3c7]",
  PATCH: "text-[#6d28d9] bg-[#ede9fe]",
  DELETE: "text-[#b91c1c] bg-[#fee2e2]",
};

export function StatusPill({ status }: { status: MonitorStatus }) {
  const s = STATUS[status];
  return (
    <span
      className={`shrink-0 rounded-[20px] px-[9px] py-[3px] text-[11px] font-semibold ${s.pill}`}
    >
      {s.label}
    </span>
  );
}

export function MethodChip({ method }: { method: string }) {
  const colors = METHOD_CHIP[method] ?? "text-body bg-fill";
  return (
    <span
      className={`rounded-[5px] px-[6px] py-[2px] font-mono text-[10.5px] font-semibold ${colors}`}
    >
      {method}
    </span>
  );
}

/** Design §Screen 1: 26 bars, heights 4–16px in a 30px row, colored by that
 * check's result (green/red — the design's amber is `degraded`, absent in v1).
 * Bar height scales with latency relative to the window's max; a failed check
 * with no latency gets a fixed tall red bar. Oldest→newest, left to right. */
export const SPARKLINE_BARS = 26;

function Sparkline({ monitorId, enabled }: { monitorId: string; enabled: boolean }) {
  const { data: results } = useMonitorResults(monitorId, SPARKLINE_BARS, {
    enabled,
  });
  if (!results || results.length === 0) {
    return null;
  }
  const bars = [...results].reverse(); // API is newest-first
  const max = Math.max(...bars.map((r) => r.latency_ms ?? 0), 1);
  return (
    <div
      data-testid="sparkline"
      className="mt-[18px] flex h-[30px] items-end gap-[2px]"
    >
      {bars.map((r) => (
        <span
          key={r.id}
          className={`min-w-[2px] flex-1 rounded-[1.5px] ${r.success ? "bg-up" : "bg-down"}`}
          style={{
            height:
              r.latency_ms == null
                ? 14
                : Math.round(4 + 12 * (r.latency_ms / max)),
          }}
        />
      ))}
    </div>
  );
}

export function MonitorCard({
  monitor,
  now,
  isNew = false,
}: {
  monitor: MonitorListItem;
  now: Date;
  isNew?: boolean;
}) {
  const summary = monitor.summary;
  const status = STATUS[summary?.status ?? "unknown"];
  const hasData = (summary?.checks ?? 0) > 0;

  return (
    <article className="snt-in flex flex-col rounded-[14px] border border-edge bg-white px-[18px] py-4 hover:border-faint hover:shadow-[0_4px_14px_rgba(0,0,0,0.05)]">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className={`h-2 w-2 shrink-0 rounded-full ${status.dot}`} />
            <span className="truncate text-[14.5px] font-semibold tracking-[-0.01em]">
              {monitor.name}
            </span>
            {isNew && (
              <span className="rounded-[5px] bg-accent-tint px-[5px] text-[10px] font-bold text-accent">
                NEW
              </span>
            )}
          </div>
          <div className="mt-2 flex items-center gap-2">
            <MethodChip method={monitor.method} />
            <span className="truncate font-mono text-xs text-muted">
              {stripProtocol(monitor.url)}
            </span>
          </div>
        </div>
        <span
          className={`shrink-0 rounded-[20px] px-[9px] py-[3px] text-[11px] font-semibold ${status.pill}`}
        >
          {status.label}
        </span>
      </div>
      <Sparkline monitorId={monitor.id} enabled={hasData} />
      <div className="mt-[14px] flex gap-[22px] border-t border-fill pt-[14px]">
        {hasData && summary ? (
          <>
            <div>
              <div className={`text-[15px] font-bold ${status.metric}`}>
                {formatUptime(summary.uptime_pct)}
              </div>
              <div className="text-[11px] text-muted">Uptime · 24h</div>
            </div>
            <div>
              <div className="font-mono text-[15px] font-bold text-[#3f3f46]">
                {formatLatency(summary.latency_p95_ms)}
              </div>
              <div className="text-[11px] text-muted">Latency</div>
            </div>
            <div className="ml-auto text-right">
              <div className="text-xs text-dim">
                {timeAgo(summary.last_check_at, now)}
              </div>
              <div className="text-[11px] text-muted">Last check</div>
            </div>
          </>
        ) : (
          <div className="text-xs text-muted">
            No data yet — waiting for the first check.
          </div>
        )}
      </div>
    </article>
  );
}
