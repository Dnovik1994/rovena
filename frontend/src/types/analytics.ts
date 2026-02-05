export interface AnalyticsPoint {
  date: string;
  value: number;
}

export interface DashboardAnalytics {
  window_days: number;
  accounts_created: AnalyticsPoint[];
  campaigns_created: AnalyticsPoint[];
  totals: {
    accounts: number;
    campaigns: number;
  };
}
