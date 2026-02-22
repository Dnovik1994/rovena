import React, { useCallback, useEffect, useRef, useState } from "react";
import { useParams, Link } from "react-router-dom";

import SkeletonList from "../components/SkeletonList";
import { fetchDialogs, fetchMessages } from "../services/inviteApi";
import type { Dialog, ChatMessage } from "../services/inviteApi";
import { useAuth } from "../stores/auth";

/* ── Helpers ───────────────────────────────────────────────────────── */

function extractError(err: unknown): string {
  if (err && typeof err === "object" && "message" in err) {
    return (err as { message: string }).message;
  }
  return "Unexpected error";
}

const DIALOG_TYPE_ICON: Record<string, string> = {
  private: "\u{1F464}",
  group: "\u{1F465}",
  supergroup: "\u{1F465}",
  channel: "\u{1F4E2}",
  bot: "\u{1F916}",
};

const MEDIA_ICON: Record<string, string> = {
  photo: "\u{1F4F7} \u0424\u043E\u0442\u043E",
  video: "\u{1F3A5} \u0412\u0438\u0434\u0435\u043E",
  document: "\u{1F4C4} \u0414\u043E\u043A\u0443\u043C\u0435\u043D\u0442",
  audio: "\u{1F3B5} \u0410\u0443\u0434\u0438\u043E",
  voice: "\u{1F3A4} \u0413\u043E\u043B\u043E\u0441\u043E\u0432\u043E\u0435",
  video_note: "\u{1F4F9} \u0412\u0438\u0434\u0435\u043E\u0441\u043E\u043E\u0431\u0449\u0435\u043D\u0438\u0435",
  sticker: "\u{1F3AD} \u0421\u0442\u0438\u043A\u0435\u0440",
  animation: "GIF",
  contact: "\u{1F4C7} \u041A\u043E\u043D\u0442\u0430\u043A\u0442",
  location: "\u{1F4CD} \u041B\u043E\u043A\u0430\u0446\u0438\u044F",
  poll: "\u{1F4CA} \u041E\u043F\u0440\u043E\u0441",
};

const TYPE_FILTER_OPTIONS = [
  { value: "all", label: "\u0412\u0441\u0435" },
  { value: "private", label: "\u041B\u0438\u0447\u043D\u044B\u0435" },
  { value: "group", label: "\u0413\u0440\u0443\u043F\u043F\u044B" },
  { value: "channel", label: "\u041A\u0430\u043D\u0430\u043B\u044B" },
];

function relativeDate(dateStr: string | null): string {
  if (!dateStr) return "";
  try {
    const date = new Date(dateStr);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffMin = Math.floor(diffMs / 60_000);
    const diffHour = Math.floor(diffMs / 3_600_000);
    const diffDay = Math.floor(diffMs / 86_400_000);

    if (diffMin < 1) return "\u0442\u043E\u043B\u044C\u043A\u043E \u0447\u0442\u043E";
    if (diffMin < 60) return `${diffMin} \u043C\u0438\u043D \u043D\u0430\u0437\u0430\u0434`;
    if (diffHour < 24) return `${diffHour} \u0447 \u043D\u0430\u0437\u0430\u0434`;
    if (diffDay === 1) return "\u0432\u0447\u0435\u0440\u0430";
    if (diffDay < 7) return `${diffDay} \u0434\u043D. \u043D\u0430\u0437\u0430\u0434`;
    return date.toLocaleDateString();
  } catch {
    return "";
  }
}

function formatTime(dateStr: string | null): string {
  if (!dateStr) return "";
  try {
    const d = new Date(dateStr);
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  } catch {
    return "";
  }
}

function truncate(text: string | null, max: number): string {
  if (!text) return "";
  return text.length > max ? text.slice(0, max) + "\u2026" : text;
}

/* ── Component ─────────────────────────────────────────────────────── */

