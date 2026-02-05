from pydantic import BaseModel, Field


class AnalyticsPoint(BaseModel):
    date: str
    value: int = Field(ge=0)


class DashboardAnalyticsResponse(BaseModel):
    window_days: int
    accounts_created: list[AnalyticsPoint]
    campaigns_created: list[AnalyticsPoint]
    totals: dict[str, int]
