export type CampaignStatus = "draft" | "active" | "paused" | "completed";

export interface Campaign {
  id: number;
  project_id: number;
  owner_id: number;
  name: string;
  status: CampaignStatus;
  source_id: number | null;
  target_id: number | null;
  max_invites_per_hour: number;
  max_invites_per_day: number;
  progress: number;
  start_at: string | null;
  end_at: string | null;
  created_at: string;
}
