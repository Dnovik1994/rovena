from pydantic import BaseModel, field_validator

from app.schemas.tariff import TariffResponse


class UserBase(BaseModel):
    id: int
    telegram_id: int
    username: str | None
    first_name: str | None
    last_name: str | None
    is_admin: bool
    is_active: bool
    role: str | None
    tariff: TariffResponse | None
    onboarding_completed: bool = False

    @field_validator("onboarding_completed", mode="before")
    @classmethod
    def coerce_onboarding_completed(cls, value: bool | None) -> bool:
        if value is None:
            return False
        return bool(value)

    class Config:
        from_attributes = True


class UserResponse(UserBase):
    pass


class UserOnboardingUpdate(BaseModel):
    onboarding_completed: bool
