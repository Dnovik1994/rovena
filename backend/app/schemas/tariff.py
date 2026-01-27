from pydantic import BaseModel, Field

from app.schemas.sanitization import SanitizedModel


class TariffBase(SanitizedModel):
    name: str = Field(min_length=1, max_length=64)
    max_accounts: int = Field(ge=1)
    max_invites_day: int = Field(ge=1)
    price: float | None = Field(default=None, ge=0)


class TariffCreate(TariffBase):
    pass


class TariffUpdate(SanitizedModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    max_accounts: int | None = Field(default=None, ge=1)
    max_invites_day: int | None = Field(default=None, ge=1)
    price: float | None = Field(default=None, ge=0)


class TariffResponse(TariffBase):
    id: int

    class Config:
        from_attributes = True


class UserTariffUpdate(SanitizedModel):
    tariff_id: int = Field(ge=1)
