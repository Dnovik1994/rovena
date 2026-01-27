export interface UserProfile {
  id: number;
  telegram_id: number;
  username: string | null;
  first_name: string | null;
  last_name: string | null;
  is_admin: boolean;
  is_active?: boolean;
  role?: string | null;
  onboarding_completed?: boolean;
  tariff?: {
    id: number;
    name: string;
    max_accounts: number;
    max_invites_day: number;
    price: number | null;
  } | null;
}
