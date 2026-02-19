import React, { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import LoadingSkeleton from "../LoadingSkeleton";
import {
  createApiApp,
  deleteApiApp,
  fetchApiApps,
  revealApiAppHash,
  updateApiApp,
} from "../../services/resources";
import { AdminApiApp } from "../../types/admin";

type ApiAppFormValues = {
  api_id: number;
  api_hash: string;
  app_title: string;
  max_accounts: number;
  is_active: boolean;
  registered_phone: string;
  notes: string;
};

const apiAppSchema = z.object({
  api_id: z.coerce.number().int().positive("Укажите api_id"),
  api_hash: z.string().min(1, "api_hash обязателен"),
  app_title: z.string(),
  max_accounts: z.coerce.number().int().min(1, "Минимум 1"),
  is_active: z.boolean(),
  registered_phone: z.string(),
  notes: z.string(),
});

type AdminApiAppsTabProps = {
  token: string;
};

const AdminApiAppsTab = ({ token }: AdminApiAppsTabProps): JSX.Element => {
  const [editingApiApp, setEditingApiApp] = useState<AdminApiApp | null>(null);
  const [showApiAppForm, setShowApiAppForm] = useState(false);
  const [createdApiHash, setCreatedApiHash] = useState<string | null>(null);
  const [deleteApiAppError, setDeleteApiAppError] = useState<string | null>(null);
  const [revealedHash, setRevealedHash] = useState<string | null>(null);
  const queryClient = useQueryClient();

  const apiAppForm = useForm<ApiAppFormValues>({
    resolver: zodResolver(apiAppSchema),
    defaultValues: {
      api_id: undefined as unknown as number,
      api_hash: "",
      app_title: "",
      max_accounts: 3,
      is_active: true,
      registered_phone: "",
      notes: "",
    },
  });

  useEffect(() => {
    if (editingApiApp) {
      apiAppForm.reset({
        api_id: editingApiApp.api_id,
        api_hash: editingApiApp.api_hash,
        app_title: editingApiApp.app_title ?? "",
        max_accounts: editingApiApp.max_accounts,
        is_active: editingApiApp.is_active,
        registered_phone: editingApiApp.registered_phone ?? "",
        notes: editingApiApp.notes ?? "",
      });
      setRevealedHash(null);
      return;
    }
    apiAppForm.reset({
      api_id: undefined as unknown as number,
      api_hash: "",
      app_title: "",
      max_accounts: 3,
      is_active: true,
      registered_phone: "",
      notes: "",
    });
    setRevealedHash(null);
  }, [editingApiApp, apiAppForm]);

  const apiAppsQuery = useQuery<AdminApiApp[]>({
    queryKey: ["admin-api-apps"],
    queryFn: () => fetchApiApps(token),
    enabled: Boolean(token),
  });

  const createApiAppMutation = useMutation({
    mutationFn: (payload: {
      api_id: number;
      api_hash: string;
      app_title?: string;
      max_accounts?: number;
      registered_phone?: string;
      notes?: string;
    }) => createApiApp(token, payload),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ["admin-api-apps"] });
      setCreatedApiHash(data.api_hash);
      setShowApiAppForm(false);
      setEditingApiApp(null);
    },
  });

  const updateApiAppMutation = useMutation({
    mutationFn: (payload: {
      id: number;
      data: {
        app_title?: string | null;
        max_accounts?: number;
        is_active?: boolean;
        registered_phone?: string | null;
        notes?: string | null;
      };
    }) => updateApiApp(token, payload.id, payload.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin-api-apps"] });
      setShowApiAppForm(false);
      setEditingApiApp(null);
    },
  });

  const deleteApiAppMutation = useMutation({
    mutationFn: (payload: { id: number }) => deleteApiApp(token, payload.id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin-api-apps"] });
      setDeleteApiAppError(null);
    },
    onError: (error: unknown) => {
      const err = error as { status?: number; message?: string };
      if (err?.status === 409) {
        setDeleteApiAppError("Невозможно удалить: есть привязанные аккаунты.");
      } else {
        setDeleteApiAppError(err?.message || "Ошибка при удалении.");
      }
    },
  });

  const revealHashMutation = useMutation({
    mutationFn: (id: number) => revealApiAppHash(token, id),
    onSuccess: (data) => {
      setRevealedHash(data.api_hash);
    },
  });

  const onApiAppSubmit = apiAppForm.handleSubmit((values) => {
    if (editingApiApp) {
      updateApiAppMutation.mutate({
        id: editingApiApp.id,
        data: {
          app_title: values.app_title || null,
          max_accounts: values.max_accounts,
          is_active: values.is_active,
          registered_phone: values.registered_phone || null,
          notes: values.notes || null,
        },
      });
      return;
    }
    const payload: {
      api_id: number;
      api_hash: string;
      app_title?: string;
      max_accounts?: number;
      registered_phone?: string;
      notes?: string;
    } = {
      api_id: values.api_id,
      api_hash: values.api_hash,
      max_accounts: values.max_accounts,
    };
    if (values.app_title) payload.app_title = values.app_title;
    if (values.registered_phone) payload.registered_phone = values.registered_phone;
    if (values.notes) payload.notes = values.notes;
    createApiAppMutation.mutate(payload);
  });

  return (
    <div className="space-y-4 rounded-2xl border border-slate-800 bg-slate-900/60 p-4 text-sm">
      {/* Created hash alert */}
      {createdApiHash && (
        <div className="rounded-xl border border-emerald-700 bg-emerald-950/60 px-4 py-3">
          <p className="font-semibold text-emerald-300">
            API App создан. Сохраните api_hash — он больше не будет показан полностью:
          </p>
          <p className="mt-1 break-all font-mono text-sm text-emerald-200">{createdApiHash}</p>
          <button
            type="button"
            className="mt-2 rounded-full border border-emerald-700 px-3 py-1 text-xs text-emerald-300"
            onClick={() => setCreatedApiHash(null)}
          >
            Закрыть
          </button>
        </div>
      )}

      {/* Delete error alert */}
      {deleteApiAppError && (
        <div className="rounded-xl border border-rose-700 bg-rose-950/60 px-4 py-3">
          <p className="text-sm text-rose-300">{deleteApiAppError}</p>
          <button
            type="button"
            className="mt-2 rounded-full border border-rose-700 px-3 py-1 text-xs text-rose-300"
            onClick={() => setDeleteApiAppError(null)}
          >
            Закрыть
          </button>
        </div>
      )}

      {/* Add / Edit form toggle */}
      {!showApiAppForm && (
        <button
          type="button"
          className="rounded-xl bg-indigo-500 px-4 py-2 text-sm font-semibold text-white"
          onClick={() => {
            setEditingApiApp(null);
            setShowApiAppForm(true);
          }}
        >
          + Add API App
        </button>
      )}

      {showApiAppForm && (
        <form onSubmit={onApiAppSubmit} className="grid gap-3 md:grid-cols-2">
          <div className="space-y-1">
            <label className="label">API ID</label>
            <input
              className="w-full rounded-xl border border-slate-800 bg-slate-950 px-3 py-2 text-sm disabled:opacity-50"
              type="number"
              disabled={!!editingApiApp}
              {...apiAppForm.register("api_id")}
            />
            {apiAppForm.formState.errors.api_id && (
              <p className="text-xs text-rose-400">
                {apiAppForm.formState.errors.api_id.message}
              </p>
            )}
          </div>

          <div className="space-y-1">
            <label className="label">API Hash</label>
            {editingApiApp ? (
              <div className="flex gap-2">
                <input
                  className="w-full rounded-xl border border-slate-800 bg-slate-950 px-3 py-2 text-sm disabled:opacity-50"
                  type="text"
                  disabled
                  value={revealedHash ?? editingApiApp.api_hash}
                />
                <button
                  type="button"
                  className="shrink-0 rounded-xl border border-slate-700 px-3 py-2 text-xs"
                  onClick={() => revealHashMutation.mutate(editingApiApp.id)}
                  disabled={revealHashMutation.isPending}
                >
                  {revealHashMutation.isPending ? "..." : revealedHash ? "Показан" : "Показать"}
                </button>
              </div>
            ) : (
              <>
                <input
                  className="w-full rounded-xl border border-slate-800 bg-slate-950 px-3 py-2 text-sm"
                  type="password"
                  autoComplete="off"
                  {...apiAppForm.register("api_hash")}
                />
                {apiAppForm.formState.errors.api_hash && (
                  <p className="text-xs text-rose-400">
                    {apiAppForm.formState.errors.api_hash.message}
                  </p>
                )}
              </>
            )}
          </div>

          <div className="space-y-1">
            <label className="label">App Title</label>
            <input
              className="w-full rounded-xl border border-slate-800 bg-slate-950 px-3 py-2 text-sm"
              {...apiAppForm.register("app_title")}
            />
          </div>

          <div className="space-y-1">
            <label className="label">Max Accounts</label>
            <input
              className="w-full rounded-xl border border-slate-800 bg-slate-950 px-3 py-2 text-sm"
              type="number"
              min={1}
              {...apiAppForm.register("max_accounts")}
            />
            {apiAppForm.formState.errors.max_accounts && (
              <p className="text-xs text-rose-400">
                {apiAppForm.formState.errors.max_accounts.message}
              </p>
            )}
          </div>

          <div className="space-y-1">
            <label className="label">Телефон регистрации</label>
            <input
              className="w-full rounded-xl border border-slate-800 bg-slate-950 px-3 py-2 text-sm"
              {...apiAppForm.register("registered_phone")}
            />
          </div>

          <div className="space-y-1">
            <label className="label">Notes</label>
            <input
              className="w-full rounded-xl border border-slate-800 bg-slate-950 px-3 py-2 text-sm"
              {...apiAppForm.register("notes")}
            />
          </div>

          {editingApiApp && (
            <div className="flex items-center gap-2">
              <label className="label">Active</label>
              <input type="checkbox" {...apiAppForm.register("is_active")} />
            </div>
          )}

          <div className="flex flex-wrap items-center gap-2 md:col-span-2">
            <button
              type="submit"
              className="rounded-xl bg-indigo-500 px-4 py-2 text-sm font-semibold text-white"
              disabled={createApiAppMutation.isPending || updateApiAppMutation.isPending}
            >
              {editingApiApp ? "Update API App" : "Create API App"}
            </button>
            <button
              type="button"
              className="rounded-xl border border-slate-700 px-4 py-2 text-sm"
              onClick={() => {
                setShowApiAppForm(false);
                setEditingApiApp(null);
              }}
            >
              Cancel
            </button>
          </div>
        </form>
      )}

      {/* API Apps table */}
      {apiAppsQuery.isLoading ? (
        <LoadingSkeleton rows={3} label="Загрузка API Apps" />
      ) : (
        <div className="space-y-2">
          {(apiAppsQuery.data ?? []).length === 0 && (
            <p className="text-xs text-slate-500">Нет API Apps.</p>
          )}
          {(apiAppsQuery.data ?? []).map((app) => (
            <div
              key={app.id}
              className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-slate-800 bg-slate-950 px-3 py-2"
            >
              <div>
                <p className="font-semibold">
                  {app.app_title || `App ${app.api_id}`}
                  <span className="ml-2 text-xs font-normal text-slate-500">
                    api_id: {app.api_id}
                  </span>
                </p>
                <p className="text-xs text-slate-400">
                  Аккаунтов: {app.current_accounts_count}/{app.max_accounts}
                  {" · "}
                  <span className={app.is_active ? "text-emerald-400" : "text-slate-500"}>
                    {app.is_active ? "Active" : "Inactive"}
                  </span>
                </p>
                {app.registered_phone && (
                  <p className="text-xs text-slate-500">Тел: {app.registered_phone}</p>
                )}
                {app.notes && (
                  <p className="text-xs text-slate-600">{app.notes}</p>
                )}
              </div>
              <div className="flex items-center gap-2 text-xs">
                <button
                  type="button"
                  className="rounded-full border border-slate-700 px-3 py-1"
                  onClick={() => {
                    setEditingApiApp(app);
                    setShowApiAppForm(true);
                    setDeleteApiAppError(null);
                  }}
                >
                  Edit
                </button>
                <button
                  type="button"
                  className="rounded-full border border-rose-400 px-3 py-1 text-rose-200"
                  disabled={deleteApiAppMutation.isPending}
                  onClick={() => {
                    if (window.confirm("Удалить API App? Это действие нельзя отменить.")) {
                      deleteApiAppMutation.mutate({ id: app.id });
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

export default AdminApiAppsTab;
