/**
 * Fetch-based SSE reader for `GET /api/v1/events` (S12.3, SPEC §3.6).
 *
 * `EventSource` cannot send an `Authorization` header, and putting the S9a
 * token in a query string would leak it into access logs — so the stream is
 * read with `fetch` + incremental parsing instead, carrying the same Bearer
 * header as every other API call (PLAN D33). Reconnects with doubling backoff
 * until unsubscribed.
 */

import { API_BASE_URL, getAuthToken } from "./config";

export type LiveEvent =
  | {
      type: "check_completed";
      monitor_id: string;
      success: boolean;
      status_code: number | null;
      latency_ms: number | null;
      error: string | null;
      at: string;
    }
  | {
      type: "status_changed";
      monitor_id: string;
      from: string;
      to: string;
      at: string;
    };

export interface SseFrame {
  event: string;
  data: string;
}

/** Minimal incremental SSE parser: `event:`/`data:` lines, frames terminated
 * by a blank line (the only shape the backend emits — `events.py`). */
export function createSseParser(): { push: (chunk: string) => SseFrame[] } {
  let buffer = "";
  return {
    push(chunk: string): SseFrame[] {
      buffer += chunk;
      const frames: SseFrame[] = [];
      for (;;) {
        const boundary = buffer.indexOf("\n\n");
        if (boundary === -1) {
          return frames;
        }
        const raw = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        let event = "";
        const data: string[] = [];
        for (const line of raw.split("\n")) {
          if (line.startsWith("event:")) {
            event = line.slice(6).trim();
          } else if (line.startsWith("data:")) {
            data.push(line.slice(5).trim());
          }
        }
        if (event) {
          frames.push({ event, data: data.join("\n") });
        }
      }
    },
  };
}

function toLiveEvent(frame: SseFrame): LiveEvent | null {
  if (frame.event !== "check_completed" && frame.event !== "status_changed") {
    return null;
  }
  try {
    const payload = JSON.parse(frame.data) as Record<string, unknown>;
    if (typeof payload.monitor_id !== "string") {
      return null;
    }
    return { type: frame.event, ...payload } as LiveEvent;
  } catch {
    return null;
  }
}

async function readStream(
  onEvent: (event: LiveEvent) => void,
  signal: AbortSignal,
): Promise<void> {
  const headers = new Headers({ Accept: "text/event-stream" });
  const token = getAuthToken();
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  const url = new URL(`${API_BASE_URL}/events`, window.location.origin);
  const response = await fetch(url, { headers, signal });
  if (!response.ok || response.body === null) {
    throw new Error(`events stream failed with HTTP ${response.status}`);
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  const parser = createSseParser();
  for (;;) {
    const { done, value } = await reader.read();
    if (done) {
      return; // server closed — caller reconnects
    }
    for (const frame of parser.push(decoder.decode(value, { stream: true }))) {
      const event = toLiveEvent(frame);
      if (event !== null) {
        onEvent(event);
      }
    }
  }
}

function delay(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    const timer = setTimeout(done, ms);
    signal.addEventListener("abort", done, { once: true });
    function done() {
      clearTimeout(timer);
      signal.removeEventListener("abort", done);
      resolve();
    }
  });
}

const MAX_RETRY_MS = 30_000;

/** Open the live event stream; returns an unsubscribe function. The loop
 * never throws — every failure waits out the backoff and reconnects. */
export function subscribeEvents(
  onEvent: (event: LiveEvent) => void,
  { retryMs = 3_000 }: { retryMs?: number } = {},
): () => void {
  const controller = new AbortController();
  const run = async (): Promise<void> => {
    let backoffMs = retryMs;
    while (!controller.signal.aborted) {
      try {
        await readStream(onEvent, controller.signal);
        backoffMs = retryMs; // had a healthy connection — reset the backoff
      } catch {
        // connection refused / non-2xx / aborted mid-read — fall through
      }
      if (controller.signal.aborted) {
        return;
      }
      await delay(backoffMs, controller.signal);
      backoffMs = Math.min(backoffMs * 2, MAX_RETRY_MS);
    }
  };
  void run();
  return () => controller.abort();
}
