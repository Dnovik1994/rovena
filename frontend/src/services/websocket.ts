/* ──────────────────────────────────────────────────────────────
 *  Reliable WebSocket client with reconnection, backoff + jitter,
 *  auth-failure detection, and singleton guard.
 * ────────────────────────────────────────────────────────────── */

export type StatusMessage =
  | {
      type: "account_update";
      account_id: number;
      status: string;
      actions_completed?: number;
      target_actions?: number;
      cooldown_until?: string | null;
    }
  | {
      type: "account_status_changed";
      account_id: number;
      status: string;
      phone?: string;
      actions_completed?: number;
      target_actions?: number;
    }
  | {
      type: "auth_flow_updated";
      account_id: number;
      flow_id: string;
      state: string;
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

/* ── Connection state exposed to UI ── */

export type WsConnectionState = "connecting" | "connected" | "disconnected" | "auth_failed" | "failed";

/* ── Backoff helpers (pure, testable) ── */

const BASE_DELAY_MS = 250;
const MAX_DELAY_MS = 30_000;
const JITTER_FACTOR = 0.3; // ±30 %

/**
 * Compute reconnection delay with exponential backoff and jitter.
 * Exported for unit-testing.
 */
export const computeBackoff = (attempt: number): number => {
  const exp = Math.min(BASE_DELAY_MS * Math.pow(2, attempt), MAX_DELAY_MS);
  const jitter = exp * JITTER_FACTOR * (Math.random() * 2 - 1); // [-30%..+30%]
  return Math.max(0, Math.round(exp + jitter));
};

/* ── Auth-failure close code used by the backend ── */

const AUTH_FAILURE_CODE = 1008;

/* ── Ping/pong timeout: if nothing arrives within this window, reconnect ── */

const PING_TIMEOUT_MS = 45_000;

/* ── Max reconnect attempts before giving up ── */

const MAX_RECONNECT_ATTEMPTS = 20;

/* ── Types ── */

export interface StatusSocketHandle {
  /** Gracefully close and stop reconnecting. */
  dispose: () => void;
  /** Current connection state. */
  readonly state: WsConnectionState;
}

type StateListener = (state: WsConnectionState) => void;

/* ──────────────────────────────────────────────────────────────
 *  Singleton guard: only ONE active connection allowed.
 * ────────────────────────────────────────────────────────────── */

let activeHandle: StatusSocketHandle | null = null;

/* ──────────────────────────────────────────────────────────────
 *  Public API
 * ────────────────────────────────────────────────────────────── */

/**
 * Connect to the real-time status WebSocket.
 *
 * - First-message auth protocol (sends `{type:"auth",token}` after open).
 * - Exponential backoff with jitter on network drops.
 * - Stops retrying on auth failure (close code 1008).
 * - Singleton: calling again disposes previous connection.
 */
export const connectStatusSocket = (
  token: string,
  onMessage: (msg: StatusMessage) => void,
  onStateChange?: StateListener,
): StatusSocketHandle => {
  // Dispose previous connection if any (singleton guard).
  if (activeHandle) {
    activeHandle.dispose();
    activeHandle = null;
  }

  let disposed = false;
  let ws: WebSocket | null = null;
  let attempt = 0;
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  let pingTimer: ReturnType<typeof setTimeout> | null = null;
  let currentState: WsConnectionState = "disconnected";

  const setState = (next: WsConnectionState) => {
    if (currentState === next) return;
    currentState = next;
    try {
      onStateChange?.(next);
    } catch {
      /* listener errors must not break the socket lifecycle */
    }
  };

  const clearTimers = () => {
    if (reconnectTimer !== null) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
    if (pingTimer !== null) {
      clearTimeout(pingTimer);
      pingTimer = null;
    }
  };

  const resetPingTimer = () => {
    if (pingTimer !== null) clearTimeout(pingTimer);
    pingTimer = setTimeout(() => {
      // Server went silent — force-close so onclose triggers reconnect.
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.close(4000, "ping timeout");
      }
    }, PING_TIMEOUT_MS);
  };

  const scheduleReconnect = () => {
    if (disposed) return;
    if (attempt >= MAX_RECONNECT_ATTEMPTS) {
      console.warn("WebSocket: max reconnect attempts reached");
      setState("failed");
      return;
    }
    const delay = computeBackoff(attempt);
    attempt += 1;
    reconnectTimer = setTimeout(connect, delay);
  };

  function connect() {
    if (disposed) return;

    setState("connecting");

    const url = new URL("/ws/status", window.location.origin);
    url.protocol = url.protocol.replace("http", "ws");

    ws = new WebSocket(url.toString());

    ws.onopen = () => {
      // Send first-message auth immediately.
      ws!.send(JSON.stringify({ type: "auth", token }));
      attempt = 0;
      setState("connected");
      resetPingTimer();
    };

    ws.onclose = (ev: CloseEvent) => {
      clearTimers();

      if (disposed) {
        setState("disconnected");
        return;
      }

      if (ev.code === AUTH_FAILURE_CODE) {
        setState("auth_failed");
        console.warn("[ws] Auth failed (1008) — will not retry");
        return;
      }

      setState("disconnected");
      scheduleReconnect();
    };

    ws.onerror = () => {
      // onerror is always followed by onclose; nothing extra needed.
    };

    ws.onmessage = (event: MessageEvent) => {
      resetPingTimer();

      let payload: StatusMessage;
      try {
        payload = JSON.parse(event.data as string) as StatusMessage;
      } catch (err) {
        console.warn("[ws] Failed to parse message:", err);
        return;
      }

      if (payload.type === "ping") {
        ws!.send("pong");
        return;
      }

      try {
        onMessage(payload);
      } catch (err) {
        console.warn("[ws] onMessage handler threw:", err);
      }
    };
  }

  // Kick off the first connection.
  connect();

  const handle: StatusSocketHandle = {
    dispose() {
      disposed = true;
      clearTimers();
      if (ws) {
        ws.onclose = null; // prevent reconnect from firing
        if (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING) {
          ws.close(1000, "disposed");
        }
        ws = null;
      }
      setState("disconnected");
    },
    get state() {
      return currentState;
    },
  };

  activeHandle = handle;
  return handle;
};
