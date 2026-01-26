from pydantic import BaseModel, Field


class TariffBase(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    max_accounts: int = Field(ge=1)
    max_invites_day: int = Field(ge=1)
    price: float | None = Field(default=None, ge=0)


class TariffCreate(TariffBase):
    pass


class TariffUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    max_accounts: int | None = Field(default=None, ge=1)
    max_invites_day: int | None = Field(default=None, ge=1)
    price: float | None = Field(default=None, ge=0)


class TariffResponse(TariffBase):
    id: int

    class Config:
        from_attributes = True


class UserTariffUpdate(BaseModel):
    tariff_id: int = Field(ge=1)
