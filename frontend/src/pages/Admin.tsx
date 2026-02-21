import React, { useEffect, useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import AdminAccountsTab from "../components/admin/AdminAccountsTab";
import AdminApiAppsTab from "../components/admin/AdminApiAppsTab";
import AdminProxiesTab from "../components/admin/AdminProxiesTab";
import AdminStatsTab from "../components/admin/AdminStatsTab";
import AdminTariffsTab from "../components/admin/AdminTariffsTab";
import AdminUsersTab from "../components/admin/AdminUsersTab";
import AdminWarmingTab from "../components/admin/AdminWarmingTab";
import {
  fetchAdminAccounts,
  fetchAdminProxies,
  fetchAdminTariffs,
  fetchAdminUsers,
  fetchApiApps,
} from "../services/resources";
import { useAuth } from "../stores/auth";

type TabKey = "stats" | "users" | "tariffs" | "proxies" | "accounts" | "api-apps" | "warming";

const Admin = (): JSX.Element => {
  const { token } = useAuth();
  const [activeTab, setActiveTab] = useState<TabKey>("stats");
  const queryClient = useQueryClient();

  const enabled = useMemo(() => Boolean(token), [token]);

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

  if (!token) {
    return <p className="page__subtitle">Нужна авторизация.</p>;
  }

  return (
    <section className="page">
      <div>
        <h2 className="page__title">Admin Dashboard</h2>
        <p className="page__subtitle">Базовые метрики и контроль доступов.</p>
      </div>

      <div className="flex flex-wrap gap-2">
        {(["stats", "users", "tariffs", "proxies", "accounts", "api-apps", "warming"] as TabKey[]).map((tab) => (
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

      {activeTab === "stats" && <AdminStatsTab token={token} />}
      {activeTab === "users" && <AdminUsersTab token={token} />}
      {activeTab === "tariffs" && <AdminTariffsTab token={token} />}
      {activeTab === "proxies" && <AdminProxiesTab token={token} />}
      {activeTab === "accounts" && <AdminAccountsTab token={token} />}
      {activeTab === "api-apps" && <AdminApiAppsTab token={token} />}
      {activeTab === "warming" && <AdminWarmingTab token={token} />}
    </section>
  );
};

export default Admin;
