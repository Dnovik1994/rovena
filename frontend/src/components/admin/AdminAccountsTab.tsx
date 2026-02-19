import React from "react";
import { useQuery } from "@tanstack/react-query";

import LoadingSkeleton from "../LoadingSkeleton";
import { fetchAdminAccounts } from "../../services/resources";
import { AdminAccount } from "../../types/admin";

type AdminAccountsTabProps = {
  token: string;
};

const AdminAccountsTab = ({ token }: AdminAccountsTabProps): JSX.Element => {
  const accountsQuery = useQuery<{ items: AdminAccount[] }>({
    queryKey: ["admin-accounts"],
    queryFn: () => fetchAdminAccounts(token),
    enabled: Boolean(token),
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
      ))}
    </div>
  );
};

export default AdminAccountsTab;
