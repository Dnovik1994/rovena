import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  computeBackoff,
  connectStatusSocket,
  type StatusMessage,
  type StatusSocketHandle,
} from "../websocket";

/* ══════════════════════════════════════════════════════════════
 *  Fake WebSocket — replaces global WebSocket for all tests.
 * ══════════════════════════════════════════════════════════════ */

let wsInstances: FakeWebSocket[] = [];

class FakeWebSocket {
  /* Static constants required by the WS spec */
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSING = 2;
  static readonly CLOSED = 3;

  /* Instance mirrors (code under test reads ws.readyState vs WebSocket.OPEN) */
  readonly CONNECTING = 0;
  readonly OPEN = 1;
  readonly CLOSING = 2;
  readonly CLOSED = 3;

  readyState = FakeWebSocket.CONNECTING;
  url: string;

  onopen: ((ev: Event) => void) | null = null;
  onclose: ((ev: CloseEvent) => void) | null = null;
  onmessage: ((ev: MessageEvent) => void) | null = null;
  onerror: ((ev: Event) => void) | null = null;

  send = vi.fn();
  close = vi.fn((_code?: number, _reason?: string) => {
    this.readyState = FakeWebSocket.CLOSED;
  });

  constructor(url: string) {
    this.url = url;
    wsInstances.push(this);
  }

  /* ── Test helpers ── */

  simulateOpen() {
    this.readyState = FakeWebSocket.OPEN;
    this.onopen?.(new Event("open"));
  }

  simulateMessage(data: string) {
    this.onmessage?.(new MessageEvent("message", { data }));
  }

  simulateClose(code = 1006, reason = "") {
    this.readyState = FakeWebSocket.CLOSED;
    this.onclose?.(new CloseEvent("close", { code, reason }));
  }
}

vi.stubGlobal("WebSocket", FakeWebSocket);

/* ── Helpers ── */

function latestWs(): FakeWebSocket {
  return wsInstances[wsInstances.length - 1];
}

/* ══════════════════════════════════════════════════════════════
 *  Setup / Teardown
 * ══════════════════════════════════════════════════════════════ */

let handle: StatusSocketHandle | null = null;

beforeEach(() => {
  wsInstances = [];
  vi.useFakeTimers();
});

afterEach(() => {
  handle?.dispose();
  handle = null;
  vi.useRealTimers();
  vi.restoreAllMocks();
});

/* ══════════════════════════════════════════════════════════════
 *  1. computeBackoff — pure function tests
 * ══════════════════════════════════════════════════════════════ */

describe("computeBackoff", () => {
  it("returns a non-negative number for any attempt", () => {
    for (let i = 0; i < 20; i++) {
      expect(computeBackoff(i)).toBeGreaterThanOrEqual(0);
    }
  });

  it("grows exponentially when jitter is neutral", () => {
    vi.spyOn(Math, "random").mockReturnValue(0.5); // jitter term = 0
    expect(computeBackoff(0)).toBe(250);
    expect(computeBackoff(1)).toBe(500);
    expect(computeBackoff(2)).toBe(1000);
    expect(computeBackoff(3)).toBe(2000);
    expect(computeBackoff(4)).toBe(4000);
  });

  it("caps at MAX_DELAY (30 000 ms)", () => {
    vi.spyOn(Math, "random").mockReturnValue(0.5);
    expect(computeBackoff(50)).toBe(30_000);
    expect(computeBackoff(100)).toBe(30_000);
  });

  it("applies ±30 % jitter around the base", () => {
    // random()=0  → jitter = base * 0.3 * (0*2-1) = -0.3·base  → 0.7·base
    vi.spyOn(Math, "random").mockReturnValue(0);
    expect(computeBackoff(0)).toBe(Math.round(250 * 0.7)); // 175

    // random()=1  → jitter = base * 0.3 * (1*2-1) = +0.3·base → 1.3·base
    vi.mocked(Math.random).mockReturnValue(1);
    expect(computeBackoff(0)).toBe(Math.round(250 * 1.3)); // 325
  });
});

/* ══════════════════════════════════════════════════════════════
 *  2. connectStatusSocket — integration tests
 * ══════════════════════════════════════════════════════════════ */

