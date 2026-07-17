/**
 * The shared "Monitoring rules" block state and its mapping to the backend's
 * assertion format (SPEC §5: `assertions: [{type, params}]`; type names from
 * `domain/logic/assertions.py`).
 */

export type IntervalValue = "30s" | "1m" | "5m" | "10m" | "30m";

export const INTERVAL_OPTIONS: { value: IntervalValue; label: string }[] = [
  { value: "30s", label: "Every 30 seconds" },
  { value: "1m", label: "Every 1 minute" },
  { value: "5m", label: "Every 5 minutes" },
  { value: "10m", label: "Every 10 minutes" },
  { value: "30m", label: "Every 30 minutes" },
];

const INTERVAL_SECONDS: Record<IntervalValue, number> = {
  "30s": 30,
  "1m": 60,
  "5m": 300,
  "10m": 600,
  "30m": 1800,
};

export function intervalToSeconds(value: IntervalValue): number {
  return INTERVAL_SECONDS[value];
}

export type AssertionRowType =
  | "body_contains"
  | "json_path_equals"
  | "status_code"
  | "max_latency_ms";

export const ASSERTION_TYPE_OPTIONS: { value: AssertionRowType; label: string }[] =
  [
    { value: "body_contains", label: "Body contains" },
    { value: "json_path_equals", label: "JSON path equals" },
    { value: "status_code", label: "Status code equals" },
    { value: "max_latency_ms", label: "Response time under (ms)" },
  ];

export interface AssertionRow {
  type: AssertionRowType;
  value: string;
  /** Only for json_path_equals — the design's single value field can't carry
   * both the path and the expected value, so the row grows a path input. */
  path?: string;
}

export interface AssertionPayload {
  type: string;
  params: Record<string, unknown>;
}

function rowToPayload(row: AssertionRow): AssertionPayload | null {
  const value = row.value.trim();
  if (value === "") {
    return null;
  }
  switch (row.type) {
    case "body_contains":
      return { type: "body_contains", params: { text: value } };
    case "json_path_equals": {
      const path = row.path?.trim() ?? "";
      if (path === "") {
        return null;
      }
      return { type: "json_path_equals", params: { path, value } };
    }
    case "status_code":
      return { type: "status_code", params: { equals: Number(value) } };
    case "max_latency_ms":
      return { type: "max_latency_ms", params: { value: Number(value) } };
  }
}

export function buildAssertions(
  expectedStatus: string,
  rows: AssertionRow[],
): AssertionPayload[] {
  const assertions: AssertionPayload[] = [];
  const status = expectedStatus.trim();
  if (status !== "") {
    assertions.push({ type: "status_code", params: { equals: Number(status) } });
  }
  for (const row of rows) {
    const payload = rowToPayload(row);
    if (payload !== null) {
      assertions.push(payload);
    }
  }
  return assertions;
}
