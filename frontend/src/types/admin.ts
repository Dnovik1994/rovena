export interface AdminStats {
  users: number;
  accounts: number;
  accounts_active: number;
  accounts_warming: number;
  proxies: number;
  proxies_online: number;
  campaigns: number;
  campaigns_active: number;
}

export interface AdminUser {
  id: number;
  telegram_id: number;
  username: string | null;
  is_admin: boolean;
  is_active: boolean;
  role: string | null;
  tariff: AdminTariff | null;
}

export interface AdminProxy {
  id: number;
  host: string;
  port: number;
  type: string | null;
  status: string | null;
  country: string | null;
  last_check?: string | null;
  latency_ms?: number | null;
}

export interface ApiAppBrief {
  id: number;
  api_id: number;
  app_title: string | null;
  is_active: boolean;
}

export interface AdminAccount {
  id: number;
  telegram_id: number;
  status: string | null;
  owner_id: number;
  user_id: number;
  proxy: {
    id: number;
    host: string;
    port: number;
    status: string | null;
  } | null;
  api_app: ApiAppBrief | null;
  warming_actions_completed: number;
  target_warming_actions: number;
}

export interface AdminApiApp {
  id: number;
  api_id: number;
  api_hash: string;
  app_title: string | null;
  registered_phone: string | null;
  max_accounts: number;
  is_active: boolean;
  notes: string | null;
  created_at: string;
  current_accounts_count: number;
}

export interface ApiAppCreateResponse {
  id: number;
  api_id: number;
  api_hash: string;
  app_title: string | null;
  registered_phone: string | null;
  max_accounts: number;
  is_active: boolean;
  notes: string | null;
  created_at: string;
}

export interface ApiAppHashReveal {
  id: number;
  api_id: number;
  api_hash: string;
}

export interface AdminTariff {
  id: number;
  name: string;
  max_accounts: number;
  max_invites_day: number;
  price: number | null;
}
