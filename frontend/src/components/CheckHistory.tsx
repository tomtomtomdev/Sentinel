/**
 * Detail-page check history (S12.1): a Recharts latency line over the recent
 * results plus a newest-first runs table. One `useMonitorResults` fetch feeds
 * both. No detail-page mockup exists in `docs/design/` — styling follows the
 * established card/token conventions.
 */

import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { formatLatency } from "../lib/format";
import { useMonitorResults, type CheckResult } from "../lib/monitors";

const RESULTS_LIMIT = 50;

function clockTime(iso: string): string {
  return new Date(iso).toLocaleTimeString(undefined, { hour12: false });
}

function ResultPill({ success }: { success: boolean }) {
  return (
    <span
      className={`rounded-[20px] px-[9px] py-[2px] text-[11px] font-semibold ${
        success ? "bg-up-bg text-up-text" : "bg-down-bg text-down-text"
      }`}
    >
      {success ? "OK" : "Failed"}
    </span>
  );
}

function LatencyChart({ results }: { results: CheckResult[] }) {
  // API returns newest-first; the chart reads left→right oldest→newest.
  const points = [...results].reverse().map((r) => ({
    time: clockTime(r.finished_at),
    latency: r.latency_ms,
  }));
  return (
    <div
      data-testid="latency-chart"
      className="mt-4 rounded-[14px] border border-edge px-[18px] py-4"
    >
      <h2 className="text-[13px] font-semibold">Latency</h2>
      <div className="mt-3">
        <ResponsiveContainer width="100%" height={170}>
          <LineChart data={points} margin={{ top: 4, right: 8, bottom: 0, left: -12 }}>
            <CartesianGrid stroke="#ededed" vertical={false} />
            <XAxis
              dataKey="time"
              tick={{ fontSize: 10, fill: "#a1a1aa" }}
              tickLine={false}
              axisLine={{ stroke: "#e4e4e7" }}
              minTickGap={40}
            />
            <YAxis
              tick={{ fontSize: 10, fill: "#a1a1aa" }}
              tickLine={false}
              axisLine={false}
              unit="ms"
              width={58}
            />
            <Tooltip
              formatter={(value) => [formatLatency(value as number), "Latency"]}
              contentStyle={{ fontSize: 12, borderRadius: 9 }}
            />
            <Line
              dataKey="latency"
              stroke="#4f46e5"
              strokeWidth={1.5}
              dot={false}
              connectNulls={false}
              isAnimationActive={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

function RunsTable({ results }: { results: CheckResult[] }) {
  return (
    <div className="mt-4 rounded-[14px] border border-edge px-[18px] py-4">
      <h2 className="text-[13px] font-semibold">Recent runs</h2>
      <div className="mt-2 overflow-x-auto">
        <table aria-label="Recent runs" className="w-full text-[12.5px]">
          <thead>
            <tr className="text-left text-[11px] text-muted">
              <th className="py-[6px] pr-4 font-medium">Time</th>
              <th className="py-[6px] pr-4 font-medium">Result</th>
              <th className="py-[6px] pr-4 font-medium">Status</th>
              <th className="py-[6px] pr-4 font-medium">Latency</th>
              <th className="py-[6px] font-medium">Error</th>
            </tr>
          </thead>
          <tbody>
            {results.map((r) => (
              <tr key={r.id} className="border-t border-fill">
                <td className="py-[7px] pr-4 font-mono text-dim">
                  {clockTime(r.finished_at)}
                </td>
                <td className="py-[7px] pr-4">
                  <ResultPill success={r.success} />
                </td>
                <td className="py-[7px] pr-4 font-mono">
                  {r.status_code ?? "—"}
                </td>
                <td className="py-[7px] pr-4 font-mono">
                  {formatLatency(r.latency_ms)}
                </td>
                <td className="py-[7px] font-mono text-down-text">
                  {r.error ?? ""}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function CheckHistoryPanel({ monitorId }: { monitorId: string }) {
  const { data: results, isPending, isError } = useMonitorResults(
    monitorId,
    RESULTS_LIMIT,
  );

  if (isPending) {
    return (
      <div className="mt-4 rounded-[14px] border border-edge px-[18px] py-10 text-center text-[13px] text-dim">
        Loading check history…
      </div>
    );
  }
  if (isError) {
    return (
      <div className="mt-4 rounded-[14px] border border-[#fecaca] bg-down-bg px-[18px] py-10 text-center text-[13px] text-down-text">
        Could not load check history.
      </div>
    );
  }
  if (results.length === 0) {
    return (
      <div className="mt-4 rounded-[14px] border border-edge px-[18px] py-10 text-center text-[13px] text-dim">
        No checks recorded yet — history appears after the first run.
      </div>
    );
  }
  return (
    <>
      <LatencyChart results={results} />
      <RunsTable results={results} />
    </>
  );
}
