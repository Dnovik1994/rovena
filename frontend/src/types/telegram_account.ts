export type TgAccountStatus =
  | "new"
  | "code_sent"
  | "password_required"
  | "verified"
  | "disconnected"
  | "error"
  | "banned"
  | "warming"
  | "active"
  | "cooldown";

export interface TgAccount {
  id: number;
  owner_user_id: number;
  phone_e164: string;
  tg_user_id: number | null;
  tg_username: string | null;
  first_name: string | null;
  last_name: string | null;
  status: TgAccountStatus;
  proxy_id: number | null;
  device_config: Record<string, unknown> | null;
  last_error: string | null;
  warming_actions_completed: number;
  target_warming_actions: number;
  warming_started_at: string | null;
  cooldown_until: string | null;
  last_activity_at: string | null;
  last_device_regenerated_at: string | null;
  created_at: string;
  updated_at: string;
  verified_at: string | null;
  last_seen_at: string | null;
}

export interface SendCodeResponse {
  flow_id: string;
  status: TgAccountStatus;
  message: string;
}

export interface ConfirmCodeResponse {
  status: TgAccountStatus;
  needs_password: boolean;
  account: TgAccount | null;
  message: string;
}

export interface ConfirmPasswordResponse {
  status: TgAccountStatus;
  account: TgAccount | null;
  message: string;
}

export interface AuthFlowStatusResponse {
  flow_id: string;
  flow_state: string;
  account_status: TgAccountStatus;
  last_error: string | null;
  sent_at: string | null;
  expires_at: string | null;
  attempts: number;
}
