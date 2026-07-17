import {
  formatLatency,
  formatUptime,
  stripProtocol,
  timeAgo,
} from "../src/lib/format";

describe("stripProtocol", () => {
  it("removes the scheme for card display (design: protocol stripped)", () => {
    expect(stripProtocol("https://api.stripe.com/v1/checkout")).toBe(
      "api.stripe.com/v1/checkout",
    );
    expect(stripProtocol("http://x.dev/y")).toBe("x.dev/y");
  });
});

describe("formatUptime", () => {
  it("shows whole percentages without decimals and others with 2dp", () => {
    expect(formatUptime(100)).toBe("100%");
    expect(formatUptime(99.79)).toBe("99.79%");
    expect(formatUptime(0)).toBe("0%");
  });
});

describe("formatLatency", () => {
  it("renders ms values and an em dash when absent", () => {
    expect(formatLatency(142)).toBe("142ms");
    expect(formatLatency(null)).toBe("—");
  });
});

describe("timeAgo", () => {
  const now = new Date("2026-07-17T12:00:00Z");

  it("renders seconds, minutes, hours, days and 'just now'", () => {
    expect(timeAgo(new Date("2026-07-17T11:59:58Z"), now)).toBe("just now");
    expect(timeAgo(new Date("2026-07-17T11:59:15Z"), now)).toBe("45s ago");
    expect(timeAgo(new Date("2026-07-17T11:53:00Z"), now)).toBe("7m ago");
    expect(timeAgo(new Date("2026-07-17T09:00:00Z"), now)).toBe("3h ago");
    expect(timeAgo(new Date("2026-07-15T12:00:00Z"), now)).toBe("2d ago");
  });

  it("renders an em dash for a missing timestamp", () => {
    expect(timeAgo(null, now)).toBe("—");
  });
});
