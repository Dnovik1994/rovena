from pydantic import BaseModel

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

    class Config:
        from_attributes = True


class UserResponse(UserBase):
    pass


class UserOnboardingUpdate(BaseModel):
    onboarding_completed: bool
