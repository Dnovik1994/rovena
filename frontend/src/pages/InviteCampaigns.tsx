import React, { useCallback, useEffect, useRef, useState } from "react";

import EmptyState from "../components/EmptyState";
import SkeletonList from "../components/SkeletonList";
import {
  fetchInviteCampaigns,
  fetchInviteCampaign,
  createInviteCampaign,
  startInviteCampaign,
  pauseInviteCampaign,
  resumeInviteCampaign,
  deleteInviteCampaign,
  fetchMyAdminChats,
  fetchParsedContactsSummary,
} from "../services/inviteApi";
import { fetchTgAccounts } from "../services/resources";
import { useAuth } from "../stores/auth";
import type {
  InviteCampaign,
  InviteCampaignDetail,
  CreateInviteCampaign,
  AdminChat,
} from "../types/invite";
import type { TgAccount } from "../types/telegram_account";
import { extractError } from "../utils/extractError";

/* ── Status badge ───────────────────────────────────────────────── */

const statusStyles: Record<string, string> = {
  draft: "bg-slate-700 text-slate-300",
  active: "bg-emerald-900/60 text-emerald-400 animate-pulse",
  paused: "bg-orange-900/60 text-orange-400",
  completed: "bg-blue-900/60 text-blue-400",
  error: "bg-rose-900/60 text-rose-400",
};

const statusLabels: Record<string, string> = {
  draft: "Черновик",
  active: "Активна",
  paused: "На паузе",
  completed: "Завершена",
  error: "Ошибка",
};

function StatusBadge({ status }: { status: string }) {
  return (
    <span
      className={`rounded-full px-2 py-0.5 text-xs font-semibold ${statusStyles[status] || "bg-slate-700 text-slate-300"}`}
    >
      {statusLabels[status] || status}
    </span>
  );
}

/* ── Progress bar ───────────────────────────────────────────────── */

function ProgressBar({ value, max, className }: { value: number; max: number; className?: string }) {
  const percent = max > 0 ? Math.min(100, Math.round((value / max) * 100)) : 0;
  return (
    <div className="h-2 w-full rounded-full bg-slate-800 overflow-hidden">
      <div
        className={`h-2 rounded-full transition-all duration-500 ${className || "bg-indigo-500/80"}`}
        style={{ width: `${percent}%` }}
      />
    </div>
  );
}

/* ── Component ──────────────────────────────────────────────────── */

