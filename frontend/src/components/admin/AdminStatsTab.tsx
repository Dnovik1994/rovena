import React from "react";
import { useQuery } from "@tanstack/react-query";

import ErrorState from "../ErrorState";
import LoadingSkeleton from "../LoadingSkeleton";
import { fetchAdminStats } from "../../services/resources";
import { AdminStats } from "../../types/admin";

type AdminStatsTabProps = {
  token: string;
};

const AdminStatsTab = ({ token }: AdminStatsTabProps): JSX.Element => {
  const statsQuery = useQuery<AdminStats>({
    queryKey: ["admin-stats"],
    queryFn: () => fetchAdminStats(token),
    enabled: Boolean(token),
  });

  if (statsQuery.isLoading) {
    return <LoadingSkeleton rows={3} label="Загрузка метрик" />;
  }

  if (statsQuery.isError) {
    return <ErrorState title="Ошибка" description="Нет доступа к админ-статистике." />;
  }

  const stats = statsQuery.data;
  if (!stats) return <></>;

  return (
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
  );
};

export default AdminStatsTab;
