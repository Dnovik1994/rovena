import React, { useCallback, useEffect, useRef, useState } from "react";
import { useParams, Link } from "react-router-dom";

import EmptyState from "../components/EmptyState";
import SkeletonList from "../components/SkeletonList";
import { fetchAccountChats, syncAccount, parseChat } from "../services/inviteApi";
import { useAuth } from "../stores/auth";
import type { AccountChat } from "../types/invite";

/* ── Helper: extract error message ──────────────────────────────── */

function extractError(err: unknown): string {
  if (err && typeof err === "object" && "message" in err) {
    return (err as { message: string }).message;
  }
  return "Unexpected error";
}

/* ── Chat type icon ─────────────────────────────────────────────── */

function chatIcon(type: AccountChat["chat_type"]): string {
  return type === "channel" ? "\u{1F4E2}" : "\u{1F465}";
}

/* ── Component ──────────────────────────────────────────────────── */

const AccountChats = (): JSX.Element => {
  const { token } = useAuth();
  const { accountId } = useParams<{ accountId: string }>();
  const numericAccountId = Number(accountId);

  const [chats, setChats] = useState<AccountChat[]>([]);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [actionMessage, setActionMessage] = useState<string | null>(null);

  // Track which chats are currently being parsed
  const [parsingChats, setParsingChats] = useState<Set<number>>(new Set());
  const [parsingTimeoutChats, setParsingTimeoutChats] = useState<Set<number>>(new Set());
  const pollingTimers = useRef<Map<number, ReturnType<typeof setInterval>>>(new Map());
  const pollingStartTimes = useRef<Map<number, number>>(new Map());

  /* ── Load chats ─── */
  const load = useCallback(async () => {
    if (!token || !numericAccountId) return;
    try {
      setLoading(true);
      setError(null);
      const data = await fetchAccountChats(token, numericAccountId);
      setChats(data);
    } catch (err) {
      setError(extractError(err));
    } finally {
      setLoading(false);
    }
  }, [token, numericAccountId]);

  useEffect(() => {
    load();
  }, [load]);

  // Cleanup polling timers on unmount
  useEffect(() => {
    return () => {
      pollingTimers.current.forEach((timer) => clearInterval(timer));
      pollingTimers.current.clear();
      pollingStartTimes.current.clear();
    };
  }, []);

  /* ── Sync ─── */
  const handleSync = async () => {
    if (!token || !numericAccountId) return;
    try {
      setSyncing(true);
      setError(null);
      await syncAccount(token, numericAccountId);
      setActionMessage("Sync started. Refreshing chat list...");
      setTimeout(() => {
        load();
        setActionMessage(null);
      }, 2000);
    } catch (err) {
      setError(extractError(err));
    } finally {
      setSyncing(false);
    }
  };

  /* ── Parse chat ─── */
  const handleParse = async (chat: AccountChat) => {
    if (!token || !numericAccountId) return;
    try {
      setError(null);
      setParsingChats((prev) => new Set(prev).add(chat.id));
      setParsingTimeoutChats((prev) => {
        const next = new Set(prev);
        next.delete(chat.id);
        return next;
      });
      await parseChat(token, numericAccountId, chat.id);
      setActionMessage(`Парсинг "${chat.title}" запущен...`);

      const originalParsedAt = chat.last_parsed_at;
      pollingStartTimes.current.set(chat.id, Date.now());

      // Poll every 5 seconds to check for updates
      const timer = setInterval(async () => {
        const startTime = pollingStartTimes.current.get(chat.id) ?? Date.now();
        const elapsed = Date.now() - startTime;

        // Timeout after 5 minutes
        if (elapsed > 5 * 60 * 1000) {
          clearInterval(timer);
          pollingTimers.current.delete(chat.id);
          pollingStartTimes.current.delete(chat.id);
          setParsingChats((prev) => {
            const next = new Set(prev);
            next.delete(chat.id);
            return next;
          });
          setParsingTimeoutChats((prev) => new Set(prev).add(chat.id));
          setActionMessage(`Парсинг "${chat.title}" занимает больше времени чем обычно`);
          return;
        }

        try {
          const data = await fetchAccountChats(token, numericAccountId);
          setChats(data);
          const updated = data.find((c) => c.id === chat.id);
          // Check if last_parsed_at changed (became non-null or newer)
          if (
            updated?.last_parsed_at &&
            updated.last_parsed_at !== originalParsedAt
          ) {
            clearInterval(timer);
            pollingTimers.current.delete(chat.id);
            pollingStartTimes.current.delete(chat.id);
            setParsingChats((prev) => {
              const next = new Set(prev);
              next.delete(chat.id);
              return next;
            });
            setActionMessage(`"${chat.title}" — парсинг завершён.`);
          }
        } catch {
          // ignore polling error
        }
      }, 5000);

      pollingTimers.current.set(chat.id, timer);
    } catch (err) {
      setError(extractError(err));
      setParsingChats((prev) => {
        const next = new Set(prev);
        next.delete(chat.id);
        return next;
      });
    }
  };

  /* ── Format date ─── */
  const formatDate = (dateStr: string | null) => {
    if (!dateStr) return null;
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
          <h2 className="page__title">Account Chats</h2>
          <p className="page__subtitle">
            Chats for account #{accountId}
          </p>
        </div>
        <div className="flex gap-2">
          <Link to="/accounts">
            <button className="rounded-lg border border-slate-700 px-3 py-1 text-xs font-semibold text-slate-200">
              Back
            </button>
          </Link>
          <button
            onClick={handleSync}
            disabled={syncing}
            className="rounded-lg bg-indigo-500/80 px-3 py-1 text-xs font-semibold text-white disabled:opacity-50"
          >
            {syncing ? "Syncing..." : "Sync"}
          </button>
        </div>
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

      {/* ── Chat list ──── */}
      {loading ? (
        <SkeletonList rows={4} />
      ) : chats.length === 0 ? (
        <EmptyState
          title="No chats found"
          description="Try syncing the account to load chats from Telegram."
        />
      ) : (
        <div className="space-y-3">
          {chats.map((chat) => {
            const isParsing = parsingChats.has(chat.id);
            const isChannel = chat.chat_type === "channel";

            return (
              <div
                key={chat.id}
                className="rounded-2xl border border-slate-800 bg-slate-900/60 p-4"
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className="text-lg">{chatIcon(chat.chat_type)}</span>
                    <h3 className="text-base font-semibold">{chat.title}</h3>
                  </div>
                  <span className="rounded-full bg-slate-800 px-2 py-0.5 text-xs text-slate-400">
                    {chat.chat_type}
                  </span>
                </div>

                {chat.username && (
                  <p className="text-xs text-slate-500">@{chat.username}</p>
                )}

                <div className="mt-1 flex items-center gap-3">
                  <span className="text-xs text-slate-400">
                    Members: {chat.members_count}
                  </span>
                  {chat.is_creator && (
                    <span className="text-xs text-emerald-400">Creator</span>
                  )}
                  {chat.is_admin && !chat.is_creator && (
                    <span className="text-xs text-amber-400">Admin</span>
                  )}
                </div>

                {/* ── Parse status ──── */}
                <div className="mt-2">
                  {chat.last_parsed_at ? (
                    <div>
                      <p className="text-xs text-emerald-400">
                        Спарсено: {chat.members_count} контактов
                      </p>
                      <p className="text-xs text-slate-500">
                        Последний парсинг: {formatDate(chat.last_parsed_at)}
                      </p>
                    </div>
                  ) : (
                    <p className="text-xs text-slate-500">Не спарсено</p>
                  )}
                </div>

                {/* ── Parse button (only for groups/supergroups) ──── */}
                {!isChannel && (
                  <div className="mt-3">
                    <button
                      onClick={() => handleParse(chat)}
                      disabled={isParsing}
                      className="rounded-lg bg-indigo-500/80 px-3 py-1 text-xs font-semibold text-white disabled:opacity-50"
                    >
                      {isParsing ? "Parsing..." : "Спарсить"}
                    </button>
                    {parsingTimeoutChats.has(chat.id) && (
                      <p className="mt-1 text-xs text-amber-400">
                        Парсинг занимает больше времени чем обычно
                      </p>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
};

export default AccountChats;
