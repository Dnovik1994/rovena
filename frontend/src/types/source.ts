export type SourceType = "group" | "channel";

export interface Source {
  id: number;
  project_id: number;
  owner_id: number;
  name: string;
  link: string;
  type: SourceType;
  created_at: string;
  updated_at: string;
}
