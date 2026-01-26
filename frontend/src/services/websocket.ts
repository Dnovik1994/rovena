export type StatusMessage =
  | {
      type: "account_update";
      account_id: number;
      status: string;
      actions_completed?: number;
      target_actions?: number;
      cooldown_until?: string | null;
    }
  | { type: "campaign_progress"; campaign_id: number; progress: number; success?: number }
  | {
      type: "dispatch_error";
      campaign_id: number;
      account_id?: number | null;
      contact_id?: number | null;
      error: string;
    }
  | { type: "campaign_update"; campaign_id: number; status: string };

export const connectStatusSocket = (
  token: string,
  onMessage: (message: StatusMessage) => void
): WebSocket => {
  const url = new URL("/ws/status", window.location.origin);
  url.protocol = url.protocol.replace("http", "ws");
  url.searchParams.set("token", token);

  const socket = new WebSocket(url.toString());

  socket.onmessage = (event) => {
    try {
      const payload = JSON.parse(event.data) as StatusMessage;
      onMessage(payload);
    } catch (error) {
      return;
    }
  };

  return socket;
};
