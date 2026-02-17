import React, { useCallback, useEffect, useState } from "react";

import EmptyState from "../components/EmptyState";
import LoadingSkeleton from "../components/LoadingSkeleton";
import { fetchParsedContactsSummary } from "../services/inviteApi";
import { useAuth } from "../stores/auth";
import type { ParsedContactsSummary } from "../types/invite";

// TODO: manual contact form — hidden for now

/* ── Chat type icon ─────────────────────────────────────────────── */

function chatIcon(chatType: string): string {
  return chatType === "channel" ? "\u{1F4E2}" : "\u{1F465}";
}

/* ── Component ──────────────────────────────────────────────────── */

const Contacts = (): JSX.Element => {
  const { token } = useAuth();
  const [summary, setSummary] = useState<ParsedContactsSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    if (!token) {
      setLoading(false);
      return;
    }
    try {
      setLoading(true);
      setError(null);
      const data = await fetchParsedContactsSummary(token);
      setSummary(data);
    } catch {
      setError("Не удалось загрузить данные о контактах.");
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    load();
  }, [load]);

  const handleRefresh = async () => {
    if (!token) return;
    try {
      setRefreshing(true);
      setError(null);
      const data = await fetchParsedContactsSummary(token);
      setSummary(data);
    } catch {
      setError("Не удалось загрузить данные о контактах.");
    } finally {
      setRefreshing(false);
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
      <div>
        <h2 className="page__title">Contacts</h2>
        <p className="page__subtitle">Спарсенные контакты аудитории.</p>
      </div>

      {error && (
        <div className="rounded-xl bg-rose-900/40 p-3 text-sm text-rose-300">{error}</div>
      )}

      {loading ? (
        <LoadingSkeleton rows={4} label="Загрузка контактов" />
      ) : !summary || summary.total_contacts === 0 ? (
        <EmptyState
          title="Нет спарсенных контактов"
          description="Перейдите в Accounts → View Chats и спарсите участников."
        />
      ) : (
        <>
          {/* ── Total contacts ──── */}
          <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-4">
            <div className="flex items-center gap-3">
              <p className="text-2xl font-bold text-slate-100">
                Всего контактов: {summary.total_contacts}
              </p>
              <button
                onClick={handleRefresh}
                disabled={refreshing}
                className="rounded-lg border border-slate-700 px-2 py-1 text-sm text-slate-300 hover:bg-slate-800 disabled:opacity-50"
                title="Обновить"
              >
                {refreshing ? "..." : "\uD83D\uDD04"}
              </button>
            </div>
          </div>

          {/* ── Chat breakdown ──── */}
          <div className="space-y-3">
            {summary.chats.map((chat) => (
              <div
                key={chat.chat_id}
                className="rounded-2xl border border-slate-800 bg-slate-900/60 p-4"
              >
                <div className="flex items-center gap-2">
                  <span className="text-lg">{chatIcon(chat.chat_type)}</span>
                  <h3 className="text-base font-semibold">{chat.title}</h3>
                </div>
                <p className="mt-1 text-xs text-emerald-400">
                  Спарсено: {chat.members_parsed} контактов
                </p>
                <p className="text-xs text-slate-500">
                  Последний парсинг: {formatDate(chat.last_parsed_at)}
                </p>
              </div>
            ))}
          </div>
        </>
      )}
    </section>
  );
};

export default Contacts;
