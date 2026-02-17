import React, { useCallback, useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";

import EmptyState from "../components/EmptyState";
import SkeletonList from "../components/SkeletonList";
import { fetchAccountChats, syncAccount, fetchChatMembers } from "../services/inviteApi";
import { useAuth } from "../stores/auth";
import type { AccountChat, ChatMember } from "../types/invite";

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

  // Modal state
  const [selectedChat, setSelectedChat] = useState<AccountChat | null>(null);
  const [membersCount, setMembersCount] = useState<number | null>(null);
  const [loadingMembers, setLoadingMembers] = useState(false);

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

  /* ── Sync ─── */
  const handleSync = async () => {
    if (!token || !numericAccountId) return;
    try {
      setSyncing(true);
      setError(null);
      await syncAccount(token, numericAccountId);
      setActionMessage("Sync started. Refreshing chat list...");
      // Reload after a short delay so backend has time to process
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

  /* ── Open chat modal ─── */
  const handleChatClick = async (chat: AccountChat) => {
    if (chat.chat_type === "channel") return;
    setSelectedChat(chat);
    setMembersCount(null);
    setLoadingMembers(true);
    try {
      const members = await fetchChatMembers(token!, numericAccountId, chat.id, { limit: 1 });
      // Use members_count from chat, or array length as fallback
      setMembersCount(chat.members_count);
      void members; // fetched to verify access
    } catch {
      setMembersCount(chat.members_count);
    } finally {
      setLoadingMembers(false);
    }
  };

  /* ── "Use as Source" — store in sessionStorage for campaign creation ─── */
  const handleUseAsSource = (chat: AccountChat) => {
    sessionStorage.setItem(
      "invite_source_chat",
      JSON.stringify({
        account_id: numericAccountId,
        chat_id: chat.id,
        title: chat.title,
        members_count: chat.members_count,
      }),
    );
    setSelectedChat(null);
    setActionMessage(`"${chat.title}" saved as source. Go to Inviter to create a campaign.`);
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
          {chats.map((chat) => (
            <div
              key={chat.id}
              onClick={() => handleChatClick(chat)}
              className={[
                "rounded-2xl border bg-slate-900/60 p-4",
                chat.chat_type !== "channel" ? "cursor-pointer hover:border-indigo-400" : "",
                "border-slate-800",
              ].join(" ")}
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
              {chat.last_parsed_at && (
                <p className="mt-1 text-xs text-slate-500">
                  Last parsed: {formatDate(chat.last_parsed_at)}
                </p>
              )}
            </div>
          ))}
        </div>
      )}

      {/* ── Chat detail modal ──── */}
      {selectedChat && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60"
          onClick={() => setSelectedChat(null)}
        >
          <div
            className="w-full max-w-sm rounded-2xl border border-slate-700 bg-slate-900 p-6"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center gap-2 mb-3">
              <span className="text-lg">{chatIcon(selectedChat.chat_type)}</span>
              <h3 className="text-base font-semibold">{selectedChat.title}</h3>
            </div>
            {selectedChat.username && (
              <p className="text-xs text-slate-400 mb-2">@{selectedChat.username}</p>
            )}
            <div className="space-y-1 text-sm text-slate-300 mb-4">
              <p>
                Members:{" "}
                {loadingMembers ? (
                  <span className="text-slate-500">loading...</span>
                ) : (
                  membersCount ?? selectedChat.members_count
                )}
              </p>
              <p>Type: {selectedChat.chat_type}</p>
              {selectedChat.is_creator && <p className="text-emerald-400">You are the creator</p>}
              {selectedChat.is_admin && !selectedChat.is_creator && (
                <p className="text-amber-400">You are an admin</p>
              )}
            </div>
            <div className="flex gap-2">
              <button
                onClick={() => handleUseAsSource(selectedChat)}
                className="btn btn--primary text-xs"
              >
                Use as Source
              </button>
              <button
                onClick={() => setSelectedChat(null)}
                className="rounded-lg border border-slate-700 px-3 py-1 text-xs font-semibold text-slate-200"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </section>
  );
};

export default AccountChats;
