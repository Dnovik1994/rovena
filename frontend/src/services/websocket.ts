/* ──────────────────────────────────────────────────────────────
 *  Reliable WebSocket client for /ws/status.
 *
 *  Protocol (server-side, see backend/app/main.py):
 *    1. Client opens ws://.../ws/status
 *    2. Client sends first-message JSON: {type:"auth", token}
 *    3. Server validates token (JWT + DB user active check).
 *       - OK  → registers connection, starts 30 s ping loop.
 *       - Fail → closes with code 1008.
 *    4. Server sends {type:"ping"} every 30 s; client replies "pong".
 *    5. Server pushes StatusMessage payloads at any time.
 *
 *  Client features:
 *    - Exponential backoff (250 ms → 30 s cap) with ±30% jitter.
 *    - Auth failure (close code 1008) stops retrying → state "auth_failed".
 *    - Singleton guard: one active socket at a time.
 *    - Ping watchdog: 45 s silence → force reconnect.
 *    - 5 connection states exposed via onStateChange callback.
 *    - Safe dispose() for React useEffect cleanup.
 * ────────────────────────────────────────────────────────────── */

// ── Message types from the server ─────────────────────────────

export type StatusMessage =
  | {
      type: "account_update";
      account_id: number;
      status: string;
      actions_completed?: number;
      target_actions?: number;
      cooldown_until?: string | null;
    }
  | { type: "ping" }
  | { type: "campaign_progress"; campaign_id: number; progress: number; success?: number }
  | {
      type: "dispatch_error";
      campaign_id: number;
      account_id?: number | null;
      contact_id?: number | null;
      error: string;
    }
  | { type: "campaign_update"; campaign_id: number; status: string };

// ── Connection states ─────────────────────────────────────────

export type WsConnectionState =
  | "connecting"    // first connection attempt in progress
  | "connected"     // authenticated, receiving messages
  | "disconnected"  // not connected, not retrying (initial or after dispose)
  | "reconnecting"  // lost connection, backoff retry scheduled/in-progress
  | "auth_failed";  // server rejected credentials (code 1008), no retry

// ── Backoff helpers (pure, exported for unit-testing) ─────────

const BASE_DELAY_MS = 250;
const MAX_DELAY_MS  = 30_000;
const JITTER_FACTOR = 0.3; // ±30 %

/**
 * Apply random jitter (±30 %) to a millisecond duration.
 * Returns a value in `[ms * 0.7, ms * 1.3]`, floored to 0.
 */
export const maybeJitter = (ms: number): number => {
  const offset = ms * JITTER_FACTOR * (Math.random() * 2 - 1);
  return Math.max(0, Math.round(ms + offset));
};

/**
 * Compute reconnection delay: `min(base * 2^attempt, cap)` with jitter.
 */
export const computeBackoff = (attempt: number): number => {
  const raw = Math.min(BASE_DELAY_MS * Math.pow(2, attempt), MAX_DELAY_MS);
  return maybeJitter(raw);
};

// ── Constants ─────────────────────────────────────────────────

/** Backend closes with 1008 on any auth problem. */
const AUTH_FAILURE_CODE = 1008;

/** If no message (including pings) arrives within this window → reconnect. */
const PING_TIMEOUT_MS = 45_000;

// ── Public handle type ────────────────────────────────────────

export interface StatusSocketHandle {
  /** Gracefully close and stop reconnecting. */
  dispose: () => void;
  /** Current connection state. */
  readonly state: WsConnectionState;
  /** Number of consecutive reconnect attempts since last successful connect. */
  readonly attempts: number;
}

type StateListener = (state: WsConnectionState) => void;

// ── Singleton guard ───────────────────────────────────────────

let activeHandle: StatusSocketHandle | null = null;

// ── Safe-send helper ──────────────────────────────────────────

/** Send data only if the socket is OPEN. Swallows send errors. */
const safeSend = (sock: WebSocket | null, data: string): void => {
  if (!sock || sock.readyState !== WebSocket.OPEN) return;
  try {
    sock.send(data);
  } catch {
    /* socket may have transitioned to CLOSING between the guard and send */
  }
};

// ── Main factory ──────────────────────────────────────────────

/**
 * Connect to the real-time status WebSocket.
 *
 * Returns a {@link StatusSocketHandle} for lifecycle management.
 * Calling again before dispose automatically closes the previous socket
 * (singleton guard).
 */
