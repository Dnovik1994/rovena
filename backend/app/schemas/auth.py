from pydantic import BaseModel, Field

from app.schemas.sanitization import SanitizedModel


class TelegramAuthRequest(SanitizedModel):
    init_data: str = Field(
        min_length=1,
        max_length=4096,
        json_schema_extra={"skip_sanitize": True},
    )


class RefreshTokenRequest(SanitizedModel):
    refresh_token: str = Field(min_length=20, max_length=2048)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str | None = None
    onboarding_needed: bool | None = None
    token_type: str = "bearer"
