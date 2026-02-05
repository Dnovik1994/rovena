import { Account, AccountVerifyResponse } from "../types/account";
import { AdminAccount, AdminProxy, AdminStats, AdminTariff, AdminUser } from "../types/admin";
import { Campaign } from "../types/campaign";
import { Contact } from "../types/contact";
import { Project } from "../types/project";
import { Source } from "../types/source";
import { Target } from "../types/target";
import { DashboardAnalytics } from "../types/analytics";
import { apiFetch } from "./api";

export const fetchProjects = (token: string): Promise<Project[]> => {
  return apiFetch<Project[]>("/projects", {}, token);
};

export const createProject = (
  token: string,
  data: { name: string; description?: string | null }
): Promise<Project> => {
  return apiFetch<Project>(
    "/projects",
    { method: "POST", body: JSON.stringify(data) },
    token
  );
};

export const fetchSources = (token: string): Promise<Source[]> => {
  return apiFetch<Source[]>("/sources", {}, token);
};

export const createSource = (
  token: string,
  data: { project_id: number; name: string; link: string; type: string }
): Promise<Source> => {
  return apiFetch<Source>(
    "/sources",
    { method: "POST", body: JSON.stringify(data) },
    token
  );
};

export const fetchTargets = (token: string): Promise<Target[]> => {
  return apiFetch<Target[]>("/targets", {}, token);
};

export const createTarget = (
  token: string,
  data: { project_id: number; name: string; link: string; type: string }
): Promise<Target> => {
  return apiFetch<Target>(
    "/targets",
    { method: "POST", body: JSON.stringify(data) },
    token
  );
};

export const fetchContacts = (token: string): Promise<Contact[]> => {
  return apiFetch<Contact[]>("/contacts", {}, token);
};

export const createContact = (
  token: string,
  data: {
    project_id: number;
    telegram_id: number;
    first_name: string;
    last_name?: string | null;
    username?: string | null;
    phone?: string | null;
  }
): Promise<Contact> => {
  return apiFetch<Contact>(
    "/contacts",
    { method: "POST", body: JSON.stringify(data) },
    token
  );
};

export const fetchCampaigns = (token: string): Promise<Campaign[]> => {
  return apiFetch<Campaign[]>("/campaigns", {}, token);
};

export const fetchDashboardAnalytics = (token: string, windowDays = 14): Promise<DashboardAnalytics> => {
  return apiFetch<DashboardAnalytics>(`/analytics/dashboard?window_days=${windowDays}`, {}, token);
};

export const createCampaign = (
  token: string,
  data: {
    project_id: number;
    name: string;
    source_id?: number | null;
    target_id?: number | null;
    max_invites_per_hour: number;
    max_invites_per_day: number;
  }
): Promise<Campaign> => {
  return apiFetch<Campaign>(
    "/campaigns",
    { method: "POST", body: JSON.stringify(data) },
    token
  );
};

export const startCampaign = (token: string, id: number): Promise<Campaign> => {
  return apiFetch<Campaign>(`/campaigns/${id}/start`, { method: "POST" }, token);
};

export const stopCampaign = (token: string, id: number): Promise<Campaign> => {
  return apiFetch<Campaign>(`/campaigns/${id}/stop`, { method: "POST" }, token);
};

export const fetchAccounts = (token: string): Promise<Account[]> => {
  return apiFetch<Account[]>("/accounts", {}, token);
};

export const createAccount = (
  token: string,
  data: {
    user_id: number;
    telegram_id: number;
    phone?: string;
    username?: string;
    first_name?: string;
    status: string;
  }
): Promise<Account> => {
  return apiFetch<Account>(
    "/accounts",
    { method: "POST", body: JSON.stringify(data) },
    token
  );
};

export const startAccountWarming = (token: string, id: number): Promise<Account> => {
  return apiFetch<Account>(`/accounts/${id}/start-warming`, { method: "POST" }, token);
};