const InviteCampaigns = (): JSX.Element => {
  const { token } = useAuth();

  // Campaign list
  const [campaigns, setCampaigns] = useState<InviteCampaign[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionMessage, setActionMessage] = useState<string | null>(null);

  // Detail view
  const [detail, setDetail] = useState<InviteCampaignDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  // Create form
  const [showForm, setShowForm] = useState(false);
  const [formSubmitting, setFormSubmitting] = useState(false);

  // Form fields
  const [formName, setFormName] = useState("");
  const [formMaxInvites, setFormMaxInvites] = useState(100);
  const [formInvitesPerHour, setFormInvitesPerHour] = useState(10);

  // Account selection (checkboxes)
  const [accounts, setAccounts] = useState<TgAccount[]>([]);
  const [selectedAccountIds, setSelectedAccountIds] = useState<Set<number>>(new Set());

  // Target chat (admin chats dropdown)
  const [adminChats, setAdminChats] = useState<AdminChat[]>([]);
  const [selectedTargetChatId, setSelectedTargetChatId] = useState<number | null>(null);
  const [loadingAdminChats, setLoadingAdminChats] = useState(false);

  // Available contacts
  const [availableContacts, setAvailableContacts] = useState<number>(0);

  /* ── Load campaigns ─── */
  const loadCampaigns = useCallback(async () => {
    if (!token) return;
    try {
      setLoading(true);
      setError(null);
      const data = await fetchInviteCampaigns(token);
      setCampaigns(data);
    } catch (err) {
      setError(extractError(err));
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    loadCampaigns();
  }, [loadCampaigns]);

  /* ── Polling: refetch campaigns every 5s while any is active ─── */
  const listPollingRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const startListPolling = useCallback(() => {
    if (listPollingRef.current) return;
    listPollingRef.current = setInterval(async () => {
      if (!token) return;
      try {
        const data = await fetchInviteCampaigns(token);
        setCampaigns(data);
      } catch {
        // ignore polling errors
      }
    }, 5000);
  }, [token]);

  const stopListPolling = useCallback(() => {
    if (listPollingRef.current) {
      clearInterval(listPollingRef.current);
      listPollingRef.current = null;
    }
  }, []);

  useEffect(() => {
    const hasActive = campaigns.some((c) => c.status === "active");

    if (hasActive && !document.hidden) {
      startListPolling();
    } else {
      stopListPolling();
    }

    return stopListPolling;
  }, [campaigns, startListPolling, stopListPolling]);

  /* ── Pause polling when tab is hidden ─── */
  useEffect(() => {
    const handleVisibility = () => {
      if (document.hidden) {
        stopListPolling();
      } else {
        const hasActive = campaigns.some((c) => c.status === "active");
        if (hasActive) {
          startListPolling();
        }
      }
    };
    document.addEventListener("visibilitychange", handleVisibility);
    return () => {
      document.removeEventListener("visibilitychange", handleVisibility);
    };
  }, [campaigns, startListPolling, stopListPolling]);

  /* ── Polling: refetch detail every 5s when detail view is open ─── */
  const detailPollingRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (detail && token) {
      detailPollingRef.current = setInterval(async () => {
        try {
          const data = await fetchInviteCampaign(token, detail.id);
          setDetail(data);
        } catch {
          // ignore polling errors
        }
      }, 5000);
    }

    return () => {
      if (detailPollingRef.current) {
        clearInterval(detailPollingRef.current);
        detailPollingRef.current = null;
      }
    };
  }, [detail?.id, token]);

  /* ── Load form data (accounts, admin chats, available contacts) ─── */
  const loadFormData = useCallback(async () => {
    if (!token) return;
    try {
      const [accs, chats, summary] = await Promise.all([
        fetchTgAccounts(token),
        fetchMyAdminChats(token).catch(() => [] as AdminChat[]),
        fetchParsedContactsSummary(token).catch(() => ({ total_contacts: 0, chats: [] })),
      ]);
      setAccounts(accs.filter((a) => a.status === "active"));
      setAdminChats(chats);
      setAvailableContacts(summary.total_contacts);
    } catch {
      // partial failure is ok — individual catches above
    }
  }, [token]);

  /* ── Open create form ─── */
  const handleOpenForm = () => {
    setShowForm(true);
    setLoadingAdminChats(true);
    loadFormData().finally(() => setLoadingAdminChats(false));
  };

  /* ── Toggle account selection ─── */
  const toggleAccount = (id: number) => {
    setSelectedAccountIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  /* ── Create campaign ─── */
  const handleCreate = async () => {
    if (!token || !selectedTargetChatId) return;
    if (!formName.trim()) {
      setError("Введите название кампании");
      return;
    }
    if (selectedAccountIds.size === 0) {
      setError("Выберите хотя бы один аккаунт");
      return;
    }
    try {
      setFormSubmitting(true);
      setError(null);
      const payload: CreateInviteCampaign = {
        name: formName.trim(),
        target_chat_id: selectedTargetChatId,
        max_invites_total: formMaxInvites,
        invites_per_hour_per_account: formInvitesPerHour,
        max_accounts: selectedAccountIds.size,
        source_chat_id: null,
      };
      const created = await createInviteCampaign(token, payload);
      setCampaigns((prev) => [created, ...prev]);
      setShowForm(false);
      resetForm();
      setActionMessage("Кампания создана.");
    } catch (err) {
      setError(extractError(err));
    } finally {
      setFormSubmitting(false);
    }
  };

  const resetForm = () => {
    setFormName("");
    setFormMaxInvites(100);
    setFormInvitesPerHour(10);
    setSelectedAccountIds(new Set());
    setSelectedTargetChatId(null);
    setAdminChats([]);
    setAccounts([]);
    setAvailableContacts(0);
  };

  /* ── Campaign actions ─── */
  const handleStart = async (id: number) => {
    if (!token) return;
    try {
      setError(null);
      const updated = await startInviteCampaign(token, id);
      setCampaigns((prev) => prev.map((c) => (c.id === id ? updated : c)));
      setActionMessage("Кампания запущена.");
    } catch (err) {
      setError(extractError(err));
    }
  };

  const handlePause = async (id: number) => {
    if (!token) return;
    try {
      setError(null);
      const updated = await pauseInviteCampaign(token, id);
      setCampaigns((prev) => prev.map((c) => (c.id === id ? updated : c)));
      setActionMessage("Кампания приостановлена.");
    } catch (err) {
      setError(extractError(err));
    }
  };

  const handleResume = async (id: number) => {
    if (!token) return;
    try {
      setError(null);
      const updated = await resumeInviteCampaign(token, id);
      setCampaigns((prev) => prev.map((c) => (c.id === id ? updated : c)));
      setActionMessage("Кампания продолжена.");
    } catch (err) {
      setError(extractError(err));
    }
  };

  const handleDelete = async (id: number) => {
    if (!token) return;
    if (!confirm("Удалить кампанию?")) return;
    try {
      setError(null);
      await deleteInviteCampaign(token, id);
      setCampaigns((prev) => prev.filter((c) => c.id !== id));
      if (detail?.id === id) setDetail(null);
      setActionMessage("Кампания удалена.");
    } catch (err) {
      setError(extractError(err));
    }
  };

  /* ── View details ─── */
  const handleViewDetail = async (campaign: InviteCampaign) => {
    if (!token) return;
    if (detail?.id === campaign.id) {
      setDetail(null);
      return;
    }
    try {
      setDetailLoading(true);
      const data = await fetchInviteCampaign(token, campaign.id);
      setDetail(data);
    } catch (err) {
      setError(extractError(err));
    } finally {
      setDetailLoading(false);
    }
  };

  /* ── Format date ─── */
  const formatDate = (dateStr: string) => {
    try {
      return new Date(dateStr).toLocaleString();
    } catch {
      return dateStr;
    }
  };

  return (
    <section className="page">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="page__title">Инвайтер</h2>
          <p className="page__subtitle">
            Управление кампаниями приглашений
          </p>
        </div>
        <button
          onClick={handleOpenForm}
          className="btn btn--primary text-xs"
        >
          Создать кампанию
        </button>
      </div>

      {/* ── Messages ──── */}
      {error && (
        <div className="rounded-xl bg-rose-900/40 p-3 text-sm text-rose-300">{error}</div>
      )}
      {actionMessage && (
        <div className="rounded-xl bg-emerald-900/40 p-3 text-sm text-emerald-300">
          {actionMessage}
        </div>
      )}

      {/* ── Create form (modal) ──── */}
      {showForm && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60"
          onClick={() => { setShowForm(false); resetForm(); }}
        >
          <div
            className="w-full max-w-md rounded-2xl border border-slate-700 bg-slate-900 p-6 max-h-[90vh] overflow-y-auto"
            onClick={(e) => e.stopPropagation()}
          >
            <h3 className="text-base font-semibold mb-4">Создать кампанию</h3>
            <div className="space-y-3">
              {/* Name */}
              <div>
                <label className="label">Название</label>
                <input
                  className="input"
                  value={formName}
                  onChange={(e) => setFormName(e.target.value)}
                  placeholder="Название кампании"
                />
              </div>

              {/* Accounts (checkboxes) */}
              <div>
                <label className="label">Аккаунты</label>
                {accounts.length === 0 ? (
                  <p className="text-xs text-slate-500">
                    {loadingAdminChats ? "Загрузка..." : "Нет активных аккаунтов"}
                  </p>
                ) : (
                  <div className="space-y-1 mt-1">
                    {accounts.map((a) => (
                      <label
                        key={a.id}
                        className="flex items-center gap-2 rounded-lg border border-slate-800 bg-slate-800/40 px-3 py-2 cursor-pointer hover:border-indigo-400"
                      >
                        <input
                          type="checkbox"
                          checked={selectedAccountIds.has(a.id)}
                          onChange={() => toggleAccount(a.id)}
                          className="accent-indigo-500"
                        />
                        <span className="text-sm text-slate-200">
                          {a.tg_username ? `@${a.tg_username}` : a.phone_e164}
                        </span>
                        <span className="ml-auto text-xs text-slate-500">{a.status}</span>
                      </label>
                    ))}
                    <p className="text-xs text-slate-400 mt-1">
                      Выбрано: {selectedAccountIds.size} из {accounts.length} аккаунтов
                    </p>
                  </div>
                )}
              </div>

              {/* Target chat (admin chats dropdown) */}
              <div>
                <label className="label">Целевая группа</label>
                {loadingAdminChats ? (
                  <p className="text-xs text-slate-500">Загрузка...</p>
                ) : (
                  <select
                    className="input"
                    value={selectedTargetChatId ?? ""}
                    onChange={(e) =>
                      setSelectedTargetChatId(e.target.value ? Number(e.target.value) : null)
                    }
                  >
                    <option value="">Выберите группу...</option>
                    {adminChats.map((c) => (
                      <option key={c.id} value={c.chat_id}>
                        {c.title} ({c.members_count})
                      </option>
                    ))}
                  </select>
                )}
              </div>

              {/* Max invites */}
              <div>
                <label className="label">Количество контактов</label>
                <input
                  className="input"
                  type="number"
                  min={1}
                  value={formMaxInvites}
                  onChange={(e) => setFormMaxInvites(Number(e.target.value))}
                />
                <p className="text-xs text-slate-500 mt-1">
                  Доступно: {availableContacts} контактов
                </p>
              </div>

              {/* Invites per hour per account */}
              <div>
                <label className="label">Контактов в час на аккаунт</label>
                <input
                  className="input"
                  type="number"
                  min={1}
                  value={formInvitesPerHour}
                  onChange={(e) => setFormInvitesPerHour(Number(e.target.value))}
                />
              </div>

              {/* Actions */}
              <div className="flex gap-2 pt-2">
                <button
                  onClick={handleCreate}
                  disabled={
                    formSubmitting ||
                    !selectedTargetChatId ||
                    !formName.trim() ||
                    selectedAccountIds.size === 0
                  }
                  className="btn btn--primary text-xs disabled:opacity-50"
                >
                  {formSubmitting ? "Создаём..." : "Создать"}
                </button>
                <button
                  onClick={() => { setShowForm(false); resetForm(); }}
                  className="rounded-lg border border-slate-700 px-3 py-1 text-xs font-semibold text-slate-200"
                >
                  Отмена
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ── Campaign list ──── */}
      {loading ? (
        <SkeletonList rows={4} />
      ) : campaigns.length === 0 ? (
        <EmptyState
          title="Кампаний пока нет"
          description="Создайте кампанию для начала инвайтинга."
        />
      ) : (
        <div className="space-y-3">
          {campaigns.map((campaign) => {
            const percent = campaign.max_invites_total > 0
              ? Math.round((campaign.invites_completed / campaign.max_invites_total) * 100)
              : 0;
            const isDetailOpen = detail?.id === campaign.id;

            return (
              <div
                key={campaign.id}
                className={[
                  "rounded-2xl border bg-slate-900/60 p-4 cursor-pointer",
                  isDetailOpen ? "border-indigo-400" : "border-slate-800",
                ].join(" ")}
                onClick={() => handleViewDetail(campaign)}
              >
                {/* ── Header ──── */}
                <div className="flex items-center justify-between">
                  <h3 className="text-base font-semibold">{campaign.name}</h3>
                  <StatusBadge status={campaign.status} />
                </div>

                {/* ── Info ──── */}
                <div className="mt-1 flex flex-wrap items-center gap-3 text-xs text-slate-400">
                  {campaign.source_title && <span>Источник: {campaign.source_title}</span>}
                  {campaign.target_title && <span>Цель: {campaign.target_title}</span>}
                </div>
                <div className="mt-1 text-xs text-slate-500">
                  Создана: {formatDate(campaign.created_at)}
                </div>

                {/* ── Progress bar ──── */}
                <div className="mt-3 space-y-1">
                  <div className="flex items-center justify-between text-xs text-slate-400">
                    <span>Прогресс</span>
                    <span>
                      {campaign.invites_completed} / {campaign.max_invites_total} ({percent}%)
                    </span>
                  </div>
                  <ProgressBar
                    value={campaign.invites_completed}
                    max={campaign.max_invites_total}
                    className={
                      campaign.status === "error"
                        ? "bg-rose-500/80"
                        : campaign.status === "completed"
                          ? "bg-blue-500/80"
                          : campaign.status === "paused"
                            ? "bg-orange-400/80"
                            : "bg-emerald-500/80"
                    }
                  />
                  {campaign.invites_failed > 0 && (
                    <p className="text-xs text-rose-400">
                      Ошибки: {campaign.invites_failed}
                    </p>
                  )}
                </div>

                {/* ── Action buttons ──── */}
                <div className="mt-3 flex flex-wrap gap-2">
                  {campaign.status === "draft" && (
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        handleStart(campaign.id);
                      }}
                      className="rounded-lg bg-emerald-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-emerald-500 transition-colors"
                    >
                      Запустить
                    </button>
                  )}
                  {campaign.status === "active" && (
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        handlePause(campaign.id);
                      }}
                      className="rounded-lg bg-orange-500/80 px-3 py-1.5 text-xs font-semibold text-white hover:bg-orange-400/80 transition-colors"
                    >
                      Пауза
                    </button>
                  )}
                  {campaign.status === "paused" && (
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        handleResume(campaign.id);
                      }}
                      className="rounded-lg bg-emerald-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-emerald-500 transition-colors"
                    >
                      Продолжить
                    </button>
                  )}
                  {["draft", "paused", "completed", "error"].includes(campaign.status) && (
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        handleDelete(campaign.id);
                      }}
                      className="rounded-lg bg-rose-600/80 px-3 py-1.5 text-xs font-semibold text-white hover:bg-rose-500/80 transition-colors"
                    >
                      Удалить
                    </button>
                  )}
                </div>

                {/* ── Detail view (inline, toggled) ──── */}
                {isDetailOpen && detail && (
                  <div className="mt-4 space-y-3 border-t border-slate-800 pt-3">
                    <h4 className="text-sm font-semibold text-slate-200">Статистика задач</h4>
                    <div className="space-y-2">
                      {/* Pending */}
                      <div>
                        <div className="flex items-center justify-between text-xs text-slate-400 mb-1">
                          <span>Ожидание</span>
                          <span>{detail.pending}</span>
                        </div>
                        <ProgressBar value={detail.pending} max={detail.total_tasks} className="bg-slate-500/80" />
                      </div>
                      {/* In Progress */}
                      <div>
                        <div className="flex items-center justify-between text-xs text-slate-400 mb-1">
                          <span>В работе</span>
                          <span>{detail.in_progress}</span>
                        </div>
                        <ProgressBar value={detail.in_progress} max={detail.total_tasks} className="bg-indigo-500/80" />
                      </div>
                      {/* Success */}
                      <div>
                        <div className="flex items-center justify-between text-xs text-slate-400 mb-1">
                          <span>Успешно</span>
                          <span>{detail.success}</span>
                        </div>
                        <ProgressBar value={detail.success} max={detail.total_tasks} className="bg-emerald-500/80" />
                      </div>
                      {/* Failed */}
                      <div>
                        <div className="flex items-center justify-between text-xs text-slate-400 mb-1">
                          <span>Ошибки</span>
                          <span>{detail.failed}</span>
                        </div>
                        <ProgressBar value={detail.failed} max={detail.total_tasks} className="bg-rose-500/80" />
                      </div>
                      {/* Skipped */}
                      <div>
                        <div className="flex items-center justify-between text-xs text-slate-400 mb-1">
                          <span>Пропущено</span>
                          <span>{detail.skipped}</span>
                        </div>
                        <ProgressBar value={detail.skipped} max={detail.total_tasks} className="bg-amber-500/80" />
                      </div>
                    </div>
                    <p className="text-xs text-slate-500">
                      Всего задач: {detail.total_tasks}
                    </p>
                  </div>
                )}
                {isDetailOpen && detailLoading && (
                  <div className="mt-4 text-xs text-slate-500">Загрузка...</div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
};

export default InviteCampaigns;
