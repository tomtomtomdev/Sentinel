import {
  buildAssertions,
  INTERVAL_OPTIONS,
  intervalToSeconds,
} from "../src/lib/rules";

describe("intervalToSeconds", () => {
  it("maps the design's interval values to seconds", () => {
    expect(intervalToSeconds("30s")).toBe(30);
    expect(intervalToSeconds("1m")).toBe(60);
    expect(intervalToSeconds("5m")).toBe(300);
    expect(intervalToSeconds("10m")).toBe(600);
    expect(intervalToSeconds("30m")).toBe(1800);
  });

  it("offers exactly the design's five options", () => {
    expect(INTERVAL_OPTIONS.map((o) => o.value)).toEqual([
      "30s",
      "1m",
      "5m",
      "10m",
      "30m",
    ]);
  });
});

describe("buildAssertions", () => {
  it("turns the expected status into a status_code equals assertion", () => {
    expect(buildAssertions("200", [])).toEqual([
      { type: "status_code", params: { equals: 200 } },
    ]);
  });

  it("maps every assertion row type to the backend format", () => {
    const rows = [
      { type: "body_contains" as const, value: "ok" },
      { type: "json_path_equals" as const, path: "$.status", value: "ok" },
      { type: "status_code" as const, value: "204" },
      { type: "max_latency_ms" as const, value: "800" },
    ];
    expect(buildAssertions("", rows)).toEqual([
      { type: "body_contains", params: { text: "ok" } },
      { type: "json_path_equals", params: { path: "$.status", value: "ok" } },
      { type: "status_code", params: { equals: 204 } },
      { type: "max_latency_ms", params: { value: 800 } },
    ]);
  });

  it("skips blank rows and a blank expected status", () => {
    const rows = [
      { type: "body_contains" as const, value: "  " },
      { type: "max_latency_ms" as const, value: "" },
    ];
    expect(buildAssertions("", rows)).toEqual([]);
  });
});
