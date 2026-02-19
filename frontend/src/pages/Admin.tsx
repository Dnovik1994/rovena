import React, { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import AdminApiAppsTab from "../components/admin/AdminApiAppsTab";
import AdminTariffsTab from "../components/admin/AdminTariffsTab";
import AdminUsersTab from "../components/admin/AdminUsersTab";
import ErrorState from "../components/ErrorState";
import LoadingSkeleton from "../components/LoadingSkeleton";
import {
  fetchAdminAccounts,
  fetchAdminProxies,
  fetchAdminStats,
  fetchAdminTariffs,
  fetchAdminUsers,
  fetchApiApps,
  validateProxy,
} from "../services/resources";
import { useAuth } from "../stores/auth";
import { AdminAccount, AdminProxy, AdminStats } from "../types/admin";

type TabKey = "stats" | "users" | "tariffs" | "proxies" | "accounts" | "api-apps";

const Admin = (): JSX.Element => {
  const { token } = useAuth();
  const [activeTab, setActiveTab] = useState<TabKey>("stats");
  const queryClient = useQueryClient();

  const enabled = useMemo(() => Boolean(token), [token]);

  const statsQuery = useQuery<AdminStats>({
    queryKey: ["admin-stats"],
    queryFn: () => fetchAdminStats(token ?? ""),
    enabled,
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
        queryKey: ["admin-users", "", ""],
        queryFn: () => fetchAdminUsers(token ?? "", "", ""),
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
        queryKey: ["admin-users", "", ""],
        queryFn: () => fetchAdminUsers(token ?? "", "", ""),
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
  }, [activeTab, enabled, queryClient, token]);

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

  const validateProxyMutation = useMutation({
    mutationFn: (payload: { id: number }) => validateProxy(token ?? "", payload.id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin-proxies"] });
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

      {activeTab === "users" && <AdminUsersTab token={token} />}

      {activeTab === "tariffs" && <AdminTariffsTab token={token} />}

      {activeTab === "proxies" && (
        <div className="space-y-2 rounded-2xl border border-slate-800 bg-slate-900/60 p-4 text-sm">
          {proxiesQuery.isLoading ? (
            <LoadingSkeleton rows={3} label="Загрузка прокси" />
          ) : proxiesQuery.isError ? (
            <div className="text-red-500 p-4 text-center">
              Ошибка загрузки прокси.{" "}
              <button type="button" onClick={() => proxiesQuery.refetch()} className="underline">
                Повторить
              </button>
            </div>
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
          ) : accountsQuery.isError ? (
            <div className="text-red-500 p-4 text-center">
              Ошибка загрузки аккаунтов.{" "}
              <button type="button" onClick={() => accountsQuery.refetch()} className="underline">
                Повторить
              </button>
            </div>
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

      {activeTab === "api-apps" && <AdminApiAppsTab token={token} />}
    </section>
  );
};

export default Admin;
