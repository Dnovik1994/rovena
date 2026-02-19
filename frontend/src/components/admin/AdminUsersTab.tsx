import React, { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import LoadingSkeleton from "../LoadingSkeleton";
import { fetchAdminUsers, updateAdminUser, updateAdminUserTariff } from "../../services/resources";
import { AdminUser } from "../../types/admin";
import { useAdminTariffs } from "./hooks/useAdminTariffs";

type AdminUsersTabProps = {
  token: string;
};

const AdminUsersTab = ({ token }: AdminUsersTabProps): JSX.Element => {
  const [search, setSearch] = useState("");
  const [tariffFilter, setTariffFilter] = useState("");
  const queryClient = useQueryClient();

  const tariffsQuery = useAdminTariffs(token);
  const tariffs = tariffsQuery.data ?? [];

  const usersQuery = useQuery<{ items: AdminUser[] }>({
    queryKey: ["admin-users", search, tariffFilter],
    queryFn: () => fetchAdminUsers(token, search, tariffFilter),
    enabled: Boolean(token),
  });

  const updateUserMutation = useMutation({
    mutationFn: (payload: { id: number; is_active?: boolean; role?: string | null }) =>
      updateAdminUser(token, payload.id, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin-users"] });
    },
  });

  const updateUserTariffMutation = useMutation({
    mutationFn: (payload: { id: number; tariff_id: number }) =>
      updateAdminUserTariff(token, payload.id, payload.tariff_id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin-users"] });
    },
  });

  return (
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
      ) : usersQuery.isError ? (
        <div className="text-red-500 p-4 text-center">
          Ошибка загрузки пользователей.{" "}
          <button type="button" onClick={() => usersQuery.refetch()} className="underline">
            Повторить
          </button>
        </div>
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
  );
};

export default AdminUsersTab;
