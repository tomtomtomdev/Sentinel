/**
 * Live dashboard updates (S12.3): one app-wide SSE subscription that turns
 * `check_completed`/`status_changed` events into TanStack Query invalidations.
 * Both event kinds refresh the same things — the monitor list (summary cards +
 * stat strip) and every query under the touched monitor's key (detail, stats,
 * results → chart, runs table, sparkline).
 */

import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { subscribeEvents } from "./sse";

export function useLiveEvents(): void {
  const queryClient = useQueryClient();
  useEffect(
    () =>
      subscribeEvents((event) => {
        void queryClient.invalidateQueries({
          queryKey: ["monitors", { include: "summary" }],
        });
        void queryClient.invalidateQueries({
          queryKey: ["monitors", event.monitor_id],
        });
      }),
    [queryClient],
  );
}