export const regenerateDeviceConfig = (token: string, id: number): Promise<Account> => {
  return apiFetch<Account>(`/accounts/${id}/regenerate-device`, { method: "POST" }, token);
};

export const verifyAccount = (token: string, id: number): Promise<AccountVerifyResponse> => {
  return apiFetch<AccountVerifyResponse>(`/accounts/${id}/verify`, { method: "POST" }, token);
};

export const fetchAdminStats = (token: string): Promise<AdminStats> => {
  return apiFetch<AdminStats>("/admin/stats", {}, token);
};

export const fetchAdminUsers = (
  token: string,
  search = "",
  tariff = ""
): Promise<{ items: AdminUser[] }> => {
  const params = new URLSearchParams();
  if (search) {
    params.set("search", search);
  }
  if (tariff) {
    params.set("tariff", tariff);
  }
  const query = params.toString() ? `?${params.toString()}` : "";
  return apiFetch<{ items: AdminUser[] }>(`/admin/users${query}`, {}, token);
};

export const updateAdminUser = (
  token: string,
  id: number,
  data: { is_active?: boolean; role?: string | null }
): Promise<AdminUser> => {
  return apiFetch<AdminUser>(
    `/admin/users/${id}`,
    { method: "PATCH", body: JSON.stringify(data) },
    token
  );
};

export const fetchAdminProxies = (
  token: string
): Promise<{ items: AdminProxy[] }> => {
  return apiFetch<{ items: AdminProxy[] }>("/admin/proxies", {}, token);
};

export const validateProxy = (token: string, id: number): Promise<AdminProxy> => {
  return apiFetch<AdminProxy>(`/proxies/${id}/validate`, { method: "POST" }, token);
};

export const fetchAdminAccounts = (
  token: string
): Promise<{ items: AdminAccount[] }> => {
  return apiFetch<{ items: AdminAccount[] }>("/admin/accounts", {}, token);
};

export const fetchAdminTariffs = (token: string): Promise<AdminTariff[]> => {
  return apiFetch<AdminTariff[]>("/admin/tariffs", {}, token);
};

export const createAdminTariff = (
  token: string,
  data: {
    name: string;
    max_accounts: number;
    max_invites_day: number;
    price?: number | null;
  }
): Promise<AdminTariff> => {
  return apiFetch<AdminTariff>(
    "/admin/tariffs",
    { method: "POST", body: JSON.stringify(data) },
    token
  );
};

export const updateAdminTariff = (
  token: string,
  id: number,
  data: {
    name?: string;
    max_accounts?: number;
    max_invites_day?: number;
    price?: number | null;
  }
): Promise<AdminTariff> => {
  return apiFetch<AdminTariff>(
    `/admin/tariffs/${id}`,
    { method: "PATCH", body: JSON.stringify(data) },
    token
  );
};

export const deleteAdminTariff = (token: string, id: number): Promise<void> => {
  return apiFetch<void>(`/admin/tariffs/${id}`, { method: "DELETE" }, token);
};

export const updateAdminUserTariff = (
  token: string,
  userId: number,
  tariffId: number
): Promise<AdminUser> => {
  return apiFetch<AdminUser>(
    `/admin/users/${userId}/tariff`,
    { method: "PATCH", body: JSON.stringify({ tariff_id: tariffId }) },
    token
  );
};

export const createAdminCheckoutSession = (
  token: string,
  data: { tariff_id: number; user_id?: number }
): Promise<{ checkout_url: string }> => {
  return apiFetch<{ checkout_url: string }>(
    "/admin/subscriptions/create-checkout",
    { method: "POST", body: JSON.stringify(data) },
    token
  );
};

export const updateOnboarding = (token: string, completed: boolean): Promise<void> => {
  return apiFetch<void>(
    "/users/me/onboarding",
    { method: "PATCH", body: JSON.stringify({ onboarding_completed: completed }) },
    token
  );
};
