import React, { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import EmptyState from "../components/EmptyState";
import {
  fetchAccounts,
  fetchCampaigns,
  fetchDashboardAnalytics,
  fetchProjects,
  fetchSources,
  fetchTargets,
} from "../services/resources";
import { useAuth } from "../stores/auth";
import { AnalyticsPoint } from "../types/analytics";

const buildSparklinePoints = (series: AnalyticsPoint[], width = 120, height = 32): string => {
  if (series.length === 0) {
    return "";
  }
  const maxValue = Math.max(...series.map((point) => point.value), 1);
  return series
    .map((point, index) => {
      const x = series.length === 1 ? width / 2 : (index / (series.length - 1)) * width;
      const y = height - (point.value / maxValue) * height;
      return `${x},${y}`;
    })
    .join(" ");
};

const hasData = (series: AnalyticsPoint[] = []): boolean => series.some((point) => point.value > 0);

const Dashboard = (): JSX.Element => {
  const { token } = useAuth();
  const enabled = useMemo(() => Boolean(token), [token]);

  const projectsQuery = useQuery({
    queryKey: ["dashboard", "projects"],
    queryFn: () => fetchProjects(token ?? ""),
    enabled,
  });
  const accountsQuery = useQuery({
    queryKey: ["dashboard", "accounts"],
    queryFn: () => fetchAccounts(token ?? ""),
    enabled,
  });
  const campaignsQuery = useQuery({
    queryKey: ["dashboard", "campaigns"],
    queryFn: () => fetchCampaigns(token ?? ""),
    enabled,
  });
  const sourcesQuery = useQuery({
    queryKey: ["dashboard", "sources"],
    queryFn: () => fetchSources(token ?? ""),
    enabled,
  });
  const targetsQuery = useQuery({
    queryKey: ["dashboard", "targets"],
    queryFn: () => fetchTargets(token ?? ""),
    enabled,
  });
  const analyticsQuery = useQuery({
    queryKey: ["dashboard", "analytics", 14],
    queryFn: () => fetchDashboardAnalytics(token ?? "", 14),
    enabled,
  });

  const isLoading = [
    projectsQuery,
    accountsQuery,
    campaignsQuery,
    sourcesQuery,
    targetsQuery,
  ].some((query) => query.isLoading);
  const hasError = [
    projectsQuery,
    accountsQuery,
    campaignsQuery,
    sourcesQuery,
    targetsQuery,
  ].some((query) => query.isError);
  const analyticsError = analyticsQuery.isError;

  const accountCounts = useMemo(() => {
    const accounts = accountsQuery.data ?? [];
    return {
      total: accounts.length,
      active: accounts.filter((account) => account.status === "active").length,
      warming: accounts.filter((account) => account.status === "warming").length,
      blocked: accounts.filter((account) => account.status === "blocked").length,
    };
  }, [accountsQuery.data]);

  const campaignCounts = useMemo(() => {
    const campaigns = campaignsQuery.data ?? [];
    return {
      total: campaigns.length,
      active: campaigns.filter((campaign) => campaign.status === "active").length,
      completed: campaigns.filter((campaign) => campaign.status === "completed").length,
    };
  }, [campaignsQuery.data]);

  const recentCampaigns = useMemo(() => {
    const campaigns = campaignsQuery.data ?? [];
    return [...campaigns]
      .sort((a, b) => b.created_at.localeCompare(a.created_at))
      .slice(0, 3);
  }, [campaignsQuery.data]);

  return (
    <section className="page">
      <div>
        <h2 className="page__title">Dashboard</h2>
        <p className="page__subtitle">Сводка по проектам, аккаунтам и кампаниям.</p>
      </div>

      {hasError ? (
        <p className="hint">Не удалось загрузить сводку.</p>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          <div className="card card__body">
            <p className="label">Проекты</p>
            <p className="mt-2 text-2xl font-semibold">
              {isLoading ? "…" : projectsQuery.data?.length ?? 0}
            </p>
            <p className="text-xs text-slate-400">Активные пространства работы</p>
          </div>
          <div className="card card__body">
            <p className="label">Аккаунты</p>
            <p className="mt-2 text-2xl font-semibold">{isLoading ? "…" : accountCounts.total}</p>
            <p className="text-xs text-slate-400">
              Активных: {accountCounts.active} · Прогрев: {accountCounts.warming}
            </p>
          </div>
          <div className="card card__body">
            <p className="label">Кампании</p>
            <p className="mt-2 text-2xl font-semibold">{isLoading ? "…" : campaignCounts.total}</p>
            <p className="text-xs text-slate-400">
              В работе: {campaignCounts.active} · Завершено: {campaignCounts.completed}
            </p>
          </div>
          <div className="card card__body">
            <p className="label">Источники & цели</p>
            <p className="mt-2 text-2xl font-semibold">
              {isLoading
                ? "…"
                : (sourcesQuery.data?.length ?? 0) + (targetsQuery.data?.length ?? 0)}
            </p>
            <p className="text-xs text-slate-400">
              Sources: {sourcesQuery.data?.length ?? 0} · Targets: {targetsQuery.data?.length ?? 0}
            </p>
          </div>
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-[2fr_1fr]">
        <div className="card card__body">
          <h3 className="text-base font-semibold">Последние кампании</h3>
          {isLoading ? (
            <p className="mt-3 text-sm text-slate-400">Загружаем кампании…</p>
          ) : recentCampaigns.length === 0 ? (
            <p className="mt-3 text-sm text-slate-400">Кампаний пока нет.</p>
          ) : (
            <ul className="mt-4 space-y-3 text-sm">
              {recentCampaigns.map((campaign) => (
                <li key={campaign.id} className="flex items-center justify-between">
                  <span className="font-medium">{campaign.name}</span>
                  <span className="text-xs text-slate-400">{campaign.status}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
        <div className="card card__body">
          <h3 className="text-base font-semibold">Быстрые действия</h3>
          <div className="mt-3 flex flex-col gap-2 text-sm">
            <Link className="rounded-xl border border-slate-700 px-3 py-2 text-left" to="/projects">
              Создать проект
            </Link>
            <Link className="rounded-xl border border-slate-700 px-3 py-2 text-left" to="/accounts">
              Добавить аккаунт
            </Link>
            <Link className="rounded-xl border border-slate-700 px-3 py-2 text-left" to="/campaigns">
              Запустить кампанию
            </Link>
          </div>
          {accountCounts.blocked > 0 && (
            <p className="mt-3 text-xs text-rose-400">
              Есть заблокированные аккаунты: {accountCounts.blocked}.
            </p>
          )}
        </div>
      </div>

      <div className="card card__body">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="text-base font-semibold">Динамика за 14 дней</h3>
          {analyticsQuery.data && (
            <span className="text-xs text-slate-400">
              Всего аккаунтов: {analyticsQuery.data.totals.accounts} · кампаний:{" "}
              {analyticsQuery.data.totals.campaigns}
            </span>
          )}
        </div>
        {analyticsQuery.isLoading ? (
          <p className="mt-3 text-sm text-slate-400">Собираем аналитику…</p>
        ) : analyticsError ? (
          <p className="mt-3 text-sm text-rose-400">Не удалось загрузить аналитику.</p>
        ) : (
          <div className="mt-4 grid gap-4 md:grid-cols-2">
            <div className="rounded-2xl border border-slate-800 bg-slate-950/30 p-4">
              <p className="label">Новые аккаунты</p>
              {hasData(analyticsQuery.data?.accounts_created) ? (
                <svg className="mt-3 h-10 w-full" viewBox="0 0 120 32" preserveAspectRatio="none">
                  <polyline
                    fill="none"
                    stroke="#6366f1"
                    strokeWidth="2"
                    points={buildSparklinePoints(analyticsQuery.data?.accounts_created ?? [])}
                  />
                </svg>
              ) : (
                <p className="mt-3 text-sm text-slate-400">Данных пока нет.</p>
              )}
            </div>
            <div className="rounded-2xl border border-slate-800 bg-slate-950/30 p-4">
              <p className="label">Новые кампании</p>
              {hasData(analyticsQuery.data?.campaigns_created) ? (
                <svg className="mt-3 h-10 w-full" viewBox="0 0 120 32" preserveAspectRatio="none">
                  <polyline
                    fill="none"
                    stroke="#22c55e"
                    strokeWidth="2"
                    points={buildSparklinePoints(analyticsQuery.data?.campaigns_created ?? [])}
                  />
                </svg>
              ) : (
                <p className="mt-3 text-sm text-slate-400">Данных пока нет.</p>
              )}
            </div>
          </div>
        )}
      </div>

      {!isLoading && projectsQuery.data?.length === 0 && (
        <EmptyState
          title="Пока нет активности"
          description="Добавьте проект и источники, чтобы увидеть статистику."
        />
      )}
    </section>
  );
};

export default Dashboard;
