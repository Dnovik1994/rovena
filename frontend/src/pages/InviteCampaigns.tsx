import React, { useCallback, useEffect, useState } from "react";

import EmptyState from "../components/EmptyState";
import SkeletonList from "../components/SkeletonList";
import {
  fetchInviteCampaigns,
  fetchInviteCampaign,
  createInviteCampaign,
  startInviteCampaign,
  pauseInviteCampaign,
  resumeInviteCampaign,
  fetchAccountChats,
} from "../services/inviteApi";
import { fetchTgAccounts } from "../services/resources";
import { useAuth } from "../stores/auth";
import type { InviteCampaign, InviteCampaignDetail, AccountChat, CreateInviteCampaign } from "../types/invite";
import type { TgAccount } from "../types/telegram_account";

/* ── Helper: extract error message ──────────────────────────────── */

function extractError(err: unknown): string {
  if (err && typeof err === "object" && "message" in err) {
    return (err as { message: string }).message;
  }
  return "Unexpected error";
}

/* ── Status badge ───────────────────────────────────────────────── */

const statusStyles: Record<string, string> = {
  draft: "bg-slate-700 text-slate-300",
  active: "bg-emerald-900/60 text-emerald-400",
  paused: "bg-orange-900/60 text-orange-400",
  completed: "bg-blue-900/60 text-blue-400",
  error: "bg-rose-900/60 text-rose-400",
};

function StatusBadge({ status }: { status: string }) {
  return (
    <span
      className={`rounded-full px-2 py-0.5 text-xs font-semibold ${statusStyles[status] || "bg-slate-700 text-slate-300"}`}
    >
      {status}
    </span>
  );
}

/* ── Progress bar ───────────────────────────────────────────────── */

