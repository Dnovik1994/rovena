export interface AccountChat {
  id: number;
  chat_id: number;
  title: string;
  username: string | null;
  chat_type: "group" | "supergroup" | "channel";
  members_count: number;
  is_creator: boolean;
  is_admin: boolean;
  last_parsed_at: string | null;
}

export interface ChatMember {
  id: number;
  telegram_id: number;
  username: string | null;
  first_name: string | null;
  last_name: string | null;
  is_premium: boolean;
  last_online_at: string | null;
}

export interface InviteCampaign {
  id: number;
  name: string;
  status: "draft" | "active" | "paused" | "completed" | "error";
  source_chat_id: number;
  source_title: string | null;
  target_link: string;
  target_title: string | null;
  max_invites_total: number;
  invites_per_hour_per_account: number;
  max_accounts: number;
  invites_completed: number;
  invites_failed: number;
  created_at: string;
}

export interface InviteCampaignDetail extends InviteCampaign {
  total_tasks: number;
  pending: number;
  in_progress: number;
  success: number;
  failed: number;
  skipped: number;
}

export interface CreateInviteCampaign {
  name: string;
  target_chat_id: number;
  max_invites_total: number;
  invites_per_hour_per_account: number;
  max_accounts: number;
  source_chat_id?: number | null;
}

export interface ParsedContactsSummary {
  total_contacts: number;
  chats: ParsedChatInfo[];
}

export interface ParsedChatInfo {
  chat_id: number;
  title: string;
  chat_type: string;
  members_parsed: number;
  last_parsed_at: string;
}

export interface AdminChat {
  id: number;
  chat_id: number;
  title: string;
  username: string | null;
  chat_type: string;
  members_count: number;
}
