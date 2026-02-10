import React, { useEffect, useMemo, useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import ErrorState from "../components/ErrorState";
import LoadingSkeleton from "../components/LoadingSkeleton";
import {
  createAdminTariff,
  deleteAdminTariff,
  fetchAdminAccounts,
  fetchAdminProxies,
  fetchAdminStats,
  fetchAdminTariffs,
  fetchAdminUsers,
  updateAdminTariff,
  updateAdminUser,
  updateAdminUserTariff,
  validateProxy,
} from "../services/resources";
import { useAuth } from "../stores/auth";
import { AdminAccount, AdminProxy, AdminStats, AdminTariff, AdminUser } from "../types/admin";

type TabKey = "stats" | "users" | "tariffs" | "proxies" | "accounts";

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

const Admin = (): JSX.Element => {
  const { token } = useAuth();
  const [activeTab, setActiveTab] = useState<TabKey>("stats");
  const [search, setSearch] = useState("");
  const [tariffFilter, setTariffFilter] = useState("");
  const [editingTariff, setEditingTariff] = useState<AdminTariff | null>(null);
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

  return (
    <section className="page">
      <div>
        <h2 className="page__title">Admin Dashboard</h2>
        <p className="page__subtitle">Базовые метрики и контроль доступов.</p>
      </div>

      <div className="flex flex-wrap gap-2">
        {(["stats", "users", "tariffs", "proxies", "accounts"] as TabKey[]).map((tab) => (
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
                          role: user.role === "admin" ? "user" : "admin",
                        })
                      }
                      className="rounded-full border border-indigo-400 px-3 py-1 text-indigo-200"
                    >
                      Toggle Admin
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
                      onClick={() => deleteTariffMutation.mutate({ id: tariff.id })}
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
                <span className="text-xs text-slate-400">
                  Proxy: {account.proxy ? `${account.proxy.host}:${account.proxy.port}` : "none"}
                </span>
              </div>
            ))
          )}
        </div>
      )}
    </section>
  );
};

export default Admin;
