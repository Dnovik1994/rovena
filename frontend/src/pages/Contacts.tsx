import React, { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

import EmptyState from "../components/EmptyState";
import LoadingSkeleton from "../components/LoadingSkeleton";
import { fetchLeads, fetchParsedContactsSummary } from "../services/inviteApi";
import { useAuth } from "../stores/auth";
import type { LeadItem, LeadsResponse, ParsedContactsSummary } from "../types/invite";

// TODO: manual contact form — hidden for now

type Tab = "groups" | "leads";

/* ── Chat type icon ─────────────────────────────────────────────── */

function chatIcon(chatType: string): string {
  return chatType === "channel" ? "\u{1F4E2}" : "\u{1F465}";
}

/* ── Format date ─── */
function formatDate(dateStr: string): string {
  try {
    return new Date(dateStr).toLocaleString();
  } catch {
    return dateStr;
  }
}

/* ── Groups tab (original content) ──────────────────────────────── */

const GroupsPanel: React.FC<{ token: string | null }> = ({ token }) => {
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

  return (
    <>
      {error && (
        <div className="rounded-xl bg-rose-900/40 p-3 text-sm text-rose-300">{error}</div>
      )}

      {loading ? (
        <LoadingSkeleton rows={4} label="Загрузка контактов" />
      ) : !summary || summary.total_contacts === 0 ? (
        <EmptyState
          title="Нет спарсенных контактов"
          description="Перейдите в Аккаунты → Чаты и спарсите участников."
        >
          <Link to="/accounts" className="btn btn--primary mt-3">
            Перейти к аккаунтам
          </Link>
        </EmptyState>
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
    </>
  );
};

/* ── Leads tab ──────────────────────────────────────────────────── */

const LeadsPanel: React.FC<{ token: string | null }> = ({ token }) => {
  const [data, setData] = useState<LeadsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [searchInput, setSearchInput] = useState("");
  const perPage = 50;

  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const load = useCallback(async () => {
    if (!token) {
      setLoading(false);
      return;
    }
    try {
      setLoading(true);
      setError(null);
      const res = await fetchLeads(token, { page, per_page: perPage, search });
      setData(res);
    } catch {
      setError("Не удалось загрузить лидов.");
    } finally {
      setLoading(false);
    }
  }, [token, page, search]);

  useEffect(() => {
    load();
  }, [load]);

  const handleSearchChange = (value: string) => {
    setSearchInput(value);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      setSearch(value);
      setPage(1);
    }, 400);
  };

  const totalPages = data ? Math.ceil(data.total / perPage) : 0;

  return (
    <>
      {/* ── Search ──── */}
      <div className="flex items-center gap-3">
        <input
          type="text"
          value={searchInput}
          onChange={(e) => handleSearchChange(e.target.value)}
          placeholder="Поиск по username, имени или Telegram ID..."
          className="w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100 placeholder-slate-500 focus:border-indigo-500 focus:outline-none"
        />
      </div>

      {error && (
        <div className="rounded-xl bg-rose-900/40 p-3 text-sm text-rose-300">{error}</div>
      )}

      {loading ? (
        <LoadingSkeleton rows={6} label="Загрузка лидов" />
      ) : !data || data.items.length === 0 ? (
        <EmptyState
          title="Нет лидов"
          description={search ? "По вашему запросу ничего не найдено." : "Спарсите участников чатов, чтобы они появились здесь."}
        />
      ) : (
        <>
          {/* ── Counter ──── */}
          <div className="text-sm text-slate-400">
            Всего: {data.total} лидов
          </div>

          {/* ── Table ──── */}
          <div className="overflow-x-auto rounded-2xl border border-slate-800">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-slate-800 bg-slate-900/80 text-xs uppercase text-slate-400">
                <tr>
                  <th className="px-3 py-2">#</th>
                  <th className="px-3 py-2">Telegram ID</th>
                  <th className="px-3 py-2">Username</th>
                  <th className="px-3 py-2">Имя</th>
                  <th className="px-3 py-2">Телефон</th>
                  <th className="px-3 py-2">Последний онлайн</th>
                  <th className="px-3 py-2">Premium</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800">
                {data.items.map((lead: LeadItem, idx: number) => (
                  <tr key={lead.id} className="hover:bg-slate-800/40">
                    <td className="px-3 py-2 text-slate-500">
                      {(page - 1) * perPage + idx + 1}
                    </td>
                    <td className="px-3 py-2 font-mono text-slate-300">
                      {lead.telegram_id}
                    </td>
                    <td className="px-3 py-2 text-slate-300">
                      {lead.username ? `@${lead.username}` : "none"}
                    </td>
                    <td className="px-3 py-2 text-slate-100">
                      {[lead.first_name, lead.last_name].filter(Boolean).join(" ") || "none"}
                    </td>
                    <td className="px-3 py-2 text-slate-300">
                      {lead.phone || "none"}
                    </td>
                    <td className="px-3 py-2 text-slate-400">
                      {lead.last_online_at ? formatDate(lead.last_online_at) : "none"}
                    </td>
                    <td className="px-3 py-2">
                      {lead.is_premium ? (
                        <span className="text-amber-400">да</span>
                      ) : (
                        <span className="text-slate-500">нет</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* ── Pagination ──── */}
          {totalPages > 1 && (
            <div className="flex items-center justify-center gap-2">
              <button
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={page <= 1}
                className="rounded-lg border border-slate-700 px-3 py-1 text-sm text-slate-300 hover:bg-slate-800 disabled:opacity-40"
              >
                Назад
              </button>
              <span className="text-sm text-slate-400">
                {page} / {totalPages}
              </span>
              <button
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                disabled={page >= totalPages}
                className="rounded-lg border border-slate-700 px-3 py-1 text-sm text-slate-300 hover:bg-slate-800 disabled:opacity-40"
              >
                Вперёд
              </button>
            </div>
          )}
        </>
      )}
    </>
  );
};

/* ── Main Component ─────────────────────────────────────────────── */

const TABS: { key: Tab; label: string }[] = [
  { key: "groups", label: "Группы" },
  { key: "leads", label: "Лиды" },
];

const Contacts = (): JSX.Element => {
  const { token } = useAuth();
  const [activeTab, setActiveTab] = useState<Tab>("groups");

  return (
    <section className="page">
      <div>
        <h2 className="page__title">Контакты</h2>
        <p className="page__subtitle">Спарсенные контакты аудитории.</p>
      </div>

      {/* ── Tabs ──── */}
      <div className="flex gap-2">
        {TABS.map((tab) => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key)}
            className={`rounded-full px-3 py-1 text-xs uppercase ${
              activeTab === tab.key
                ? "bg-indigo-500 text-white"
                : "bg-slate-900 text-slate-300"
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {activeTab === "groups" && <GroupsPanel token={token} />}
      {activeTab === "leads" && <LeadsPanel token={token} />}
    </section>
  );
};

export default Contacts;
