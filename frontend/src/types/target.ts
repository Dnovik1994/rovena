export type TargetType = "group" | "channel";

export interface Target {
  id: number;
  project_id: number;
  owner_id: number;
  name: string;
  link: string;
  type: TargetType;
  created_at: string;
  updated_at: string;
}