describe("connectStatusSocket", () => {
  let onMessage: ReturnType<typeof vi.fn>;
  let onStateChange: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    onMessage = vi.fn();
    onStateChange = vi.fn();
  });

  /* ── Connection + onopen ── */

  it("transitions to 'connected' and sends auth token on open", () => {
    handle = connectStatusSocket("tok-123", onMessage, onStateChange);

    expect(onStateChange).toHaveBeenCalledWith("connecting");
    expect(wsInstances).toHaveLength(1);

    latestWs().simulateOpen();

    expect(onStateChange).toHaveBeenCalledWith("connected");
    expect(handle.state).toBe("connected");
    expect(latestWs().send).toHaveBeenCalledWith(
      JSON.stringify({ type: "auth", token: "tok-123" }),
    );
  });

  /* ── onmessage handler ── */

  it("delivers parsed messages to onMessage callback", () => {
    handle = connectStatusSocket("tok", onMessage, onStateChange);
    latestWs().simulateOpen();

    const msg: StatusMessage = {
      type: "account_update",
      account_id: 42,
      status: "active",
    };
    latestWs().simulateMessage(JSON.stringify(msg));

    expect(onMessage).toHaveBeenCalledWith(msg);
  });

  it("responds to 'ping' with 'pong' and does NOT forward to onMessage", () => {
    handle = connectStatusSocket("tok", onMessage, onStateChange);
    latestWs().simulateOpen();

    latestWs().simulateMessage(JSON.stringify({ type: "ping" }));

    // pong sent (second call — first was auth)
    expect(latestWs().send).toHaveBeenCalledWith("pong");
    // ping NOT forwarded
    expect(onMessage).not.toHaveBeenCalled();
  });

  it("ignores malformed JSON without crashing", () => {
    handle = connectStatusSocket("tok", onMessage, onStateChange);
    latestWs().simulateOpen();

    expect(() => latestWs().simulateMessage("not json{")).not.toThrow();
    expect(onMessage).not.toHaveBeenCalled();
  });

  /* ── Reconnect on unclean disconnect ── */

  it("reconnects after unclean close (code 1006)", () => {
    vi.spyOn(Math, "random").mockReturnValue(0.5);

    handle = connectStatusSocket("tok", onMessage, onStateChange);
    latestWs().simulateOpen();

    const countBefore = wsInstances.length;
    latestWs().simulateClose(1006, "abnormal");

    expect(onStateChange).toHaveBeenCalledWith("disconnected");

    // Backoff for attempt 0 with neutral jitter = 250 ms
    vi.advanceTimersByTime(250);
    expect(wsInstances).toHaveLength(countBefore + 1);
    expect(onStateChange).toHaveBeenLastCalledWith("connecting");
  });

  /* ── Clean close via dispose() — NO reconnect ── */

  it("does NOT reconnect after dispose()", () => {
    handle = connectStatusSocket("tok", onMessage, onStateChange);
    latestWs().simulateOpen();

    const countBefore = wsInstances.length;
    handle.dispose();

    vi.advanceTimersByTime(60_000);
    expect(wsInstances).toHaveLength(countBefore);
    expect(handle.state).toBe("disconnected");
  });

  /* ── Auth failure (1008) — NO reconnect ── */

  it("does NOT reconnect on auth failure (code 1008)", () => {
    handle = connectStatusSocket("tok", onMessage, onStateChange);
    latestWs().simulateOpen();

    const countBefore = wsInstances.length;
    latestWs().simulateClose(1008, "policy violation");

    expect(onStateChange).toHaveBeenCalledWith("auth_failed");
    expect(handle.state).toBe("auth_failed");

    vi.advanceTimersByTime(60_000);
    expect(wsInstances).toHaveLength(countBefore);
  });

  /* ── Backoff grows exponentially ── */

  it("backoff delays grow exponentially across reconnect attempts", () => {
    vi.spyOn(Math, "random").mockReturnValue(0.5);

    handle = connectStatusSocket("tok", onMessage, onStateChange);

    // attempt 0 → open then close → backoff = 250ms
    latestWs().simulateOpen();
    latestWs().simulateClose(1006);

    vi.advanceTimersByTime(200);
    expect(wsInstances).toHaveLength(1); // not yet
    vi.advanceTimersByTime(50); // total 250ms
    expect(wsInstances).toHaveLength(2); // reconnected

    // attempt 1 (no open → attempt NOT reset) → backoff = 500ms
    latestWs().simulateClose(1006);

    vi.advanceTimersByTime(499);
    expect(wsInstances).toHaveLength(2);
    vi.advanceTimersByTime(1); // total 500ms
    expect(wsInstances).toHaveLength(3);

    // attempt 2 → backoff = 1000ms
    latestWs().simulateClose(1006);

    vi.advanceTimersByTime(999);
    expect(wsInstances).toHaveLength(3);
    vi.advanceTimersByTime(1); // total 1000ms
    expect(wsInstances).toHaveLength(4);
  });

  /* ── Attempt counter resets on successful open ── */

  it("resets attempt counter after successful reconnect", () => {
    vi.spyOn(Math, "random").mockReturnValue(0.5);

    handle = connectStatusSocket("tok", onMessage, onStateChange);
    latestWs().simulateOpen();

    // Close → attempt 0 → delay 250ms
    latestWs().simulateClose(1006);
    vi.advanceTimersByTime(250);
    expect(wsInstances).toHaveLength(2);

    // Close without open → attempt 1 → delay 500ms
    latestWs().simulateClose(1006);
    vi.advanceTimersByTime(500);
    expect(wsInstances).toHaveLength(3);

    // Now OPEN successfully → attempt resets to 0
    latestWs().simulateOpen();
    latestWs().simulateClose(1006);

    // Should be back to 250ms, NOT 1000ms
    vi.advanceTimersByTime(250);
    expect(wsInstances).toHaveLength(4);
  });

  /* ── Max retries: current implementation retries indefinitely ── */

  it("retries indefinitely — no max-retries cap (documents current behaviour)", () => {
    vi.spyOn(Math, "random").mockReturnValue(0.5);

    handle = connectStatusSocket("tok", onMessage, onStateChange);

    for (let i = 0; i < 15; i++) {
      latestWs().simulateClose(1006);
      // MAX_DELAY_MS = 30s is always enough
      vi.advanceTimersByTime(31_000);
    }

    // 1 initial + 15 reconnects = 16
    expect(wsInstances).toHaveLength(16);
  });

  /* ── Singleton guard ── */

  it("singleton guard: new connection disposes the previous one", () => {
    const handle1 = connectStatusSocket("tok-1", onMessage, onStateChange);
    const ws1 = latestWs();
    ws1.simulateOpen();

    handle = connectStatusSocket("tok-2", onMessage, onStateChange);

    expect(ws1.close).toHaveBeenCalled();
    expect(handle1.state).toBe("disconnected");
    expect(wsInstances).toHaveLength(2);
  });
});
