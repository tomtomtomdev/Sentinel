import { useState } from "react";
import { Link } from "react-router-dom";

import { MonitorCard } from "../components/MonitorCard";
import { PlusIcon, SearchIcon, TrendingUpIcon } from "../components/icons";
import { formatUptime } from "../lib/format";
import { useMonitors, type MonitorListItem } from "../lib/monitors";

function summarize(monitors: MonitorListItem[]) {
  const byStatus = { up: 0, down: 0, unknown: 0 };
  const uptimes: number[] = [];
  for (const m of monitors) {
    const summary = m.summary;
    byStatus[summary?.status ?? "unknown"] += 1;
    if (summary && summary.checks > 0) {
      uptimes.push(summary.uptime_pct);
    }
  }
  const avgUptime =
    uptimes.length === 0
      ? null
      : uptimes.reduce((a, b) => a + b, 0) / uptimes.length;
  return { byStatus, avgUptime };
}

function StatCard({
  label,
  value,
  marker,
}: {
  label: string;
  value: string;
  marker: React.ReactNode;
}) {
  return (
    <li className="rounded-xl border border-edge bg-white px-[18px] py-4">
      <div className="flex items-center gap-2 text-[12.5px] font-medium text-dim">
        {marker}
        <span data-testid="stat-label">{label}</span>
      </div>
      <div
        data-testid="stat-value"
        className="mt-1 text-[30px] font-bold tracking-[-0.02em]"
      >
        {value}
      </div>
    </li>
  );
}

function dot(color: string) {
  return <span className={`h-2 w-2 rounded-full ${color}`} />;
}

export function DashboardPage() {
  const { data: monitors, isPending, isError, error } = useMonitors();
  const [query, setQuery] = useState("");
  const now = new Date();

  const filtered = (monitors ?? []).filter((m) => {
    const q = query.trim().toLowerCase();
    return (
      q === "" ||
      m.name.toLowerCase().includes(q) ||
      m.url.toLowerCase().includes(q)
    );
  });
  const { byStatus, avgUptime } = summarize(monitors ?? []);

  return (
    <div className="mx-auto max-w-[1080px] px-9 pb-16 pt-[30px]">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-[-0.02em]">Monitors</h1>
          <div className="mt-2 flex items-center gap-2 text-[13px] text-dim">
            <span className="snt-pulse h-[7px] w-[7px] rounded-full bg-up" />
            Live · checking every 30s
          </div>
        </div>
        <div className="flex items-center gap-3">
          <label className="flex w-[240px] items-center gap-2 rounded-[9px] border border-edge bg-fill px-3 py-2">
            <SearchIcon size={15} className="shrink-0 text-muted" />
            <input
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search monitors"
              className="w-full bg-transparent text-[13px] outline-none placeholder:text-muted"
            />
          </label>
          <Link
            to="/monitors/new"
            className="flex items-center gap-[6px] rounded-[9px] bg-ink px-[14px] py-[9px] text-[13px] font-semibold text-white shadow-[0_1px_2px_rgba(0,0,0,0.12)] hover:bg-black"
          >
            <PlusIcon size={15} />
            Add monitor
          </Link>
        </div>
      </div>

      {isPending ? (
        <div className="mt-6 rounded-[14px] border border-edge px-[18px] py-10 text-center text-[13px] text-dim">
          Loading monitors…
        </div>
      ) : isError ? (
        <div className="mt-6 rounded-[14px] border border-[#fecaca] bg-down-bg px-[18px] py-10 text-center text-[13px] text-down-text">
          Could not load monitors — {error.message}
        </div>
      ) : (
        <>
          <ul
            aria-label="Summary"
            className="mb-[22px] mt-6 grid grid-cols-2 gap-[14px] lg:grid-cols-4"
          >
            <StatCard
              label="Operational"
              value={String(byStatus.up)}
              marker={dot("bg-up")}
            />
            <StatCard
              label="Unknown"
              value={String(byStatus.unknown)}
              marker={dot("bg-degraded")}
            />
            <StatCard
              label="Down"
              value={String(byStatus.down)}
              marker={dot("bg-down")}
            />
            <StatCard
              label="Avg uptime · 24h"
              value={avgUptime === null ? "—" : formatUptime(avgUptime)}
              marker={<TrendingUpIcon size={15} className="text-accent" />}
            />
          </ul>

          {monitors !== undefined && monitors.length === 0 ? (
            <div className="rounded-[14px] border border-edge px-[18px] py-12 text-center">
              <p className="text-[14px] font-semibold">No monitors yet</p>
              <p className="mt-1 text-[13px] text-dim">
                Add your first endpoint and Sentinel starts watching it
                immediately.
              </p>
              <Link
                to="/monitors/new"
                className="mt-4 inline-flex items-center gap-[6px] rounded-[9px] bg-ink px-[14px] py-[9px] text-[13px] font-semibold text-white hover:bg-black"
              >
                <PlusIcon size={15} />
                Add monitor
              </Link>
            </div>
          ) : (
            <div className="grid grid-cols-[repeat(auto-fill,minmax(300px,1fr))] gap-[14px]">
              {filtered.map((m) => (
                <MonitorCard key={m.id} monitor={m} now={now} />
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}
