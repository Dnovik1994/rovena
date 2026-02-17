import { apiFetch } from "../shared/api/client";
import type {
  AccountChat,
  ChatMember,
  InviteCampaign,
  InviteCampaignDetail,
  CreateInviteCampaign,
  ParsedContactsSummary,
  AdminChat,
} from "../types/invite";

// Account chats
export const fetchAccountChats = (token: string, accountId: number) =>
  apiFetch<AccountChat[]>(`/tg-accounts/${accountId}/chats`, {}, token);

export const syncAccount = (token: string, accountId: number) =>
  apiFetch<{ status: string }>(`/tg-accounts/${accountId}/sync`, { method: "POST" }, token);

export const fetchChatMembers = (
  token: string,
  accountId: number,
  chatId: number,
  params?: { limit?: number; offset?: number },
) =>
  apiFetch<ChatMember[]>(
    `/tg-accounts/${accountId}/chats/${chatId}/members?limit=${params?.limit || 50}&offset=${params?.offset || 0}`,
    {},
    token,
  );

export const parseChat = (token: string, accountId: number, chatId: number) =>
  apiFetch<{ status: string; chat_id: number }>(
    `/tg-accounts/${accountId}/chats/${chatId}/parse`,
    { method: "POST" },
    token,
  );

// Parsed contacts
export const fetchParsedContactsSummary = (token: string) =>
  apiFetch<ParsedContactsSummary>("/parsed-contacts/summary", {}, token);

// Admin chats (where user is admin)
export const fetchMyAdminChats = (token: string) =>
  apiFetch<AdminChat[]>("/my-admin-chats", {}, token);

// Invite campaigns
export const fetchInviteCampaigns = (token: string) =>
  apiFetch<InviteCampaign[]>("/invite-campaigns", {}, token);

export const fetchInviteCampaign = (token: string, id: number) =>
  apiFetch<InviteCampaignDetail>(`/invite-campaigns/${id}`, {}, token);

export const createInviteCampaign = (token: string, data: CreateInviteCampaign) =>
  apiFetch<InviteCampaign>("/invite-campaigns", {
    method: "POST",
    body: JSON.stringify(data),
    headers: { "Content-Type": "application/json" },
  }, token);

export const startInviteCampaign = (token: string, id: number) =>
  apiFetch<InviteCampaign>(`/invite-campaigns/${id}/start`, { method: "POST" }, token);

export const pauseInviteCampaign = (token: string, id: number) =>
  apiFetch<InviteCampaign>(`/invite-campaigns/${id}/pause`, { method: "POST" }, token);

export const resumeInviteCampaign = (token: string, id: number) =>
  apiFetch<InviteCampaign>(`/invite-campaigns/${id}/resume`, { method: "POST" }, token);
