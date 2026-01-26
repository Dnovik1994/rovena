import React, { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";

import EmptyState from "../components/EmptyState";
import SkeletonList from "../components/SkeletonList";
import {
  createAccount,
  fetchAccounts,
  regenerateDeviceConfig,
  startAccountWarming,
  verifyAccount,
} from "../services/resources";
import { connectStatusSocket, StatusMessage } from "../services/websocket";
import { useAuth } from "../stores/auth";
import { Account } from "../types/account";

const schema = z.object({
  user_id: z.coerce.number().int().positive(),
  telegram_id: z.coerce.number().int().positive(),
  phone: z.string().optional(),
  username: z.string().optional(),
  first_name: z.string().optional(),
  status: z.enum(["new", "warming", "active", "cooldown", "blocked", "verified"]),
});

type FormValues = z.infer<typeof schema>;

const statusStyles: Record<string, string> = {
  new: "text-slate-300",
  warming: "text-amber-400",
  active: "text-emerald-400",
  cooldown: "text-orange-400",
  blocked: "text-rose-400",
  verified: "text-sky-400",
};

const Accounts = (): JSX.Element => {
  const { token } = useAuth();
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [verifyMessage, setVerifyMessage] = useState<string | null>(null);
  const [selectedAccountId, setSelectedAccountId] = useState<number | null>(null);

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
    reset,
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { status: "new" },
  });

  const load = async () => {
    if (!token) {
      setLoading(false);
      return;
    }
    try {
      setLoading(true);
      const data = await fetchAccounts(token);
      setAccounts(data);
    } catch (err) {
      setError("Не удалось загрузить аккаунты.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, [token]);

  useEffect(() => {
    const telegram = (window as unknown as { Telegram?: { WebApp?: { MainButton?: { show: () => void; hide: () => void; setText: (text: string) => void; onClick: (cb: () => void) => void; offClick: (cb: () => void) => void } } } }).Telegram?.WebApp;
    const mainButton = telegram?.MainButton;
    if (!mainButton) {
      return;
    }

    const selected = accounts.find((item) => item.id === selectedAccountId);
    if (!selected || selected.status === "verified") {
      mainButton.hide();
      return;
    }

    const handler = () => {
      void handleVerify(selected.id);
    };

    mainButton.setText("Verify Account");
    mainButton.show();
    mainButton.onClick(handler);
    return () => {
      mainButton.offClick(handler);
    };
  }, [accounts, selectedAccountId]);

  useEffect(() => {
    if (!token) {
      return;
    }
    const socket = connectStatusSocket(token, (message: StatusMessage) => {
      if (message.type === "account_update") {
        setAccounts((prev) =>
          prev.map((item) =>
            item.id === message.account_id
              ? {
                  ...item,
                  status: message.status as Account["status"],
                  warming_actions_completed:
                    message.actions_completed ?? item.warming_actions_completed,
                  target_warming_actions: message.target_actions ?? item.target_warming_actions,
                  cooldown_until: message.cooldown_until ?? item.cooldown_until,
                }
              : item
          )
        );
      }
    });

    return () => {
      socket.close();
    };
  }, [token]);

  const onSubmit = async (values: FormValues) => {
    if (!token) {
      setError("Нужна авторизация.");
      return;
    }
    try {
      const created = await createAccount(token, values);
      setAccounts((prev) => [created, ...prev]);
      reset({
        user_id: values.user_id,
        telegram_id: undefined,
        phone: "",
        username: "",
        first_name: "",
        status: values.status,
      });
      setError(null);
      setVerifyMessage(null);
    } catch (err) {
      setError("Не удалось создать аккаунт.");
    }
  };

  const handleStartWarming = async (accountId: number) => {
    if (!token) {
      return;
    }
    const updated = await startAccountWarming(token, accountId);
    setAccounts((prev) => prev.map((item) => (item.id === accountId ? updated : item)));
  };

  const handleRegenerateDevice = async (accountId: number) => {
    if (!token) {
      return;
    }
    const updated = await regenerateDeviceConfig(token, accountId);
    setAccounts((prev) => prev.map((item) => (item.id === accountId ? updated : item)));
  };

  const handleVerify = async (accountId: number) => {
    if (!token) {
      return;
    }
    const result = await verifyAccount(token, accountId);
    if (result.needs_password) {
      setVerifyMessage("Нужен пароль 2FA для завершения проверки.");
      return;
    }
    if (result.account) {
      setAccounts((prev) => prev.map((item) => (item.id === accountId ? result.account : item)));
      setVerifyMessage("Аккаунт подтверждён через Telegram.");
    }
  };

  const formatProgress = (account: Account) => {
    const target = account.target_warming_actions || 0;
    if (!target) {
      return { percent: 0, label: "0 / 0" };
    }
    const percent = Math.min(100, Math.round((account.warming_actions_completed / target) * 100));
    return { percent, label: `${account.warming_actions_completed} / ${target}` };
  };

  return (
    <section className="space-y-6">
      <div>
        <h2 className="text-xl font-semibold">Accounts</h2>
        <p className="text-sm text-slate-400">Назначенные аккаунты Telegram.</p>
      </div>

      <form onSubmit={handleSubmit(onSubmit)} className="space-y-3 rounded-2xl bg-slate-900/60 p-4">
        <div>
          <label className="text-xs uppercase text-slate-400">User ID</label>
          <input
            className="mt-1 w-full rounded-xl border border-slate-800 bg-slate-950 px-3 py-2 text-sm"
            type="number"
            {...register("user_id")}
          />
          {errors.user_id && (
            <p className="text-xs text-rose-400">Укажите user_id.</p>
          )}
        </div>
        <div>
          <label className="text-xs uppercase text-slate-400">Telegram ID</label>
          <input
            className="mt-1 w-full rounded-xl border border-slate-800 bg-slate-950 px-3 py-2 text-sm"
            type="number"
            {...register("telegram_id")}
          />
          {errors.telegram_id && (
            <p className="text-xs text-rose-400">Укажите Telegram ID.</p>
          )}
        </div>
        <div>
          <label className="text-xs uppercase text-slate-400">Phone</label>
          <input
            className="mt-1 w-full rounded-xl border border-slate-800 bg-slate-950 px-3 py-2 text-sm"
            {...register("phone")}
          />
        </div>
        <div>
          <label className="text-xs uppercase text-slate-400">Username</label>
          <input
            className="mt-1 w-full rounded-xl border border-slate-800 bg-slate-950 px-3 py-2 text-sm"
            {...register("username")}
          />
        </div>
        <div>
          <label className="text-xs uppercase text-slate-400">First name</label>
          <input
            className="mt-1 w-full rounded-xl border border-slate-800 bg-slate-950 px-3 py-2 text-sm"
            {...register("first_name")}
          />
        </div>
        <div>
          <label className="text-xs uppercase text-slate-400">Status</label>
          <select
            className="mt-1 w-full rounded-xl border border-slate-800 bg-slate-950 px-3 py-2 text-sm"
            {...register("status")}
          >
            <option value="new">New</option>
            <option value="warming">Warming</option>
            <option value="active">Active</option>
            <option value="cooldown">Cooldown</option>
            <option value="blocked">Blocked</option>
            <option value="verified">Verified</option>
          </select>
        </div>
        <button
          type="submit"
          className="rounded-xl bg-indigo-500 px-4 py-2 text-sm font-semibold text-white disabled:opacity-60"
          disabled={isSubmitting}
        >
          {isSubmitting ? "Сохраняем..." : "Добавить аккаунт"}
        </button>
        {error && <p className="text-sm text-rose-400">{error}</p>}
        {verifyMessage && <p className="text-sm text-emerald-300">{verifyMessage}</p>}
      </form>

      {loading ? (
        <SkeletonList rows={4} />
      ) : accounts.length === 0 ? (
        <EmptyState
          title="Аккаунтов нет"
          description="Добавьте аккаунты, чтобы запускать кампании."
        />
      ) : (
        <div className="space-y-3">
          {accounts.map((account) => {
            const progress = formatProgress(account);
            return (
              <div
                key={account.id}
                onClick={() => setSelectedAccountId(account.id)}
                className={[
                  "rounded-2xl border bg-slate-900/60 p-4",
                  selectedAccountId === account.id ? "border-indigo-400" : "border-slate-800",
                ].join(" ")}
              >
                <div className="flex items-center justify-between">
                  <h3 className="text-base font-semibold">
                    {account.username || account.telegram_id}
                  </h3>
                  <span
                    className={`text-xs uppercase ${statusStyles[account.status] || "text-slate-300"}`}
                  >
                    {account.status}
                  </span>
                </div>
                <p className="text-xs text-slate-500">ID: {account.telegram_id}</p>
                {account.device_config?.device_model && (
                  <p className="text-xs text-slate-500">
                    Device: {String(account.device_config.device_model)}
                  </p>
                )}
                {account.status === "warming" && (
                  <div className="mt-3 space-y-1">
                    <div className="flex items-center justify-between text-xs text-slate-400">
                      <span>Warming progress</span>
                      <span>{progress.label}</span>
                    </div>
                    <div className="h-2 w-full rounded-full bg-slate-800">
                      <div
                        className="h-2 rounded-full bg-amber-400/80"
                        style={{ width: `${progress.percent}%` }}
                      />
                    </div>
                  </div>
                )}
                <div className="mt-3 flex gap-2">
                  <button
                    type="button"
                    onClick={() => handleStartWarming(account.id)}
                    className="rounded-lg bg-indigo-500/80 px-3 py-1 text-xs font-semibold disabled:opacity-60"
                    disabled={account.status === "warming"}
                  >
                    {account.status === "warming" ? "Warming..." : "Start Warming"}
                  </button>
                  <button
                    type="button"
                    onClick={() => handleVerify(account.id)}
                    className="rounded-lg border border-slate-700 px-3 py-1 text-xs font-semibold text-slate-200"
                  >
                    Verify Telegram
                  </button>
                  <button
                    type="button"
                    onClick={() => handleRegenerateDevice(account.id)}
                    className="rounded-lg border border-slate-700 px-3 py-1 text-xs font-semibold text-slate-200"
                  >
                    Regenerate Device
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
};

export default Accounts;
