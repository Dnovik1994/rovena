import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import LoadingSkeleton from "../LoadingSkeleton";
import { fetchAdminProxies, validateProxy } from "../../services/resources";
import { AdminProxy } from "../../types/admin";

type AdminProxiesTabProps = {
  token: string;
};

const AdminProxiesTab = ({ token }: AdminProxiesTabProps): JSX.Element => {
  const queryClient = useQueryClient();

  const proxiesQuery = useQuery<{ items: AdminProxy[] }>({
    queryKey: ["admin-proxies"],
    queryFn: () => fetchAdminProxies(token),
    enabled: Boolean(token),
  });

  const validateProxyMutation = useMutation({
    mutationFn: (payload: { id: number }) => validateProxy(token, payload.id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin-proxies"] });
    },
  });

  if (proxiesQuery.isLoading) {
    return <LoadingSkeleton rows={3} label="Загрузка прокси" />;
  }

  if (proxiesQuery.isError) {
    return (
      <div className="text-red-500 p-4 text-center">
        Ошибка загрузки прокси.{" "}
        <button type="button" onClick={() => proxiesQuery.refetch()} className="underline">
          Повторить
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-2 rounded-2xl border border-slate-800 bg-slate-900/60 p-4 text-sm">
      {proxiesQuery.data?.items.map((proxy) => (
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
      ))}
    </div>
  );
};

export default AdminProxiesTab;
