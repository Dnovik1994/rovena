from pydantic import BaseModel, field_validator, model_validator

from app.schemas.tariff import TariffResponse

_ADMIN_ROLE_VALUES: frozenset[str] = frozenset({"admin", "superadmin"})


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

    @model_validator(mode="after")
    def derive_is_admin_from_role(self) -> "UserBase":
        """is_admin is always derived from role — single source of truth."""
        self.is_admin = (self.role or "") in _ADMIN_ROLE_VALUES
        return self

    class Config:
        from_attributes = True


class UserResponse(UserBase):
    pass


class UserOnboardingUpdate(BaseModel):
    onboarding_completed: bool
