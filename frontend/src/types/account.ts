export type AccountStatus = "new" | "warming" | "active" | "cooldown" | "blocked" | "verified";

export interface Account {
  id: number;
  user_id: number;
  owner_id: number;
  telegram_id: number;
  phone: string | null;
  username: string | null;
  first_name: string | null;
  status: AccountStatus;
  proxy_id: number | null;
  device_config: Record<string, unknown> | null;
  last_device_regenerated_at?: string | null;
  warming_actions_completed: number;
  target_warming_actions: number;
  warming_started_at: string | null;
  last_activity_at: string | null;
  cooldown_until: string | null;
  created_at: string;
  updated_at: string;
}

export interface AccountVerifyResponse {
  needs_password: boolean;
  account: Account | null;
}
