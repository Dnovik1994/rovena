import React, { useEffect, useMemo, useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import ErrorState from "../components/ErrorState";
import LoadingSkeleton from "../components/LoadingSkeleton";
import {
  createAdminTariff,
  createApiApp,
  deleteAdminTariff,
  deleteApiApp,
  fetchAdminAccounts,
  fetchAdminProxies,
  fetchAdminStats,
  fetchAdminTariffs,
  fetchAdminUsers,
  fetchApiApps,
  revealApiAppHash,
  updateAdminTariff,
  updateAdminUser,
  updateAdminUserTariff,
  updateApiApp,
  validateProxy,
} from "../services/resources";
import { useAuth } from "../stores/auth";
import { AdminAccount, AdminApiApp, AdminProxy, AdminStats, AdminTariff, AdminUser } from "../types/admin";

type TabKey = "stats" | "users" | "tariffs" | "proxies" | "accounts" | "api-apps";

type TariffFormValues = {
  name: string;
  max_accounts: number;
  max_invites_day: number;
  price?: number | undefined;
};

const tariffSchema = z.object({
  name: z.string().min(1, "Название обязательно"),
  max_accounts: z.coerce.number().int().positive(),
  max_invites_day: z.coerce.number().int().positive(),
  price: z.preprocess(
    (value) => {
      if (value === "" || value === null || Number.isNaN(value)) {
        return undefined;
      }
      return value;
    },
    z.number().nonnegative().optional()
  ),
});

type ApiAppFormValues = {
  api_id: number;
  api_hash: string;
  app_title: string;
  max_accounts: number;
  is_active: boolean;
  registered_phone: string;
  notes: string;
};

const apiAppSchema = z.object({
  api_id: z.coerce.number().int().positive("Укажите api_id"),
  api_hash: z.string().min(1, "api_hash обязателен"),
  app_title: z.string(),
  max_accounts: z.coerce.number().int().min(1, "Минимум 1"),
  is_active: z.boolean(),
  registered_phone: z.string(),
  notes: z.string(),
});

const Admin = (): JSX.Element => {
  const { token } = useAuth();
  const [activeTab, setActiveTab] = useState<TabKey>("stats");
  const [search, setSearch] = useState("");
  const [tariffFilter, setTariffFilter] = useState("");
  const [editingTariff, setEditingTariff] = useState<AdminTariff | null>(null);
  const [editingApiApp, setEditingApiApp] = useState<AdminApiApp | null>(null);
  const [showApiAppForm, setShowApiAppForm] = useState(false);
  const [createdApiHash, setCreatedApiHash] = useState<string | null>(null);
  const [deleteApiAppError, setDeleteApiAppError] = useState<string | null>(null);
  const [revealedHash, setRevealedHash] = useState<string | null>(null);
  const queryClient = useQueryClient();

  const enabled = useMemo(() => Boolean(token), [token]);

  const tariffForm = useForm<TariffFormValues>({
    resolver: zodResolver(tariffSchema),
    defaultValues: {
      name: "",
      max_accounts: 5,
      max_invites_day: 50,
      price: undefined,
    },
  });

  const apiAppForm = useForm<ApiAppFormValues>({
    resolver: zodResolver(apiAppSchema),
    defaultValues: {
      api_id: undefined as unknown as number,
      api_hash: "",
      app_title: "",
      max_accounts: 3,
      is_active: true,
      registered_phone: "",
      notes: "",
    },
  });

  useEffect(() => {
    if (editingTariff) {
      tariffForm.reset({
        name: editingTariff.name,
        max_accounts: editingTariff.max_accounts,
        max_invites_day: editingTariff.max_invites_day,
        price: editingTariff.price ?? undefined,
      });
      return;
    }
    tariffForm.reset({ name: "", max_accounts: 5, max_invites_day: 50, price: undefined });
  }, [editingTariff, tariffForm]);

  useEffect(() => {
    if (editingApiApp) {
      apiAppForm.reset({
        api_id: editingApiApp.api_id,
        api_hash: editingApiApp.api_hash,
        app_title: editingApiApp.app_title ?? "",
        max_accounts: editingApiApp.max_accounts,
        is_active: editingApiApp.is_active,
        registered_phone: editingApiApp.registered_phone ?? "",
        notes: editingApiApp.notes ?? "",
      });
      setRevealedHash(null);
      return;
    }
    apiAppForm.reset({
      api_id: undefined as unknown as number,
      api_hash: "",
      app_title: "",
      max_accounts: 3,
      is_active: true,
      registered_phone: "",
      notes: "",
    });
    setRevealedHash(null);
  }, [editingApiApp, apiAppForm]);

  const statsQuery = useQuery<AdminStats>({
    queryKey: ["admin-stats"],
    queryFn: () => fetchAdminStats(token ?? ""),
    enabled,
  });

  const tariffsQuery = useQuery<AdminTariff[]>({
    queryKey: ["admin-tariffs"],
    queryFn: () => fetchAdminTariffs(token ?? ""),
    enabled: enabled && (activeTab === "tariffs" || activeTab === "users"),
  });

  const usersQuery = useQuery<{ items: AdminUser[] }>({
    queryKey: ["admin-users", search, tariffFilter],
    queryFn: () => fetchAdminUsers(token ?? "", search, tariffFilter),
    enabled: enabled && activeTab === "users",
  });

  const proxiesQuery = useQuery<{ items: AdminProxy[] }>({
    queryKey: ["admin-proxies"],
    queryFn: () => fetchAdminProxies(token ?? ""),
    enabled: enabled && activeTab === "proxies",
  });

  const accountsQuery = useQuery<{ items: AdminAccount[] }>({
    queryKey: ["admin-accounts"],
    queryFn: () => fetchAdminAccounts(token ?? ""),
    enabled: enabled && activeTab === "accounts",
  });

  const apiAppsQuery = useQuery<AdminApiApp[]>({
    queryKey: ["admin-api-apps"],
    queryFn: () => fetchApiApps(token ?? ""),
    enabled: enabled && activeTab === "api-apps",
  });

  useEffect(() => {
    if (!enabled) {
      return;
    }
    if (activeTab === "stats") {
      queryClient.prefetchQuery({
        queryKey: ["admin-users", search, tariffFilter],
        queryFn: () => fetchAdminUsers(token ?? "", search, tariffFilter),
      });
      queryClient.prefetchQuery({
        queryKey: ["admin-tariffs"],
        queryFn: () => fetchAdminTariffs(token ?? ""),
      });
    }
    if (activeTab === "users") {
      queryClient.prefetchQuery({
        queryKey: ["admin-tariffs"],
        queryFn: () => fetchAdminTariffs(token ?? ""),
      });
    }
    if (activeTab === "tariffs") {
      queryClient.prefetchQuery({
        queryKey: ["admin-users", search, tariffFilter],
        queryFn: () => fetchAdminUsers(token ?? "", search, tariffFilter),
      });
    }
    if (activeTab === "proxies") {
      queryClient.prefetchQuery({
        queryKey: ["admin-accounts"],
        queryFn: () => fetchAdminAccounts(token ?? ""),
      });
    }
    if (activeTab === "accounts") {
      queryClient.prefetchQuery({
        queryKey: ["admin-api-apps"],
        queryFn: () => fetchApiApps(token ?? ""),
      });
    }
  }, [activeTab, enabled, queryClient, search, tariffFilter, token]);

  useEffect(() => {
    if (!enabled) {
      return;
    }
    queryClient.prefetchQuery({
      queryKey: ["admin-users", "", ""],
      queryFn: () => fetchAdminUsers(token ?? "", "", ""),
    });
    queryClient.prefetchQuery({
      queryKey: ["admin-proxies"],
      queryFn: () => fetchAdminProxies(token ?? ""),
    });
  }, [enabled, queryClient, token]);

  const updateUserMutation = useMutation({
    mutationFn: (payload: { id: number; is_active?: boolean; role?: string | null }) =>
      updateAdminUser(token ?? "", payload.id, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin-users"] });
    },
  });

  const updateUserTariffMutation = useMutation({
    mutationFn: (payload: { id: number; tariff_id: number }) =>
      updateAdminUserTariff(token ?? "", payload.id, payload.tariff_id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin-users"] });
    },
  });

  const validateProxyMutation = useMutation({
    mutationFn: (payload: { id: number }) => validateProxy(token ?? "", payload.id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin-proxies"] });
    },
  });

  const createTariffMutation = useMutation({
    mutationFn: (payload: TariffFormValues) => createAdminTariff(token ?? "", payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin-tariffs"] });
      setEditingTariff(null);
    },
  });

  const updateTariffMutation = useMutation({
    mutationFn: (payload: { id: number; data: TariffFormValues }) =>
      updateAdminTariff(token ?? "", payload.id, payload.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin-tariffs"] });
      setEditingTariff(null);
    },
  });

  const deleteTariffMutation = useMutation({
    mutationFn: (payload: { id: number }) => deleteAdminTariff(token ?? "", payload.id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin-tariffs"] });
    },
    onError: (error: any) => {
      const status = error?.status;
      if (status === 400 || status === 409) {
        alert("Невозможно удалить тариф: к нему привязаны пользователи.");
      } else {
        alert("Ошибка при удалении тарифа.");
      }
    },
  });

  const createApiAppMutation = useMutation({
    mutationFn: (payload: {
      api_id: number;
      api_hash: string;
      app_title?: string;
      max_accounts?: number;
      registered_phone?: string;
      notes?: string;
    }) => createApiApp(token ?? "", payload),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ["admin-api-apps"] });
      setCreatedApiHash(data.api_hash);
      setShowApiAppForm(false);
      setEditingApiApp(null);
    },
  });

  const updateApiAppMutation = useMutation({
    mutationFn: (payload: {
      id: number;
      data: {
        app_title?: string | null;
        max_accounts?: number;
        is_active?: boolean;
        registered_phone?: string | null;
        notes?: string | null;
      };
    }) => updateApiApp(token ?? "", payload.id, payload.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin-api-apps"] });
      setShowApiAppForm(false);
      setEditingApiApp(null);
    },
  });

  const deleteApiAppMutation = useMutation({
    mutationFn: (payload: { id: number }) => deleteApiApp(token ?? "", payload.id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin-api-apps"] });
      setDeleteApiAppError(null);
    },
    onError: (error: unknown) => {
      const err = error as { status?: number; message?: string };
      if (err?.status === 409) {
        setDeleteApiAppError("Невозможно удалить: есть привязанные аккаунты.");
      } else {
        setDeleteApiAppError(err?.message || "Ошибка при удалении.");
      }
    },
  });

  const revealHashMutation = useMutation({
    mutationFn: (id: number) => revealApiAppHash(token ?? "", id),
    onSuccess: (data) => {
      setRevealedHash(data.api_hash);
    },
  });

  if (!token) {
    return <p className="page__subtitle">Нужна авторизация.</p>;
  }

  if (statsQuery.isLoading && activeTab === "stats") {
    return <LoadingSkeleton rows={3} label="Загрузка метрик" />;
  }

  if (statsQuery.isError && activeTab === "stats") {
    return <ErrorState title="Ошибка" description="Нет доступа к админ-статистике." />;
  }

  const stats = statsQuery.data;

  const tariffs = tariffsQuery.data ?? [];

  const onTariffSubmit = tariffForm.handleSubmit((values) => {
    if (editingTariff) {
      updateTariffMutation.mutate({ id: editingTariff.id, data: values });
      return;
    }
    createTariffMutation.mutate(values);
  });

  const onApiAppSubmit = apiAppForm.handleSubmit((values) => {
    if (editingApiApp) {
      updateApiAppMutation.mutate({
        id: editingApiApp.id,
        data: {
          app_title: values.app_title || null,
          max_accounts: values.max_accounts,
          is_active: values.is_active,
          registered_phone: values.registered_phone || null,
          notes: values.notes || null,
        },
      });
      return;
    }
    const payload: {
      api_id: number;
      api_hash: string;
      app_title?: string;
      max_accounts?: number;
      registered_phone?: string;
      notes?: string;
    } = {
      api_id: values.api_id,
      api_hash: values.api_hash,
      max_accounts: values.max_accounts,
    };
    if (values.app_title) payload.app_title = values.app_title;
    if (values.registered_phone) payload.registered_phone = values.registered_phone;
    if (values.notes) payload.notes = values.notes;
    createApiAppMutation.mutate(payload);
  });

  return (
    <section className="page">
      <div>
        <h2 className="page__title">Admin Dashboard</h2>
        <p className="page__subtitle">Базовые метрики и контроль доступов.</p>
      </div>

      <div className="flex flex-wrap gap-2">
        {(["stats", "users", "tariffs", "proxies", "accounts", "api-apps"] as TabKey[]).map((tab) => (
          <button
            key={tab}
            type="button"
            onClick={() => setActiveTab(tab)}
            className={`rounded-full px-3 py-1 text-xs uppercase ${
              activeTab === tab ? "bg-indigo-500 text-white" : "bg-slate-900 text-slate-300"
            }`}
          >
            {tab}
          </button>
        ))}
      </div>

      {activeTab === "stats" && stats && (
        <div className="grid gap-4 md:grid-cols-2">
          <div className="card card__body">
            <p className="label">Users</p>
            <p className="text-2xl font-semibold">{stats.users}</p>
          </div>
          <div className="card card__body">
            <p className="label">Accounts</p>
            <p className="text-2xl font-semibold">{stats.accounts}</p>
            <p className="text-xs text-slate-400">
              Active: {stats.accounts_active} · Warming: {stats.accounts_warming}
            </p>
          </div>
          <div className="card card__body">
            <p className="label">Proxies</p>
            <p className="text-2xl font-semibold">{stats.proxies}</p>
            <p className="text-xs text-slate-400">Online: {stats.proxies_online}</p>
          </div>
          <div className="card card__body">
            <p className="label">Campaigns</p>
            <p className="text-2xl font-semibold">{stats.campaigns}</p>
            <p className="text-xs text-slate-400">Active: {stats.campaigns_active}</p>
          </div>
        </div>
      )}

      {activeTab === "users" && (
        <div className="space-y-3 rounded-2xl border border-slate-800 bg-slate-900/60 p-4">
          <div className="flex flex-wrap gap-2">
            <input
              className="w-full flex-1 rounded-xl border border-slate-800 bg-slate-950 px-3 py-2 text-sm"
              placeholder="Search by username or telegram_id"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
            />
            <select
              className="rounded-xl border border-slate-800 bg-slate-950 px-3 py-2 text-sm"
              value={tariffFilter}
              onChange={(event) => setTariffFilter(event.target.value)}
            >
              <option value="">All tariffs</option>
              {tariffs.map((tariff) => (
                <option key={tariff.id} value={tariff.name}>
                  {tariff.name}
                </option>
              ))}
            </select>
          </div>
          {usersQuery.isLoading ? (
            <LoadingSkeleton rows={3} label="Загрузка пользователей" />
          ) : (
            <div className="space-y-2 text-sm">
              {usersQuery.data?.items.map((user) => (
                <div
                  key={user.id}
                  className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-slate-800 bg-slate-950 px-3 py-2"
                >
                  <div>
                    <p className="font-semibold">{user.username ?? "Без username"}</p>
                    <p className="text-xs text-slate-400">TG: {user.telegram_id}</p>
                    <p className="text-xs text-slate-500">
                      Tariff: {user.tariff?.name ?? "n/a"}
                    </p>
                  </div>
                  <div className="flex flex-wrap items-center gap-2 text-xs text-slate-300">
                    <span>Role: {user.role ?? "user"}</span>
                    <button
                      type="button"
                      onClick={() =>
                        updateUserMutation.mutate({
                          id: user.id,
                          is_active: !user.is_active,
                        })
                      }
                      className="rounded-full border border-slate-700 px-3 py-1"
                    >
                      {user.is_active ? "Deactivate" : "Activate"}
                    </button>
                    <button
                      type="button"
                      onClick={() =>
                        updateUserMutation.mutate({
                          id: user.id,
                          role: user.role === "admin" || user.role === "superadmin" ? "user" : "admin",
                        })
                      }
                      className="rounded-full border border-indigo-400 px-3 py-1 text-indigo-200"
                    >
                      {user.role === "admin" || user.role === "superadmin" ? "Revoke Admin" : "Grant Admin"}
                    </button>
                    <select
                      className="rounded-full border border-slate-700 bg-slate-950 px-3 py-1"
                      value={user.tariff?.id ?? ""}
                      disabled={tariffs.length === 0}
                      onChange={(event) =>
                        updateUserTariffMutation.mutate({
                          id: user.id,
                          tariff_id: Number(event.target.value),
                        })
                      }
                    >
                      {tariffs.length === 0 && <option value="">No tariffs</option>}
                      {tariffs.map((tariff) => (
                        <option key={tariff.id} value={tariff.id}>
                          {tariff.name}
                        </option>
                      ))}
                    </select>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {activeTab === "tariffs" && (
        <div className="space-y-4 rounded-2xl border border-slate-800 bg-slate-900/60 p-4 text-sm">
          <form onSubmit={onTariffSubmit} className="grid gap-3 md:grid-cols-2">
            <div className="space-y-1">
              <label className="label">Name</label>
              <input
                className="w-full rounded-xl border border-slate-800 bg-slate-950 px-3 py-2 text-sm"
                {...tariffForm.register("name")}
              />
              {tariffForm.formState.errors.name && (
                <p className="text-xs text-rose-400">Введите имя тарифа.</p>
              )}
            </div>
            <div className="space-y-1">
              <label className="label">Max accounts</label>
              <input
                className="w-full rounded-xl border border-slate-800 bg-slate-950 px-3 py-2 text-sm"
                type="number"
                {...tariffForm.register("max_accounts")}
              />
            </div>
            <div className="space-y-1">
              <label className="label">Max invites / day</label>
              <input
                className="w-full rounded-xl border border-slate-800 bg-slate-950 px-3 py-2 text-sm"
                type="number"
                {...tariffForm.register("max_invites_day")}
              />
            </div>
            <div className="space-y-1">
              <label className="label">Price</label>
              <input
                className="w-full rounded-xl border border-slate-800 bg-slate-950 px-3 py-2 text-sm"
                type="number"
                step="0.01"
                {...tariffForm.register("price", { valueAsNumber: true })}
              />
            </div>
            <div className="flex flex-wrap items-center gap-2 md:col-span-2">
              <button
                type="submit"
                className="rounded-xl bg-indigo-500 px-4 py-2 text-sm font-semibold text-white"
              >
                {editingTariff ? "Update tariff" : "Create tariff"}
              </button>
              {editingTariff && (
                <button
                  type="button"
                  className="rounded-xl border border-slate-700 px-4 py-2 text-sm"
                  onClick={() => setEditingTariff(null)}
                >
                  Cancel
                </button>
              )}
            </div>
          </form>

          {tariffsQuery.isLoading ? (
            <LoadingSkeleton rows={3} label="Загрузка тарифов" />
          ) : (
            <div className="space-y-2">
              {tariffs.map((tariff) => (
                <div
                  key={tariff.id}
                  className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-slate-800 bg-slate-950 px-3 py-2"
                >
                  <div>
                    <p className="font-semibold">{tariff.name}</p>
                    <p className="text-xs text-slate-400">
                      Accounts: {tariff.max_accounts} · Invites/day: {tariff.max_invites_day}
                    </p>
                    <p className="text-xs text-slate-500">
                      Price: {tariff.price !== null ? `$${tariff.price}` : "free"}
                    </p>
                  </div>
                  <div className="flex items-center gap-2 text-xs">
                    <button
                      type="button"
                      className="rounded-full border border-slate-700 px-3 py-1"
                      onClick={() => setEditingTariff(tariff)}
                    >
                      Edit
                    </button>
                    <button
                      type="button"
                      className="rounded-full border border-rose-400 px-3 py-1 text-rose-200"
                      onClick={() => {
                        if (window.confirm("Удалить тариф? Это действие необратимо.")) {
                          deleteTariffMutation.mutate({ id: tariff.id });
                        }
                      }}
                    >
                      Delete
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {activeTab === "proxies" && (
        <div className="space-y-2 rounded-2xl border border-slate-800 bg-slate-900/60 p-4 text-sm">
          {proxiesQuery.isLoading ? (
            <LoadingSkeleton rows={3} label="Загрузка прокси" />
          ) : (
            proxiesQuery.data?.items.map((proxy) => (
              <div
                key={proxy.id}
                className="flex items-center justify-between rounded-xl border border-slate-800 bg-slate-950 px-3 py-2"
              >
                <div>
                  <p className="font-semibold">
                    {proxy.host}:{proxy.port}
                  </p>
                  <p className="text-xs text-slate-400">
                    {proxy.type ?? "unknown"} · {proxy.country ?? "n/a"}
                  </p>
                  <p className="text-xs text-slate-500">
                    Last check: {proxy.last_check ?? "n/a"} · Latency:{" "}
                    {proxy.latency_ms ? `${proxy.latency_ms}ms` : "n/a"}
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-xs text-slate-400">{proxy.status ?? "unknown"}</span>
                  <button
                    type="button"
                    onClick={() => validateProxyMutation.mutate({ id: proxy.id })}
                    className="rounded-full border border-slate-700 px-3 py-1 text-xs"
                  >
                    Validate
                  </button>
                </div>
              </div>
            ))
          )}
        </div>
      )}

      {activeTab === "accounts" && (
        <div className="space-y-2 rounded-2xl border border-slate-800 bg-slate-900/60 p-4 text-sm">
          {accountsQuery.isLoading ? (
            <LoadingSkeleton rows={3} label="Загрузка аккаунтов" />
          ) : (
            accountsQuery.data?.items.map((account) => (
              <div
                key={account.id}
                className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-slate-800 bg-slate-950 px-3 py-2"
              >
                <div>
                  <p className="font-semibold">TG: {account.telegram_id}</p>
                  <p className="text-xs text-slate-400">
                    Status: {account.status ?? "unknown"} · Owner: {account.owner_id}
                  </p>
                  <p className="text-xs text-slate-400">
                    Warming: {account.warming_actions_completed}/{account.target_warming_actions}
                  </p>
                </div>
                <div className="flex flex-wrap items-center gap-3 text-xs text-slate-400">
                  <span>
                    API App:{" "}
                    {account.api_app
                      ? account.api_app.app_title || String(account.api_app.api_id)
                      : "none"}
                  </span>
                  <span>
                    Proxy: {account.proxy ? `${account.proxy.host}:${account.proxy.port}` : "none"}
                  </span>
                </div>
              </div>
            ))
          )}
        </div>
      )}

      {activeTab === "api-apps" && (
        <div className="space-y-4 rounded-2xl border border-slate-800 bg-slate-900/60 p-4 text-sm">
          {/* Created hash alert */}
          {createdApiHash && (
            <div className="rounded-xl border border-emerald-700 bg-emerald-950/60 px-4 py-3">
              <p className="font-semibold text-emerald-300">
                API App создан. Сохраните api_hash — он больше не будет показан полностью:
              </p>
              <p className="mt-1 break-all font-mono text-sm text-emerald-200">{createdApiHash}</p>
              <button
                type="button"
                className="mt-2 rounded-full border border-emerald-700 px-3 py-1 text-xs text-emerald-300"
                onClick={() => setCreatedApiHash(null)}
              >
                Закрыть
              </button>
            </div>
          )}

          {/* Delete error alert */}
          {deleteApiAppError && (
            <div className="rounded-xl border border-rose-700 bg-rose-950/60 px-4 py-3">
              <p className="text-sm text-rose-300">{deleteApiAppError}</p>
              <button
                type="button"
                className="mt-2 rounded-full border border-rose-700 px-3 py-1 text-xs text-rose-300"
                onClick={() => setDeleteApiAppError(null)}
              >
                Закрыть
              </button>
            </div>
          )}

          {/* Add / Edit form toggle */}
          {!showApiAppForm && (
            <button
              type="button"
              className="rounded-xl bg-indigo-500 px-4 py-2 text-sm font-semibold text-white"
              onClick={() => {
                setEditingApiApp(null);
                setShowApiAppForm(true);
              }}
            >
              + Add API App
            </button>
          )}

          {showApiAppForm && (
            <form onSubmit={onApiAppSubmit} className="grid gap-3 md:grid-cols-2">
              <div className="space-y-1">
                <label className="label">API ID</label>
                <input
                  className="w-full rounded-xl border border-slate-800 bg-slate-950 px-3 py-2 text-sm disabled:opacity-50"
                  type="number"
                  disabled={!!editingApiApp}
                  {...apiAppForm.register("api_id")}
                />
                {apiAppForm.formState.errors.api_id && (
                  <p className="text-xs text-rose-400">
                    {apiAppForm.formState.errors.api_id.message}
                  </p>
                )}
              </div>

              <div className="space-y-1">
                <label className="label">API Hash</label>
                {editingApiApp ? (
                  <div className="flex gap-2">
                    <input
                      className="w-full rounded-xl border border-slate-800 bg-slate-950 px-3 py-2 text-sm disabled:opacity-50"
                      type="text"
                      disabled
                      value={revealedHash ?? editingApiApp.api_hash}
                    />
                    <button
                      type="button"
                      className="shrink-0 rounded-xl border border-slate-700 px-3 py-2 text-xs"
                      onClick={() => revealHashMutation.mutate(editingApiApp.id)}
                      disabled={revealHashMutation.isPending}
                    >
                      {revealHashMutation.isPending ? "..." : revealedHash ? "Показан" : "Показать"}
                    </button>
                  </div>
                ) : (
                  <>
                    <input
                      className="w-full rounded-xl border border-slate-800 bg-slate-950 px-3 py-2 text-sm"
                      type="password"
                      autoComplete="off"
                      {...apiAppForm.register("api_hash")}
                    />
                    {apiAppForm.formState.errors.api_hash && (
                      <p className="text-xs text-rose-400">
                        {apiAppForm.formState.errors.api_hash.message}
                      </p>
                    )}
                  </>
                )}
              </div>

              <div className="space-y-1">
                <label className="label">App Title</label>
                <input
                  className="w-full rounded-xl border border-slate-800 bg-slate-950 px-3 py-2 text-sm"
                  {...apiAppForm.register("app_title")}
                />
              </div>

              <div className="space-y-1">
                <label className="label">Max Accounts</label>
                <input
                  className="w-full rounded-xl border border-slate-800 bg-slate-950 px-3 py-2 text-sm"
                  type="number"
                  min={1}
                  {...apiAppForm.register("max_accounts")}
                />
                {apiAppForm.formState.errors.max_accounts && (
                  <p className="text-xs text-rose-400">
                    {apiAppForm.formState.errors.max_accounts.message}
                  </p>
                )}
              </div>

              <div className="space-y-1">
                <label className="label">Телефон регистрации</label>
                <input
                  className="w-full rounded-xl border border-slate-800 bg-slate-950 px-3 py-2 text-sm"
                  {...apiAppForm.register("registered_phone")}
                />
              </div>

              <div className="space-y-1">
                <label className="label">Notes</label>
                <input
                  className="w-full rounded-xl border border-slate-800 bg-slate-950 px-3 py-2 text-sm"
                  {...apiAppForm.register("notes")}
                />
              </div>

              {editingApiApp && (
                <div className="flex items-center gap-2">
                  <label className="label">Active</label>
                  <input type="checkbox" {...apiAppForm.register("is_active")} />
                </div>
              )}

              <div className="flex flex-wrap items-center gap-2 md:col-span-2">
                <button
                  type="submit"
                  className="rounded-xl bg-indigo-500 px-4 py-2 text-sm font-semibold text-white"
                  disabled={createApiAppMutation.isPending || updateApiAppMutation.isPending}
                >
                  {editingApiApp ? "Update API App" : "Create API App"}
                </button>
                <button
                  type="button"
                  className="rounded-xl border border-slate-700 px-4 py-2 text-sm"
                  onClick={() => {
                    setShowApiAppForm(false);
                    setEditingApiApp(null);
                  }}
                >
                  Cancel
                </button>
              </div>
            </form>
          )}

          {/* API Apps table */}
          {apiAppsQuery.isLoading ? (
            <LoadingSkeleton rows={3} label="Загрузка API Apps" />
          ) : (
            <div className="space-y-2">
              {(apiAppsQuery.data ?? []).length === 0 && (
                <p className="text-xs text-slate-500">Нет API Apps.</p>
              )}
              {(apiAppsQuery.data ?? []).map((app) => (
                <div
                  key={app.id}
                  className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-slate-800 bg-slate-950 px-3 py-2"
                >
                  <div>
                    <p className="font-semibold">
                      {app.app_title || `App ${app.api_id}`}
                      <span className="ml-2 text-xs font-normal text-slate-500">
                        api_id: {app.api_id}
                      </span>
                    </p>
                    <p className="text-xs text-slate-400">
                      Аккаунтов: {app.current_accounts_count}/{app.max_accounts}
                      {" · "}
                      <span className={app.is_active ? "text-emerald-400" : "text-slate-500"}>
                        {app.is_active ? "Active" : "Inactive"}
                      </span>
                    </p>
                    {app.registered_phone && (
                      <p className="text-xs text-slate-500">Тел: {app.registered_phone}</p>
                    )}
                    {app.notes && (
                      <p className="text-xs text-slate-600">{app.notes}</p>
                    )}
                  </div>
                  <div className="flex items-center gap-2 text-xs">
                    <button
                      type="button"
                      className="rounded-full border border-slate-700 px-3 py-1"
                      onClick={() => {
                        setEditingApiApp(app);
                        setShowApiAppForm(true);
                        setDeleteApiAppError(null);
                      }}
                    >
                      Edit
                    </button>
                    <button
                      type="button"
                      className="rounded-full border border-rose-400 px-3 py-1 text-rose-200"
                      disabled={deleteApiAppMutation.isPending}
                      onClick={() => {
                        if (window.confirm("Удалить API App? Это действие нельзя отменить.")) {
                          deleteApiAppMutation.mutate({ id: app.id });
                        }
                      }}
                    >
                      Delete
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </section>
  );
};

export default Admin;
