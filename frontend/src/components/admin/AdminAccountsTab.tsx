import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import LoadingSkeleton from "../LoadingSkeleton";
import { fetchAdminAccounts } from "../../services/resources";
import { AdminAccount } from "../../types/admin";
import { apiFetch } from "../../shared/api/client";

type AdminAccountsTabProps = {
  token: string;
};

const toggleTrusted = (token: string, id: number, trusted: boolean) =>
  apiFetch<AdminAccount>(`/admin/warming/accounts/${id}/trusted`, {
    method: "PATCH",
    body: JSON.stringify({ is_trusted: trusted }),
  }, token);

const formatWarmingDay = (account: AdminAccount): string => {
  if (account.warming_day === undefined || account.warming_day === null) return "—";
  if (account.warming_day > 15) return "Active";
  if (account.warming_day < 0) return "Rest";
  return String(account.warming_day);
};

const AdminAccountsTab = ({ token }: AdminAccountsTabProps): JSX.Element => {
  const qc = useQueryClient();

  const accountsQuery = useQuery<{ items: AdminAccount[] }>({
    queryKey: ["admin-accounts"],
    queryFn: () => fetchAdminAccounts(token),
    enabled: Boolean(token),
  });

  const trustedMut = useMutation({
    mutationFn: (payload: { id: number; trusted: boolean }) =>
      toggleTrusted(token, payload.id, payload.trusted),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin-accounts"] });
      window.dispatchEvent(
        new CustomEvent("app:toast", {
          detail: { message: "Trusted status updated" },
        }),
      );
    },
  });

  if (accountsQuery.isLoading) {
    return <LoadingSkeleton rows={3} label="Загрузка аккаунтов" />;
  }

  if (accountsQuery.isError) {
    return (
      <div className="text-red-500 p-4 text-center">
        Ошибка загрузки аккаунтов.{" "}
        <button type="button" onClick={() => accountsQuery.refetch()} className="underline">
          Повторить
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-2 rounded-2xl border border-slate-800 bg-slate-900/60 p-4 text-sm">
      {accountsQuery.data?.items.map((account) => (
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
              {" · "}
              Day: {formatWarmingDay(account)}
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
            <label className="flex items-center gap-1 cursor-pointer">
              <input
                type="checkbox"
                checked={account.is_trusted ?? false}
                disabled={trustedMut.isPending}
                onChange={(e) =>
                  trustedMut.mutate({ id: account.id, trusted: e.target.checked })
                }
              />
              <span className={account.is_trusted ? "text-green-400" : "text-slate-500"}>
                Trusted
              </span>
            </label>
          </div>
        </div>
      ))}
    </div>
  );
};

export default AdminAccountsTab;