function ProgressBar({ value, max, className }: { value: number; max: number; className?: string }) {
  const percent = max > 0 ? Math.min(100, Math.round((value / max) * 100)) : 0;
  return (
    <div className="h-2 w-full rounded-full bg-slate-800">
      <div
        className={`h-2 rounded-full ${className || "bg-indigo-500/80"}`}
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
  const [formTargetLink, setFormTargetLink] = useState("");
  const [formTargetTitle, setFormTargetTitle] = useState("");
  const [formMaxInvites, setFormMaxInvites] = useState(100);
  const [formInvitesPerHour, setFormInvitesPerHour] = useState(10);
  const [formMaxAccounts, setFormMaxAccounts] = useState(1);

  // Account & chat selection for source
  const [accounts, setAccounts] = useState<TgAccount[]>([]);
  const [selectedAccountId, setSelectedAccountId] = useState<number | null>(null);
  const [accountChats, setAccountChats] = useState<AccountChat[]>([]);
  const [selectedChatId, setSelectedChatId] = useState<number | null>(null);
  const [loadingChats, setLoadingChats] = useState(false);

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

  /* ── Load accounts for form ─── */
  const loadAccounts = useCallback(async () => {
    if (!token) return;
    try {
      const data = await fetchTgAccounts(token);
      // Only show accounts that can be used for inviting
      setAccounts(data.filter((a) => ["verified", "active", "warming", "cooldown"].includes(a.status)));
    } catch {
      // ignore — form will show empty list
    }
  }, [token]);

  /* ── Load chats when account selected ─── */
  useEffect(() => {
    if (!token || !selectedAccountId) {
      setAccountChats([]);
      setSelectedChatId(null);
      return;
    }
    let cancelled = false;
    const loadChats = async () => {
      setLoadingChats(true);
      try {
        const data = await fetchAccountChats(token, selectedAccountId);
        if (!cancelled) {
          // Only show groups/supergroups as source
          setAccountChats(data.filter((c) => c.chat_type !== "channel"));
        }
      } catch {
        if (!cancelled) setAccountChats([]);
      } finally {
        if (!cancelled) setLoadingChats(false);
      }
    };
    loadChats();
    return () => { cancelled = true; };
  }, [token, selectedAccountId]);

  /* ── Pre-fill from sessionStorage (from AccountChats "Use as Source") ─── */
  useEffect(() => {
    const saved = sessionStorage.getItem("invite_source_chat");
    if (saved) {
      try {
        const data = JSON.parse(saved) as {
          account_id: number;
          chat_id: number;
          title: string;
          members_count: number;
        };
        setSelectedAccountId(data.account_id);
        setSelectedChatId(data.chat_id);
        setShowForm(true);
        sessionStorage.removeItem("invite_source_chat");
      } catch {
        // ignore
      }
    }
  }, []);

  /* ── Open create form ─── */
  const handleOpenForm = () => {
    setShowForm(true);
    loadAccounts();
  };

  /* ── Create campaign ─── */
  const handleCreate = async () => {
    if (!token || !selectedChatId) return;
    if (!formName.trim()) {
      setError("Campaign name is required");
      return;
    }
    if (!formTargetLink.trim()) {
      setError("Target link is required");
      return;
    }
    try {
      setFormSubmitting(true);
      setError(null);
      const payload: CreateInviteCampaign = {
        name: formName.trim(),
        source_chat_id: selectedChatId,
        target_link: formTargetLink.trim(),
        max_invites_total: formMaxInvites,
        invites_per_hour_per_account: formInvitesPerHour,
        max_accounts: formMaxAccounts,
      };
      if (formTargetTitle.trim()) {
        payload.target_title = formTargetTitle.trim();
      }
      const created = await createInviteCampaign(token, payload);
      setCampaigns((prev) => [created, ...prev]);
      setShowForm(false);
      resetForm();
      setActionMessage("Campaign created successfully.");
    } catch (err) {
      setError(extractError(err));
    } finally {
      setFormSubmitting(false);
    }
  };

  const resetForm = () => {
    setFormName("");
    setFormTargetLink("");
    setFormTargetTitle("");
    setFormMaxInvites(100);
    setFormInvitesPerHour(10);
    setFormMaxAccounts(1);
    setSelectedAccountId(null);
    setSelectedChatId(null);
    setAccountChats([]);
  };

  /* ── Campaign actions ─── */
  const handleStart = async (id: number) => {
    if (!token) return;
    try {
      setError(null);
      const updated = await startInviteCampaign(token, id);
      setCampaigns((prev) => prev.map((c) => (c.id === id ? updated : c)));
      setActionMessage("Campaign started.");
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
      setActionMessage("Campaign paused.");
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
      setActionMessage("Campaign resumed.");
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
          <h2 className="page__title">Invite Campaigns</h2>
          <p className="page__subtitle">
            Manage invite campaigns to grow your groups.
          </p>
        </div>
        <button
          onClick={handleOpenForm}
          className="btn btn--primary text-xs"
        >
          Create Campaign
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
            <h3 className="text-base font-semibold mb-4">Create Campaign</h3>
            <div className="space-y-3">
              {/* Name */}
              <div>
                <label className="label">Name</label>
                <input
                  className="input"
                  value={formName}
                  onChange={(e) => setFormName(e.target.value)}
                  placeholder="Campaign name"
                />
              </div>

              {/* Account select */}
              <div>
                <label className="label">Account</label>
                <select
                  className="input"
                  value={selectedAccountId ?? ""}
                  onChange={(e) => {
                    const val = e.target.value ? Number(e.target.value) : null;
                    setSelectedAccountId(val);
                    setSelectedChatId(null);
                  }}
                >
                  <option value="">Select account...</option>
                  {accounts.map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.tg_username ? `@${a.tg_username}` : a.phone_e164} ({a.status})
                    </option>
                  ))}
                </select>
              </div>

              {/* Source chat select */}
              <div>
                <label className="label">Source Chat</label>
                {loadingChats ? (
                  <p className="text-xs text-slate-500">Loading chats...</p>
                ) : (
                  <select
                    className="input"
                    value={selectedChatId ?? ""}
                    onChange={(e) => setSelectedChatId(e.target.value ? Number(e.target.value) : null)}
                    disabled={!selectedAccountId}
                  >
                    <option value="">Select source chat...</option>
                    {accountChats.map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.title} ({c.members_count} members)
                      </option>
                    ))}
                  </select>
                )}
              </div>

              {/* Target link */}
              <div>
                <label className="label">Target Link</label>
                <input
                  className="input"
                  value={formTargetLink}
                  onChange={(e) => setFormTargetLink(e.target.value)}
                  placeholder="https://t.me/+invite_link or @username"
                />
              </div>

              {/* Target title */}
              <div>
                <label className="label">Target Title (optional)</label>
                <input
                  className="input"
                  value={formTargetTitle}
                  onChange={(e) => setFormTargetTitle(e.target.value)}
                  placeholder="Target group name"
                />
              </div>

              {/* Max invites */}
              <div>
                <label className="label">Max Invites Total</label>
                <input
                  className="input"
                  type="number"
                  min={1}
                  value={formMaxInvites}
                  onChange={(e) => setFormMaxInvites(Number(e.target.value))}
                />
              </div>

              {/* Invites per hour per account */}
              <div>
                <label className="label">Invites per Hour per Account</label>
                <input
                  className="input"
                  type="number"
                  min={1}
                  value={formInvitesPerHour}
                  onChange={(e) => setFormInvitesPerHour(Number(e.target.value))}
                />
              </div>

              {/* Max accounts */}
              <div>
                <label className="label">Max Accounts</label>
                <input
                  className="input"
                  type="number"
                  min={1}
                  value={formMaxAccounts}
                  onChange={(e) => setFormMaxAccounts(Number(e.target.value))}
                />
              </div>

              {/* Actions */}
              <div className="flex gap-2 pt-2">
                <button
                  onClick={handleCreate}
                  disabled={formSubmitting || !selectedChatId || !formName.trim() || !formTargetLink.trim()}
                  className="btn btn--primary text-xs disabled:opacity-50"
                >
                  {formSubmitting ? "Creating..." : "Create"}
                </button>
                <button
                  onClick={() => { setShowForm(false); resetForm(); }}
                  className="rounded-lg border border-slate-700 px-3 py-1 text-xs font-semibold text-slate-200"
                >
                  Cancel
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
          title="No campaigns yet"
          description="Create an invite campaign to start inviting users."
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
                  {campaign.source_title && <span>Source: {campaign.source_title}</span>}
                  {campaign.target_title && <span>Target: {campaign.target_title}</span>}
                  <span>{formatDate(campaign.created_at)}</span>
                </div>

                {/* ── Progress bar ──── */}
                <div className="mt-3 space-y-1">
                  <div className="flex items-center justify-between text-xs text-slate-400">
                    <span>Progress</span>
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
                      Failed: {campaign.invites_failed}
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
                      className="rounded-lg bg-emerald-600 px-3 py-1 text-xs font-semibold text-white"
                    >
                      Start
                    </button>
                  )}
                  {campaign.status === "active" && (
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        handlePause(campaign.id);
                      }}
                      className="rounded-lg bg-orange-500/80 px-3 py-1 text-xs font-semibold text-white"
                    >
                      Pause
                    </button>
                  )}
                  {campaign.status === "paused" && (
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        handleResume(campaign.id);
                      }}
                      className="rounded-lg bg-emerald-600 px-3 py-1 text-xs font-semibold text-white"
                    >
                      Resume
                    </button>
                  )}
                </div>

                {/* ── Detail view (inline, toggled) ──── */}
                {isDetailOpen && detail && (
                  <div className="mt-4 space-y-3 border-t border-slate-800 pt-3">
                    <h4 className="text-sm font-semibold text-slate-200">Task Breakdown</h4>
                    <div className="space-y-2">
                      {/* Pending */}
                      <div>
                        <div className="flex items-center justify-between text-xs text-slate-400 mb-1">
                          <span>Pending</span>
                          <span>{detail.pending}</span>
                        </div>
                        <ProgressBar value={detail.pending} max={detail.total_tasks} className="bg-slate-500/80" />
                      </div>
                      {/* In Progress */}
                      <div>
                        <div className="flex items-center justify-between text-xs text-slate-400 mb-1">
                          <span>In Progress</span>
                          <span>{detail.in_progress}</span>
                        </div>
                        <ProgressBar value={detail.in_progress} max={detail.total_tasks} className="bg-indigo-500/80" />
                      </div>
                      {/* Success */}
                      <div>
                        <div className="flex items-center justify-between text-xs text-slate-400 mb-1">
                          <span>Success</span>
                          <span>{detail.success}</span>
                        </div>
                        <ProgressBar value={detail.success} max={detail.total_tasks} className="bg-emerald-500/80" />
                      </div>
                      {/* Failed */}
                      <div>
                        <div className="flex items-center justify-between text-xs text-slate-400 mb-1">
                          <span>Failed</span>
                          <span>{detail.failed}</span>
                        </div>
                        <ProgressBar value={detail.failed} max={detail.total_tasks} className="bg-rose-500/80" />
                      </div>
                      {/* Skipped */}
                      <div>
                        <div className="flex items-center justify-between text-xs text-slate-400 mb-1">
                          <span>Skipped</span>
                          <span>{detail.skipped}</span>
                        </div>
                        <ProgressBar value={detail.skipped} max={detail.total_tasks} className="bg-amber-500/80" />
                      </div>
                    </div>
                    <p className="text-xs text-slate-500">
                      Total tasks: {detail.total_tasks}
                    </p>
                  </div>
                )}
                {isDetailOpen && detailLoading && (
                  <div className="mt-4 text-xs text-slate-500">Loading details...</div>
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
