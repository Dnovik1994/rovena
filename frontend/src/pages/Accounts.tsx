import React, { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";

import EmptyState from "../components/EmptyState";
import SkeletonList from "../components/SkeletonList";
import {
  fetchTgAccounts,
  createTgAccount,
  sendTgCode,
  confirmTgCode,
  confirmTgPassword,
  disconnectTgAccount,
  deleteTgAccount,
  tgHealthCheck,
  tgWarmup,
  tgRegenerateDevice,
  getAuthFlowStatus,
} from "../services/resources";
import { connectStatusSocket, StatusMessage } from "../services/websocket";
import { useAuth } from "../stores/auth";
import type { TgAccount, TgAccountStatus } from "../types/telegram_account";
import { apiFetch } from "../shared/api/client";
import { extractError } from "../utils/extractError";

/* ── Form schemas ────────────────────────────────────────────────── */

const phoneSchema = z.object({
  phone: z
    .string()
    .min(7, "Enter a valid phone number")
    .max(32)
    .regex(/^\+[1-9]\d{6,14}$/, "Phone must be E.164 format (e.g. +380501234567)"),
});
type PhoneFormValues = z.infer<typeof phoneSchema>;

const codeSchema = z.object({
  code: z.string().min(3, "Enter the verification code").max(10),
});
type CodeFormValues = z.infer<typeof codeSchema>;

const passwordSchema = z.object({
  password: z.string().min(1, "Enter your 2FA password"),
});
type PasswordFormValues = z.infer<typeof passwordSchema>;

/* ── Polling constants ─────────────────────────────────────────── */

const POLL_INTERVAL_MS = 2_000;
const POLL_MAX_ATTEMPTS = 30; // 60s max

/* ── Status styling ─────────────────────────────────────────────── */

const statusStyles: Record<string, string> = {
  new: "text-slate-300",
  code_sent: "text-yellow-400",
  password_required: "text-orange-400",
  verified: "text-emerald-400",
  disconnected: "text-slate-500",
  error: "text-rose-400",
  banned: "text-red-500",
  warming: "text-amber-400",
  active: "text-emerald-400",
  cooldown: "text-orange-400",
};

const statusLabels: Record<string, string> = {
  new: "New",
  code_sent: "Code Sent",
  password_required: "2FA Required",
  verified: "Verified",
  disconnected: "Disconnected",
  error: "Error",
  banned: "Banned",
  warming: "Warming",
  active: "Active",
  cooldown: "Cooldown",
};

/* Flow states that indicate polling is done */
const TERMINAL_FLOW_STATES = new Set([
  "wait_code",
  "code_sent",
  "wait_password",
  "done",
  "expired",
  "failed",
]);

/* ── Component ──────────────────────────────────────────────────── */

const Accounts = (): JSX.Element => {
  const { token } = useAuth();
  const [accounts, setAccounts] = useState<TgAccount[]>([]);
  const [loading, setLoading] = useState(true);
  const [globalError, setGlobalError] = useState<string | null>(null);
  const [actionMessage, setActionMessage] = useState<string | null>(null);

  // Per-account auth flow state
  const [flowMap, setFlowMap] = useState<Record<number, string>>({}); // account_id -> flow_id
  const [activeAccountId, setActiveAccountId] = useState<number | null>(null);
  // Track which accounts are waiting for send-code to complete
  const [pendingAccounts, setPendingAccounts] = useState<Set<number>>(new Set());
  const pollTimersRef = useRef<Record<number, ReturnType<typeof setTimeout>>>({});

  /* ── Phone form ─── */
  const phoneForm = useForm<PhoneFormValues>({
    resolver: zodResolver(phoneSchema),
  });

  /* ── Code form ─── */
  const codeForm = useForm<CodeFormValues>({
    resolver: zodResolver(codeSchema),
  });

  /* ── Password form ─── */
  const passwordForm = useForm<PasswordFormValues>({
    resolver: zodResolver(passwordSchema),
  });

  /* ── Cleanup poll timers on unmount ─── */
  useEffect(() => {
    return () => {
      Object.values(pollTimersRef.current).forEach(clearTimeout);
    };
  }, []);

  /* ── Load accounts ─── */
  const load = useCallback(async () => {
    if (!token) {
      setLoading(false);
      return;
    }
    try {
      setLoading(true);
      const data = await fetchTgAccounts(token);
      setAccounts(data);
    } catch (err) {
      setGlobalError(extractError(err));
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    load();
  }, [load]);

  /* ── Poll flow status after send-code ─── */
  const startFlowPolling = useCallback(
    (accountId: number, flowId: string) => {
      if (!token) return;
      let attempt = 0;

      const poll = async () => {
        if (attempt >= POLL_MAX_ATTEMPTS) {
          setPendingAccounts((prev) => {
            const next = new Set(prev);
            next.delete(accountId);
            return next;
          });
          setGlobalError(
            "Verification timed out — the code was not sent. Check account error or try again.",
          );
          setActionMessage(null);
          // Reload accounts to display any error the worker may have written
          load();
          return;
        }
        attempt++;
        try {
          const status = await getAuthFlowStatus(token, accountId, flowId);

          if (TERMINAL_FLOW_STATES.has(status.flow_state)) {
            // Update account status from the polling response
            setAccounts((prev) =>
              prev.map((a) =>
                a.id === accountId
                  ? { ...a, status: status.account_status, last_error: status.last_error }
                  : a,
              ),
            );
            setPendingAccounts((prev) => {
              const next = new Set(prev);
              next.delete(accountId);
              return next;
            });

            if (status.flow_state === "failed" || status.flow_state === "expired") {
              setGlobalError(status.last_error || "Verification failed");
              setActionMessage(null);
            } else if (status.flow_state === "wait_code" || status.flow_state === "code_sent") {
              setActionMessage("Verification code sent. Enter the code below.");
              setGlobalError(null);
            } else if (status.flow_state === "wait_password") {
              setActionMessage("2FA password required. Enter your Telegram cloud password.");
              setGlobalError(null);
            }
            return;
          }
        } catch {
          // Ignore poll errors, will retry
        }
        pollTimersRef.current[accountId] = setTimeout(poll, POLL_INTERVAL_MS);
      };

      // Clear any existing timer for this account
      if (pollTimersRef.current[accountId]) {
        clearTimeout(pollTimersRef.current[accountId]);
      }
      setPendingAccounts((prev) => new Set(prev).add(accountId));
      poll();
    },
    [token],
  );

  /* ── WebSocket for real-time updates ─── */
  // Use a ref so the WS callback can read the latest pendingAccounts
  // without causing the effect to re-run (which would reconnect the socket).
  const pendingAccountsRef = useRef(pendingAccounts);
  pendingAccountsRef.current = pendingAccounts;

  useEffect(() => {
    if (!token) return;
    const handle = connectStatusSocket(token, (message: StatusMessage) => {
      if (message.type === "account_status_changed" || message.type === "account_update") {
        setAccounts((prev) =>
          prev.map((item) =>
            item.id === message.account_id
              ? {
                  ...item,
                  status: message.status as TgAccountStatus,
                  warming_actions_completed:
                    ("actions_completed" in message ? message.actions_completed : undefined) ??
                    item.warming_actions_completed,
                  target_warming_actions:
                    ("target_actions" in message ? message.target_actions : undefined) ??
                    item.target_warming_actions,
                  cooldown_until:
                    ("cooldown_until" in message ? message.cooldown_until : undefined) ??
                    item.cooldown_until,
                }
              : item,
          ),
        );
        // Stop polling if WS already delivered the update
        if (pendingAccountsRef.current.has(message.account_id)) {
          if (pollTimersRef.current[message.account_id]) {
            clearTimeout(pollTimersRef.current[message.account_id]);
          }
          setPendingAccounts((prev) => {
            const next = new Set(prev);
            next.delete(message.account_id);
            return next;
          });
        }
      }
      if (message.type === "auth_flow_updated") {
        // Refresh accounts on flow state changes for fresh data
        load();
        // Stop polling for this account
        if (pollTimersRef.current[message.account_id]) {
          clearTimeout(pollTimersRef.current[message.account_id]);
        }
        setPendingAccounts((prev) => {
          const next = new Set(prev);
          next.delete(message.account_id);
          return next;
        });
      }
    });
    return () => {
      handle.dispose();
    };
  }, [token, load]);

  /* ── Submit phone ─── */
  const onSubmitPhone = async (values: PhoneFormValues) => {
    if (!token) return;
    try {
      setGlobalError(null);
      setActionMessage(null);
      const account = await createTgAccount(token, { phone: values.phone });
      setAccounts((prev) => {
        const exists = prev.find((a) => a.id === account.id);
        return exists ? prev.map((a) => (a.id === account.id ? account : a)) : [account, ...prev];
      });
      setActiveAccountId(account.id);
      phoneForm.reset();
      setActionMessage(`Account registered for ${account.phone_e164}. Click "Send Code" to verify.`);
    } catch (err) {
      setGlobalError(extractError(err));
    }
  };

  /* ── Send code ─── */
  const handleSendCode = async (accountId: number) => {
    if (!token) return;
    try {
      setGlobalError(null);
      setActionMessage(null);
      const resp = await sendTgCode(token, accountId);
      setFlowMap((prev) => ({ ...prev, [accountId]: resp.flow_id }));
      setActiveAccountId(accountId);
      setActionMessage("Sending verification code...");
      codeForm.reset();
      passwordForm.reset();

      // Start polling for flow status (primary mechanism)
      // WebSocket will also deliver updates when available
      startFlowPolling(accountId, resp.flow_id);
    } catch (err) {
      setGlobalError(extractError(err));
    }
  };

  /* ── Confirm code ─── */
  const handleConfirmCode = async (accountId: number, values: CodeFormValues) => {
    if (!token) return;
    const flowId = flowMap[accountId];
    if (!flowId) {
      setGlobalError("No active verification flow. Please send code first.");
      return;
    }
    try {
      setGlobalError(null);
      setActionMessage(null);
      const resp = await confirmTgCode(token, accountId, {
        flow_id: flowId,
        code: values.code,
      });
      setActionMessage(resp.message || "Verifying code...");
      codeForm.reset();
      // Poll for result of confirm-code task
      startFlowPolling(accountId, flowId);
    } catch (err) {
      setGlobalError(extractError(err));
    }
  };

  /* ── Confirm 2FA password ─── */
  const handleConfirmPassword = async (accountId: number, values: PasswordFormValues) => {
    if (!token) return;
    const flowId = flowMap[accountId];
    if (!flowId) {
      setGlobalError("No active verification flow.");
      return;
    }
    try {
      setGlobalError(null);
      setActionMessage(null);
      const resp = await confirmTgPassword(token, accountId, {
        flow_id: flowId,
        password: values.password,
      });
      setActionMessage(resp.message || "Verifying password...");
      passwordForm.reset();
      // Poll for result
      startFlowPolling(accountId, flowId);
    } catch (err) {
      setGlobalError(extractError(err));
    }
  };

  /* ── Actions ─── */
  const handleDisconnect = async (accountId: number) => {
    if (!token) return;
    try {
      setGlobalError(null);
      const updated = await disconnectTgAccount(token, accountId);
      setAccounts((prev) => prev.map((a) => (a.id === accountId ? updated : a)));
      setActionMessage("Account disconnected.");
    } catch (err) {
      setGlobalError(extractError(err));
    }
  };

  const handleHealthCheck = async (accountId: number) => {
    if (!token) return;
    try {
      setGlobalError(null);
      await tgHealthCheck(token, accountId);
      setActionMessage("Health check started.");
    } catch (err) {
      setGlobalError(extractError(err));
    }
  };

  const handleWarmup = async (accountId: number) => {
    if (!token) return;
    try {
      setGlobalError(null);
      const updated = await tgWarmup(token, accountId);
      setAccounts((prev) => prev.map((a) => (a.id === accountId ? updated : a)));
      setActionMessage("Warmup started.");
    } catch (err) {
      setGlobalError(extractError(err));
    }
  };

  const handleRegenerateDevice = async (accountId: number) => {
    if (!token) return;
    try {
      setGlobalError(null);
      const updated = await tgRegenerateDevice(token, accountId);
      setAccounts((prev) => prev.map((a) => (a.id === accountId ? updated : a)));
      setActionMessage("Device profile regenerated.");
    } catch (err) {
      setGlobalError(extractError(err));
    }
  };

  const handleActivate = async (accountId: number) => {
    if (!token) return;
    try {
      setGlobalError(null);
      await apiFetch(`/tg-accounts/${accountId}/activate`, { method: "POST" }, token);
      setActionMessage("Аккаунт активирован.");
      load();
    } catch (err: any) {
      setGlobalError(err.message || "Ошибка активации");
    }
  };

  const handleDelete = async (account: TgAccount) => {
    if (!token) return;
    const confirmed = window.confirm(
      `Удалить аккаунт ${account.phone_e164}? Сессия будет потеряна.`,
    );
    if (!confirmed) return;
    try {
      setGlobalError(null);
      await deleteTgAccount(token, account.id);
      setAccounts((prev) => prev.filter((a) => a.id !== account.id));
      setActionMessage("Account deleted.");
    } catch (err) {
      setGlobalError(extractError(err));
    }
  };

  /* ── Helpers ─── */
  const formatProgress = (account: TgAccount) => {
    const target = account.target_warming_actions || 0;
    if (!target) return { percent: 0, label: "0 / 0" };
    const percent = Math.min(100, Math.round((account.warming_actions_completed / target) * 100));
    return { percent, label: `${account.warming_actions_completed} / ${target}` };
  };

  const canSendCode = (status: TgAccountStatus) =>
    ["new", "error", "disconnected", "code_sent"].includes(status);

  const needsCodeInput = (status: TgAccountStatus, accountId: number) =>
    status === "code_sent" && !!flowMap[accountId];

  const needsPasswordInput = (status: TgAccountStatus, accountId: number) =>
    status === "password_required" && !!flowMap[accountId];

  const canWarmup = (status: TgAccountStatus) => ["verified", "active"].includes(status);

  const canDisconnect = (status: TgAccountStatus) => !["new", "disconnected"].includes(status);

  const canHealthCheck = (status: TgAccountStatus) =>
    ["verified", "active", "cooldown", "warming"].includes(status);

  return (
    <section className="page">
      <div>
        <h2 className="page__title">Telegram Accounts</h2>
        <p className="page__subtitle">
          Connect Telegram accounts by phone number for campaigns.
        </p>
      </div>

      {/* ── Add account form ──────────────────────────────────────── */}
      <form
        onSubmit={phoneForm.handleSubmit(onSubmitPhone)}
        className="space-y-3 rounded-2xl bg-slate-900/60 p-4"
      >
        <div>
          <label className="label">Phone number (E.164)</label>
          <input
            className="input"
            type="tel"
            placeholder="+380501234567"
            {...phoneForm.register("phone")}
          />
          {phoneForm.formState.errors.phone && (
            <p className="text-xs text-rose-400">
              {phoneForm.formState.errors.phone.message}
            </p>
          )}
        </div>
        <button
          type="submit"
          className="btn btn--primary"
          disabled={phoneForm.formState.isSubmitting}
        >
          {phoneForm.formState.isSubmitting ? "Adding..." : "Add Account"}
        </button>
      </form>

      {/* ── Messages ──────────────────────────────────────────────── */}
      {globalError && (
        <div className="rounded-xl bg-rose-900/40 p-3 text-sm text-rose-300">{globalError}</div>
      )}
      {actionMessage && (
        <div className="rounded-xl bg-emerald-900/40 p-3 text-sm text-emerald-300">
          {actionMessage}
        </div>
      )}

      {/* ── Account list ──────────────────────────────────────────── */}
      {loading ? (
        <SkeletonList rows={4} />
      ) : accounts.length === 0 ? (
        <EmptyState
          title="No accounts yet"
          description="Add a Telegram account by phone number to get started."
        />
      ) : (
        <div className="space-y-3">
          {accounts.map((account) => {
            const progress = formatProgress(account);
            const deviceModel = account.device_config?.device_model;
            const deviceModelLabel = deviceModel ? String(deviceModel) : null;
            const isActive = activeAccountId === account.id;
            const isPending = pendingAccounts.has(account.id);

            return (
              <div
                key={account.id}
                onClick={() => setActiveAccountId(account.id)}
                className={[
                  "rounded-2xl border bg-slate-900/60 p-4 cursor-pointer",
                  isActive ? "border-indigo-400" : "border-slate-800",
                ].join(" ")}
              >
                {/* ── Header ──── */}
                <div className="flex items-center justify-between">
                  <h3 className="text-base font-semibold">
                    {account.tg_username
                      ? `@${account.tg_username}`
                      : account.first_name || account.phone_e164}
                  </h3>
                  <span
                    className={`text-xs uppercase ${statusStyles[account.status] || "text-slate-300"}`}
                  >
                    {isPending ? "Sending..." : statusLabels[account.status] || account.status}
                  </span>
                </div>
                <p className="text-xs text-slate-500">{account.phone_e164}</p>
                {account.tg_user_id && (
                  <p className="text-xs text-slate-500">TG ID: {account.tg_user_id}</p>
                )}
                {deviceModelLabel && (
                  <p className="text-xs text-slate-500">Device: {deviceModelLabel}</p>
                )}
                {account.last_error && (
                  <p className="mt-1 text-xs text-rose-400">Error: {account.last_error}</p>
                )}

                {/* ── Warming progress ──── */}
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

                {/* ── Inline code form ──── */}
                {isActive && needsCodeInput(account.status, account.id) && (
                  <form
                    onSubmit={codeForm.handleSubmit((v) => handleConfirmCode(account.id, v))}
                    className="mt-3 flex gap-2"
                    onClick={(e) => e.stopPropagation()}
                  >
                    <input
                      className="input flex-1"
                      placeholder="Verification code"
                      {...codeForm.register("code")}
                    />
                    <button
                      type="submit"
                      className="rounded-lg bg-emerald-600 px-3 py-1 text-xs font-semibold text-white"
                      disabled={codeForm.formState.isSubmitting}
                    >
                      Confirm
                    </button>
                  </form>
                )}

                {/* ── Inline 2FA password form ──── */}
                {isActive && needsPasswordInput(account.status, account.id) && (
                  <form
                    onSubmit={passwordForm.handleSubmit((v) =>
                      handleConfirmPassword(account.id, v),
                    )}
                    className="mt-3 flex gap-2"
                    onClick={(e) => e.stopPropagation()}
                  >
                    <input
                      className="input flex-1"
                      type="password"
                      placeholder="2FA cloud password"
                      {...passwordForm.register("password")}
                    />
                    <button
                      type="submit"
                      className="rounded-lg bg-orange-600 px-3 py-1 text-xs font-semibold text-white"
                      disabled={passwordForm.formState.isSubmitting}
                    >
                      Confirm Password
                    </button>
                  </form>
                )}

                {/* ── Action buttons ──── */}
                <div className="mt-3 flex flex-wrap gap-2">
                  {canSendCode(account.status) && (
                    <button
                      type="button"
                      disabled={isPending}
                      onClick={(e) => {
                        e.stopPropagation();
                        handleSendCode(account.id);
                      }}
                      className="rounded-lg bg-indigo-500/80 px-3 py-1 text-xs font-semibold text-white disabled:opacity-50"
                    >
                      {isPending
                        ? "Sending..."
                        : account.status === "code_sent"
                          ? "Resend Code"
                          : "Send Code"}
                    </button>
                  )}
                  {canWarmup(account.status) && (
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        handleWarmup(account.id);
                      }}
                      className="rounded-lg bg-amber-500/80 px-3 py-1 text-xs font-semibold text-white"
                      disabled={account.status === "warming"}
                    >
                      {account.status === "warming" ? "Warming..." : "Start Warmup"}
                    </button>
                  )}
                  {["verified"].includes(account.status) && (
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        handleActivate(account.id);
                      }}
                      className="rounded-lg bg-emerald-500/80 px-3 py-1 text-xs font-semibold text-white"
                    >
                      Активировать
                    </button>
                  )}
                  {["verified", "active", "warming", "cooldown"].includes(account.status) && (
                    <Link
                      to={`/accounts/${account.id}/chats`}
                      onClick={(e) => e.stopPropagation()}
                    >
                      <button className="rounded-lg border border-indigo-700 px-3 py-1 text-xs font-semibold text-indigo-300">
                        View Chats
                      </button>
                    </Link>
                  )}
                  {canHealthCheck(account.status) && (
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        handleHealthCheck(account.id);
                      }}
                      className="rounded-lg border border-slate-700 px-3 py-1 text-xs font-semibold text-slate-200"
                    >
                      Health Check
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      handleRegenerateDevice(account.id);
                    }}
                    className="rounded-lg border border-slate-700 px-3 py-1 text-xs font-semibold text-slate-200"
                  >
                    Regenerate Device
                  </button>
                  {canDisconnect(account.status) && (
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        handleDisconnect(account.id);
                      }}
                      className="rounded-lg border border-rose-700 px-3 py-1 text-xs font-semibold text-rose-300"
                    >
                      Disconnect
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      handleDelete(account);
                    }}
                    className="rounded-lg bg-rose-600 px-3 py-1 text-xs font-semibold text-white"
                  >
                    Delete
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