const AccountDialogs = (): JSX.Element => {
  const { token } = useAuth();
  const { accountId } = useParams<{ accountId: string }>();
  const numericAccountId = Number(accountId);

  /* ── Dialogs state ─── */
  const [dialogs, setDialogs] = useState<Dialog[]>([]);
  const [dialogsLoading, setDialogsLoading] = useState(true);
  const [dialogsError, setDialogsError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [typeFilter, setTypeFilter] = useState("all");

  /* ── Messages state ─── */
  const [selectedChatId, setSelectedChatId] = useState<number | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [messagesLoading, setMessagesLoading] = useState(false);
  const [messagesError, setMessagesError] = useState<string | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [hasMore, setHasMore] = useState(true);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const messagesContainerRef = useRef<HTMLDivElement>(null);
  const isFirstLoad = useRef(true);

  /* ── Load dialogs ─── */
  const loadDialogs = useCallback(async () => {
    if (!token || !numericAccountId) return;
    try {
      setDialogsLoading(true);
      setDialogsError(null);
      const data = await fetchDialogs(token, numericAccountId);
      setDialogs(data);
    } catch (err) {
      setDialogsError(extractError(err));
    } finally {
      setDialogsLoading(false);
    }
  }, [token, numericAccountId]);

  useEffect(() => {
    loadDialogs();
  }, [loadDialogs]);

  /* ── Load messages ─── */
  const loadMessages = useCallback(
    async (chatId: number) => {
      if (!token || !numericAccountId) return;
      try {
        setMessagesLoading(true);
        setMessagesError(null);
        setHasMore(true);
        isFirstLoad.current = true;
        const data = await fetchMessages(token, numericAccountId, chatId);
        setMessages(data);
        if (data.length < 50) setHasMore(false);
      } catch (err) {
        setMessagesError(extractError(err));
      } finally {
        setMessagesLoading(false);
      }
    },
    [token, numericAccountId],
  );

  /* ── Auto-scroll on first load ─── */
  useEffect(() => {
    if (isFirstLoad.current && messages.length > 0 && !messagesLoading) {
      messagesEndRef.current?.scrollIntoView();
      isFirstLoad.current = false;
    }
  }, [messages, messagesLoading]);

  /* ── Select dialog ─── */
  const handleSelectDialog = (chatId: number) => {
    setSelectedChatId(chatId);
    setMessages([]);
    loadMessages(chatId);
  };

  /* ── Load more (older messages) ─── */
  const handleLoadMore = async () => {
    if (!token || !numericAccountId || !selectedChatId || messages.length === 0) return;
    const container = messagesContainerRef.current;
    const prevScrollHeight = container?.scrollHeight ?? 0;

    try {
      setLoadingMore(true);
      const firstMsgId = messages[0].id;
      const older = await fetchMessages(token, numericAccountId, selectedChatId, 50, firstMsgId);
      if (older.length === 0) {
        setHasMore(false);
        return;
      }
      if (older.length < 50) setHasMore(false);
      setMessages((prev) => [...older, ...prev]);

      // Preserve scroll position
      requestAnimationFrame(() => {
        if (container) {
          container.scrollTop = container.scrollHeight - prevScrollHeight;
        }
      });
    } catch (err) {
      setMessagesError(extractError(err));
    } finally {
      setLoadingMore(false);
    }
  };

  /* ── Filter dialogs ─── */
  const filteredDialogs = dialogs.filter((d) => {
    const matchesSearch =
      !search ||
      d.title.toLowerCase().includes(search.toLowerCase()) ||
      (d.username && d.username.toLowerCase().includes(search.toLowerCase()));
    const matchesType =
      typeFilter === "all" ||
      d.type === typeFilter ||
      (typeFilter === "group" && (d.type === "group" || d.type === "supergroup"));
    return matchesSearch && matchesType;
  });

  const selectedDialog = dialogs.find((d) => d.chat_id === selectedChatId);

  /* ── Determine "own" messages ─── */
  // We use account's tg_user_id but it's not available here, so we rely on
  // the from_user being null (Telegram sometimes omits for own in private) or
  // compare with the first sender pattern. For simplicity, we check if
  // from_user is null (service messages) or mark based on a heuristic.
  // A better approach: the API could return account_user_id.

  return (
    <section className="page" style={{ height: "calc(100vh - 120px)", overflow: "hidden" }}>
      {/* ── Header ─── */}
      <div className="flex items-center justify-between" style={{ flexShrink: 0 }}>
        <div>
          <h2 className="page__title">{"\u0414\u0438\u0430\u043B\u043E\u0433\u0438 \u0430\u043A\u043A\u0430\u0443\u043D\u0442\u0430"}</h2>
          <p className="page__subtitle">
            {"\u0410\u043A\u043A\u0430\u0443\u043D\u0442"} #{accountId}
          </p>
        </div>
        <Link to="/accounts">
          <button className="rounded-lg border border-slate-700 px-3 py-1 text-xs font-semibold text-slate-200">
            {"\u2190 \u041D\u0430\u0437\u0430\u0434 \u043A \u0430\u043A\u043A\u0430\u0443\u043D\u0442\u0430\u043C"}
          </button>
        </Link>
      </div>

      {/* ── Errors ─── */}
      {dialogsError && (
        <div className="rounded-xl bg-rose-900/40 p-3 text-sm text-rose-300" style={{ flexShrink: 0 }}>
          {dialogsError}
        </div>
      )}

      {/* ── Split view ─── */}
      <div
        className="flex gap-0 overflow-hidden rounded-2xl border border-slate-800"
        style={{ flex: 1, minHeight: 0 }}
      >
        {/* ── Left panel: dialogs ─── */}
        <div
          className="flex flex-col border-r border-slate-800 bg-slate-900/80"
          style={{ width: 350, flexShrink: 0 }}
        >
          {/* Search & filter */}
          <div className="space-y-2 border-b border-slate-800 p-3">
            <input
              className="input"
              type="text"
              placeholder={"\u{1F50D} \u041F\u043E\u0438\u0441\u043A \u0447\u0430\u0442\u0430..."}
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
            <div className="flex gap-1">
              {TYPE_FILTER_OPTIONS.map((opt) => (
                <button
                  key={opt.value}
                  onClick={() => setTypeFilter(opt.value)}
                  className={[
                    "rounded-lg px-2 py-1 text-xs font-medium transition-colors",
                    typeFilter === opt.value
                      ? "bg-indigo-500/80 text-white"
                      : "bg-slate-800 text-slate-400 hover:text-slate-200",
                  ].join(" ")}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          </div>

          {/* Dialog list */}
          <div className="flex-1 overflow-y-auto">
            {dialogsLoading ? (
              <div className="p-3">
                <SkeletonList rows={6} />
              </div>
            ) : filteredDialogs.length === 0 ? (
              <div className="p-4 text-center text-sm text-slate-500">
                {dialogs.length === 0
                  ? "\u0414\u0438\u0430\u043B\u043E\u0433\u043E\u0432 \u043D\u0435 \u043D\u0430\u0439\u0434\u0435\u043D\u043E"
                  : "\u041D\u0438\u0447\u0435\u0433\u043E \u043D\u0435 \u043D\u0430\u0439\u0434\u0435\u043D\u043E"}
              </div>
            ) : (
              filteredDialogs.map((d) => (
                <div
                  key={d.chat_id}
                  onClick={() => handleSelectDialog(d.chat_id)}
                  className={[
                    "cursor-pointer border-b border-slate-800/50 px-3 py-2.5 transition-colors hover:bg-slate-800/60",
                    selectedChatId === d.chat_id ? "bg-indigo-500/15" : "",
                  ].join(" ")}
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2 min-w-0 flex-1">
                      <span className="text-base flex-shrink-0">
                        {DIALOG_TYPE_ICON[d.type] || "\u{1F4AC}"}
                      </span>
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-1.5">
                          <span className="truncate text-sm font-medium text-slate-200">
                            {d.title}
                          </span>
                          {d.unread_count > 0 && (
                            <span className="flex-shrink-0 rounded-full bg-indigo-500 px-1.5 py-0.5 text-[10px] font-bold text-white leading-none">
                              {d.unread_count}
                            </span>
                          )}
                        </div>
                        {d.username && (
                          <p className="truncate text-xs text-slate-500">@{d.username}</p>
                        )}
                      </div>
                    </div>
                    {d.last_message?.date && (
                      <span className="flex-shrink-0 text-[10px] text-slate-500 ml-2">
                        {relativeDate(d.last_message.date)}
                      </span>
                    )}
                  </div>
                  {d.last_message?.text && (
                    <p className="mt-0.5 truncate text-xs text-slate-500 pl-7">
                      {d.last_message.from && (
                        <span className="text-slate-400">{d.last_message.from}: </span>
                      )}
                      {truncate(d.last_message.text, 50)}
                    </p>
                  )}
                </div>
              ))
            )}
          </div>
        </div>

        {/* ── Right panel: messages ─── */}
        <div className="flex flex-1 flex-col bg-slate-950/60 min-w-0">
          {!selectedChatId ? (
            <div className="flex flex-1 items-center justify-center text-sm text-slate-500">
              {"\u0412\u044B\u0431\u0435\u0440\u0438\u0442\u0435 \u0447\u0430\u0442"}
            </div>
          ) : (
            <>
              {/* Chat header */}
              <div className="flex items-center gap-2 border-b border-slate-800 px-4 py-3">
                <span className="text-base">
                  {selectedDialog ? DIALOG_TYPE_ICON[selectedDialog.type] || "\u{1F4AC}" : ""}
                </span>
                <div>
                  <h3 className="text-sm font-semibold text-slate-200">
                    {selectedDialog?.title || `Chat ${selectedChatId}`}
                  </h3>
                  {selectedDialog && (
                    <p className="text-[10px] text-slate-500">
                      {selectedDialog.type}
                      {selectedDialog.members_count != null && ` \u00B7 ${selectedDialog.members_count} \u0443\u0447\u0430\u0441\u0442\u043D\u0438\u043A\u043E\u0432`}
                    </p>
                  )}
                </div>
              </div>

              {/* Messages area */}
              {messagesError && (
                <div className="mx-4 mt-2 rounded-xl bg-rose-900/40 p-2 text-xs text-rose-300">
                  {messagesError}
                </div>
              )}

              <div
                ref={messagesContainerRef}
                className="flex-1 overflow-y-auto px-4 py-3 space-y-2"
              >
                {/* Load more button */}
                {hasMore && messages.length > 0 && (
                  <div className="flex justify-center py-2">
                    <button
                      onClick={handleLoadMore}
                      disabled={loadingMore}
                      className="rounded-lg bg-slate-800 px-3 py-1 text-xs text-slate-400 hover:text-slate-200 disabled:opacity-50"
                    >
                      {loadingMore ? "\u0417\u0430\u0433\u0440\u0443\u0437\u043A\u0430..." : "\u0417\u0430\u0433\u0440\u0443\u0437\u0438\u0442\u044C \u0435\u0449\u0451"}
                    </button>
                  </div>
                )}

                {messagesLoading ? (
                  <div className="flex flex-1 items-center justify-center py-8">
                    <div className="text-sm text-slate-500">{"\u0417\u0430\u0433\u0440\u0443\u0437\u043A\u0430 \u0441\u043E\u043E\u0431\u0449\u0435\u043D\u0438\u0439..."}</div>
                  </div>
                ) : messages.length === 0 ? (
                  <div className="flex flex-1 items-center justify-center py-8">
                    <div className="text-sm text-slate-500">{"\u041D\u0435\u0442 \u0441\u043E\u043E\u0431\u0449\u0435\u043D\u0438\u0439"}</div>
                  </div>
                ) : (
                  messages.map((msg) => {
                    const isOwn = msg.from_user === null;
                    return (
                      <div
                        key={msg.id}
                        className={`flex ${isOwn ? "justify-end" : "justify-start"}`}
                      >
                        <div
                          className={[
                            "max-w-[75%] rounded-xl px-3 py-2",
                            isOwn
                              ? "bg-indigo-600/40 text-slate-200"
                              : "bg-slate-800/80 text-slate-300",
                          ].join(" ")}
                        >
                          {!isOwn && msg.from_user && (
                            <p className="text-xs font-semibold text-indigo-400 mb-0.5">
                              {msg.from_user.name}
                              {msg.from_user.username && (
                                <span className="font-normal text-slate-500">
                                  {" "}@{msg.from_user.username}
                                </span>
                              )}
                            </p>
                          )}

                          {msg.reply_to_message_id && (
                            <div className="mb-1 border-l-2 border-indigo-500/50 pl-2 text-[10px] text-slate-500">
                              {"\u041E\u0442\u0432\u0435\u0442 \u043D\u0430 #"}{msg.reply_to_message_id}
                            </div>
                          )}

                          {msg.media_type && (
                            <p className="text-xs text-slate-400 mb-0.5">
                              {MEDIA_ICON[msg.media_type] || `\u{1F4CE} ${msg.media_type}`}
                            </p>
                          )}

                          {msg.text && (
                            <p className="text-sm whitespace-pre-wrap break-words">{msg.text}</p>
                          )}

                          <p className={`text-[10px] mt-1 ${isOwn ? "text-indigo-300/60" : "text-slate-500"}`}>
                            {formatTime(msg.date)}
                          </p>
                        </div>
                      </div>
                    );
                  })
                )}
                <div ref={messagesEndRef} />
              </div>
            </>
          )}
        </div>
      </div>
    </section>
  );
};

export default AccountDialogs;
