export interface Contact {
  id: number;
  project_id: number;
  owner_id: number;
  telegram_id: number;
  first_name: string;
  last_name: string | null;
  username: string | null;
  phone: string | null;
  tags: string[] | null;
  source_id: number | null;
  blocked: boolean;
  blocked_reason: string | null;
  created_at: string;
}
