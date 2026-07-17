import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";

import { MethodChip, StatusPill } from "../components/MonitorCard";
import { Toast, useToast } from "../components/Toast";
import { ArrowLeftIcon } from "../components/icons";
import { api } from "../lib/api";
import { useAuthSources } from "../lib/authSources";
import { formatLatency, formatUptime, stripProtocol } from "../lib/format";
import { useMonitor, useMonitorStats } from "../lib/monitors";

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="font-mono text-[15px] font-bold text-[#3f3f46]">
        {value}
      </div>
      <div className="text-[11px] text-muted">{label}</div>
    </div>
  );
}

export function MonitorDetailPage() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { message, show } = useToast();
  const { data: monitor, isPending, isError, error } = useMonitor(id);
  const { data: stats } = useMonitorStats(id, "24h");
  const { data: sources } = useAuthSources();
  const [confirmingDelete, setConfirmingDelete] = useState(false);

  const linkAuthSource = async (authSourceId: string) => {
    try {
      await api.patch(`/monitors/${id}`, {
        auth_source_id: authSourceId === "" ? null : authSourceId,
      });
      await queryClient.invalidateQueries({ queryKey: ["monitors", id] });
      show(authSourceId === "" ? "Auth source unlinked" : "Auth source linked");
    } catch (e) {
      show(e instanceof Error ? e.message : "Could not update the monitor");
    }
  };

  const deleteMonitor = async () => {
    try {
      await api.delete(`/monitors/${id}`);
      await queryClient.invalidateQueries({ queryKey: ["monitors"] });
      navigate("/monitors", { state: { toast: "Monitor deleted" } });
    } catch (e) {
      show(e instanceof Error ? e.message : "Could not delete the monitor");
    }
  };

  return (
    <div className="mx-auto max-w-[840px] px-9 pb-16 pt-[30px]">
      <Link
        to="/monitors"
        className="flex w-fit items-center gap-[6px] text-[13px] font-medium text-dim hover:text-ink"
      >
        <ArrowLeftIcon size={15} />
        Back to monitors
      </Link>

      {isPending ? (
        <div className="mt-6 text-[13px] text-dim">Loading monitor…</div>
      ) : isError ? (
        <div className="mt-6 rounded-[14px] border border-[#fecaca] bg-down-bg px-[18px] py-10 text-center text-[13px] text-down-text">
          Could not load the monitor — {error.message}
        </div>
      ) : (
        <>
          <div className="mt-4 flex items-start justify-between gap-4">
            <div className="min-w-0">
              <div className="flex items-center gap-3">
                <h1 className="truncate text-2xl font-bold tracking-[-0.02em]">
                  {monitor.name}
                </h1>
                {stats && <StatusPill status={stats.status} />}
              </div>
              <div className="mt-2 flex items-center gap-2">
                <MethodChip method={monitor.method} />
                <span className="truncate font-mono text-xs text-muted">
                  {stripProtocol(monitor.url)}
                </span>
              </div>
            </div>
          </div>

          {stats && (
            <div className="mt-6 flex flex-wrap gap-[26px] rounded-[14px] border border-edge px-[18px] py-4">
              <Stat label="Uptime · 24h" value={formatUptime(stats.uptime_pct)} />
              <Stat label="Checks" value={String(stats.checks)} />
              <Stat label="Failures" value={String(stats.failures)} />
              <Stat label="p50" value={formatLatency(stats.latency_ms.p50)} />
              <Stat label="p95" value={formatLatency(stats.latency_ms.p95)} />
              <Stat label="p99" value={formatLatency(stats.latency_ms.p99)} />
            </div>
          )}

          <div className="mt-4 flex flex-wrap gap-[26px] rounded-[14px] border border-edge px-[18px] py-4 text-[13px]">
            <div>
              <span className="text-dim">Interval</span>{" "}
              <span className="font-semibold">{monitor.interval_seconds}s</span>
            </div>
            <div>
              <span className="text-dim">Timeout</span>{" "}
              <span className="font-semibold">{monitor.timeout_seconds}s</span>
            </div>
            <div>
              <span className="text-dim">Assertions</span>{" "}
              <span className="font-semibold">{monitor.assertions.length}</span>
            </div>
            <div>
              <span className="text-dim">Enabled</span>{" "}
              <span className="font-semibold">
                {monitor.enabled ? "yes" : "no"}
              </span>
            </div>
          </div>

          <div className="mt-4 rounded-[14px] border border-edge px-[18px] py-4">
            <label className="block max-w-[360px]">
              <span className="mb-1 block text-[13px] font-semibold">
                Auth source
              </span>
              <select
                value={monitor.auth_source_id ?? ""}
                onChange={(e) => void linkAuthSource(e.target.value)}
                className="snt-field w-full rounded-[9px] border border-hairline bg-white px-3 py-[9px] text-[13.5px]"
              >
                <option value="">None</option>
                {(sources ?? []).map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
              </select>
            </label>
            <p className="mt-2 text-xs text-muted">
              Linked monitors get the source's token injected on every check;
              Sentinel refreshes it automatically.
            </p>
          </div>

          <div className="mt-4 rounded-[14px] border border-edge px-[18px] py-10 text-center text-[13px] text-dim">
            Latency chart and recent runs land in the next slice (S12).
          </div>

          <div className="mt-6 flex justify-end gap-2">
            {confirmingDelete ? (
              <>
                <button
                  type="button"
                  onClick={() => setConfirmingDelete(false)}
                  className="rounded-[9px] border border-faint bg-white px-[14px] py-[9px] text-[13px] font-semibold hover:bg-subtle"
                >
                  Keep monitor
                </button>
                <button
                  type="button"
                  onClick={() => void deleteMonitor()}
                  className="rounded-[9px] bg-down px-[14px] py-[9px] text-[13px] font-semibold text-white hover:bg-down-text"
                >
                  Confirm delete
                </button>
              </>
            ) : (
              <button
                type="button"
                onClick={() => setConfirmingDelete(true)}
                className="rounded-[9px] border border-[#fecaca] bg-white px-[14px] py-[9px] text-[13px] font-semibold text-down-text hover:bg-down-bg"
              >
                Delete monitor
              </button>
            )}
          </div>
        </>
      )}
      <Toast message={message} />
    </div>
  );
}
