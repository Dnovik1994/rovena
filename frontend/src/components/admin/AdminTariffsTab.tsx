import React, { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import LoadingSkeleton from "../LoadingSkeleton";
import {
  createAdminTariff,
  deleteAdminTariff,
  updateAdminTariff,
} from "../../services/resources";
import { AdminTariff } from "../../types/admin";
import { useAdminTariffs } from "./hooks/useAdminTariffs";

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

type AdminTariffsTabProps = {
  token: string;
};

const AdminTariffsTab = ({ token }: AdminTariffsTabProps): JSX.Element => {
  const [editingTariff, setEditingTariff] = useState<AdminTariff | null>(null);
  const queryClient = useQueryClient();

  const tariffsQuery = useAdminTariffs(token);
  const tariffs = tariffsQuery.data ?? [];

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

  const createTariffMutation = useMutation({
    mutationFn: (payload: TariffFormValues) => createAdminTariff(token, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin-tariffs"] });
      setEditingTariff(null);
    },
  });

  const updateTariffMutation = useMutation({
    mutationFn: (payload: { id: number; data: TariffFormValues }) =>
      updateAdminTariff(token, payload.id, payload.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin-tariffs"] });
      setEditingTariff(null);
    },
  });

  const deleteTariffMutation = useMutation({
    mutationFn: (payload: { id: number }) => deleteAdminTariff(token, payload.id),
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

  const onTariffSubmit = tariffForm.handleSubmit((values) => {
    if (editingTariff) {
      updateTariffMutation.mutate({ id: editingTariff.id, data: values });
      return;
    }
    createTariffMutation.mutate(values);
  });

  return (
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
          {tariffForm.formState.errors.max_accounts && (
            <span className="text-red-500">{tariffForm.formState.errors.max_accounts.message}</span>
          )}
        </div>
        <div className="space-y-1">
          <label className="label">Max invites / day</label>
          <input
            className="w-full rounded-xl border border-slate-800 bg-slate-950 px-3 py-2 text-sm"
            type="number"
            {...tariffForm.register("max_invites_day")}
          />
          {tariffForm.formState.errors.max_invites_day && (
            <span className="text-red-500">{tariffForm.formState.errors.max_invites_day.message}</span>
          )}
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
      ) : tariffsQuery.isError ? (
        <div className="text-red-500 p-4 text-center">
          Ошибка загрузки тарифов.{" "}
          <button type="button" onClick={() => tariffsQuery.refetch()} className="underline">
            Повторить
          </button>
        </div>
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
  );
};

export default AdminTariffsTab;
