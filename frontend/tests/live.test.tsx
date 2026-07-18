import { render } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { useLiveEvents } from "../src/lib/live";
import { subscribeEvents, type LiveEvent } from "../src/lib/sse";

vi.mock("../src/lib/sse", () => ({ subscribeEvents: vi.fn() }));

const mockedSubscribe = vi.mocked(subscribeEvents);

function Host() {
  useLiveEvents();
  return null;
}

function renderHost() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const invalidate = vi.spyOn(queryClient, "invalidateQueries");
  const unsubscribe = vi.fn();
  let handler: (event: LiveEvent) => void = () => {};
  mockedSubscribe.mockImplementation((onEvent) => {
    handler = onEvent;
    return unsubscribe;
  });
  const view = render(
    <QueryClientProvider client={queryClient}>
      <Host />
    </QueryClientProvider>,
  );
  return { view, invalidate, unsubscribe, fire: (e: LiveEvent) => handler(e) };
}

describe("useLiveEvents", () => {
  it("invalidates the list and the touched monitor on check_completed", () => {
    const { invalidate, fire } = renderHost();

    fire({
      type: "check_completed",
      monitor_id: "m1",
      success: false,
      status_code: null,
      latency_ms: null,
      error: "timeout",
      at: "2026-07-18T09:00:00Z",
    });

    expect(invalidate).toHaveBeenCalledWith({
      queryKey: ["monitors", { include: "summary" }],
    });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["monitors", "m1"] });
  });

  it("invalidates the same keys on status_changed", () => {
    const { invalidate, fire } = renderHost();

    fire({
      type: "status_changed",
      monitor_id: "m2",
      from: "up",
      to: "down",
      at: "2026-07-18T09:01:00Z",
    });

    expect(invalidate).toHaveBeenCalledWith({
      queryKey: ["monitors", { include: "summary" }],
    });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["monitors", "m2"] });
  });

  it("unsubscribes on unmount", () => {
    const { view, unsubscribe } = renderHost();
    view.unmount();
    expect(unsubscribe).toHaveBeenCalledTimes(1);
  });
});
