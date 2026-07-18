import { AUTH_TOKEN_STORAGE_KEY } from "../src/lib/config";
import {
  createSseParser,
  subscribeEvents,
  type LiveEvent,
} from "../src/lib/sse";

/** A ReadableStream we can push SSE text into from the test. */
function scriptedStream() {
  let controller!: ReadableStreamDefaultController<Uint8Array>;
  const stream = new ReadableStream<Uint8Array>({
    start(c) {
      controller = c;
    },
  });
  const encoder = new TextEncoder();
  return {
    stream,
    push: (text: string) => controller.enqueue(encoder.encode(text)),
    close: () => controller.close(),
  };
}

const CHECK_FRAME =
  "event: check_completed\n" +
  'data: {"monitor_id":"m1","success":true,"status_code":200,"latency_ms":42,"error":null,"at":"2026-07-18T09:00:00Z"}\n\n';

describe("createSseParser", () => {
  it("parses a complete frame into event name + data", () => {
    const parser = createSseParser();
    expect(parser.push('event: status_changed\ndata: {"x":1}\n\n')).toEqual([
      { event: "status_changed", data: '{"x":1}' },
    ]);
  });

  it("buffers a frame split across chunks", () => {
    const parser = createSseParser();
    expect(parser.push("event: check_comp")).toEqual([]);
    expect(parser.push('leted\ndata: {"x":1}\n')).toEqual([]);
    expect(parser.push("\n")).toEqual([
      { event: "check_completed", data: '{"x":1}' },
    ]);
  });

  it("parses multiple frames from one chunk", () => {
    const parser = createSseParser();
    const frames = parser.push(
      'event: a\ndata: {"n":1}\n\nevent: b\ndata: {"n":2}\n\n',
    );
    expect(frames).toEqual([
      { event: "a", data: '{"n":1}' },
      { event: "b", data: '{"n":2}' },
    ]);
  });
});

describe("subscribeEvents", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    localStorage.clear();
  });

  it("connects with the Bearer header and dispatches typed events", async () => {
    localStorage.setItem(AUTH_TOKEN_STORAGE_KEY, "tok-123");
    const { stream, push } = scriptedStream();
    const fetchMock = vi
      .fn()
      .mockResolvedValue(new Response(stream, { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    const events: LiveEvent[] = [];
    const unsubscribe = subscribeEvents((e) => events.push(e));
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));

    const [url, init] = fetchMock.mock.calls[0] as [URL, RequestInit];
    expect(String(url)).toContain("/api/v1/events");
    const headers = new Headers(init.headers);
    expect(headers.get("Authorization")).toBe("Bearer tok-123");
    expect(headers.get("Accept")).toBe("text/event-stream");

    push(CHECK_FRAME);
    push(
      "event: status_changed\n" +
        'data: {"monitor_id":"m2","from":"up","to":"down","at":"2026-07-18T09:01:00Z"}\n\n',
    );
    await vi.waitFor(() => expect(events).toHaveLength(2));
    expect(events[0]).toEqual({
      type: "check_completed",
      monitor_id: "m1",
      success: true,
      status_code: 200,
      latency_ms: 42,
      error: null,
      at: "2026-07-18T09:00:00Z",
    });
    expect(events[1]).toEqual({
      type: "status_changed",
      monitor_id: "m2",
      from: "up",
      to: "down",
      at: "2026-07-18T09:01:00Z",
    });
    unsubscribe();
  });

  it("ignores unknown event names and malformed data without crashing", async () => {
    const { stream, push } = scriptedStream();
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(stream, { status: 200 })),
    );

    const events: LiveEvent[] = [];
    const unsubscribe = subscribeEvents((e) => events.push(e));
    push("event: mystery\ndata: {}\n\n");
    push("event: check_completed\ndata: not-json\n\n");
    push(CHECK_FRAME);
    await vi.waitFor(() => expect(events).toHaveLength(1));
    expect(events[0].type).toBe("check_completed");
    unsubscribe();
  });

  it("reconnects after the stream ends", async () => {
    const first = scriptedStream();
    const second = scriptedStream();
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response(first.stream, { status: 200 }))
      .mockResolvedValueOnce(new Response(second.stream, { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    const events: LiveEvent[] = [];
    const unsubscribe = subscribeEvents((e) => events.push(e), { retryMs: 1 });
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    first.close();
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));

    second.push(CHECK_FRAME);
    await vi.waitFor(() => expect(events).toHaveLength(1));
    unsubscribe();
  });

  it("stops for good once unsubscribed", async () => {
    const { stream, close } = scriptedStream();
    const fetchMock = vi
      .fn()
      .mockResolvedValue(new Response(stream, { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    const unsubscribe = subscribeEvents(() => {}, { retryMs: 1 });
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    unsubscribe();
    close();
    await new Promise((r) => setTimeout(r, 30));
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