export const connectStatusSocket = (
  token: string,
  onMessage: (msg: StatusMessage) => void,
  onStateChange?: StateListener,
): StatusSocketHandle => {
  // Singleton: dispose previous connection if any.
  if (activeHandle) {
    activeHandle.dispose();
    activeHandle = null;
  }

  let disposed = false;
  let ws: WebSocket | null = null;
  let attempt = 0;
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  let pingTimer:      ReturnType<typeof setTimeout> | null = null;
  let currentState: WsConnectionState = "disconnected";

  /* ── State management ─────────────────────────────────────── */

  const setState = (next: WsConnectionState): void => {
    if (currentState === next) return;
    currentState = next;
    try { onStateChange?.(next); } catch { /* listener must not break lifecycle */ }
  };

  /* ── Timer management ─────────────────────────────────────── */

  const clearReconnectTimer = (): void => {
    if (reconnectTimer !== null) { clearTimeout(reconnectTimer); reconnectTimer = null; }
  };

  const clearPingTimer = (): void => {
    if (pingTimer !== null) { clearTimeout(pingTimer); pingTimer = null; }
  };

  const clearAllTimers = (): void => {
    clearReconnectTimer();
    clearPingTimer();
  };

  const resetPingWatchdog = (): void => {
    clearPingTimer();
    pingTimer = setTimeout(() => {
      if (ws && ws.readyState === WebSocket.OPEN) {
        console.warn("[ws] Ping timeout (%d ms) — forcing reconnect", PING_TIMEOUT_MS);
        ws.close(4000, "ping timeout");
      }
    }, PING_TIMEOUT_MS);
  };

  /* ── Reconnect scheduling ─────────────────────────────────── */

  const scheduleReconnect = (): void => {
    if (disposed) return;
    clearReconnectTimer(); // guarantee no duplicate timers
    const delay = computeBackoff(attempt);
    console.log("[ws] Reconnect scheduled — attempt #%d, delay %d ms", attempt + 1, delay);
    setState("reconnecting");
    attempt += 1;
    reconnectTimer = setTimeout(connect, delay);
  };

  /* ── Core connect ─────────────────────────────────────────── */

  function connect(): void {
    if (disposed) return;

    // "connecting" only on the very first attempt; later retries stay "reconnecting".
    if (attempt === 0) setState("connecting");

    const url = new URL("/ws/status", window.location.origin);
    url.protocol = url.protocol.replace("http", "ws");

    try {
      ws = new WebSocket(url.toString());
    } catch (err) {
      // SecurityError or similar from the constructor.
      console.warn("[ws] WebSocket constructor failed:", err);
      scheduleReconnect();
      return;
    }

    ws.onopen = (): void => {
      safeSend(ws, JSON.stringify({ type: "auth", token }));
      attempt = 0;
      setState("connected");
      resetPingWatchdog();
    };

    ws.onclose = (ev: CloseEvent): void => {
      clearAllTimers();

      if (disposed) {
        setState("disconnected");
        return;
      }

      if (ev.code === AUTH_FAILURE_CODE) {
        setState("auth_failed");
        console.warn("[ws] Auth failed (code 1008) — will not retry");
        return;
      }

      // Network drop, server restart, ping timeout — retry with backoff.
      scheduleReconnect();
    };

    ws.onerror = (): void => {
      // onerror is always followed by onclose — reconnect handled there.
    };

    ws.onmessage = (event: MessageEvent): void => {
      resetPingWatchdog();

      let payload: StatusMessage;
      try {
        payload = JSON.parse(event.data as string) as StatusMessage;
      } catch (err) {
        const snippet = typeof event.data === "string"
          ? event.data.slice(0, 80)
          : String(event.data).slice(0, 80);
        console.warn("[ws] JSON parse failed — data: \"%s\" — error:", snippet, err);
        return;
      }

      if (payload.type === "ping") {
        safeSend(ws, "pong");
        return;
      }

      try {
        onMessage(payload);
      } catch (err) {
        console.warn("[ws] onMessage handler threw:", err);
      }
    };
  }

  /* ── Start first connection ───────────────────────────────── */

  connect();

  /* ── Build handle ─────────────────────────────────────────── */

  const handle: StatusSocketHandle = {
    dispose(): void {
      if (disposed) return;
      disposed = true;
      clearAllTimers();
      if (ws) {
        // Assign noop handlers to prevent onclose from scheduling reconnect.
        ws.onclose = () => {};
        ws.onerror = () => {};
        ws.onmessage = () => {};
        if (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING) {
          ws.close(1000, "disposed");
        }
        ws = null;
      }
      setState("disconnected");
      if (activeHandle === handle) activeHandle = null;
    },
    get state(): WsConnectionState {
      return currentState;
    },
    get attempts(): number {
      return attempt;
    },
  };

  activeHandle = handle;
  return handle;
};
