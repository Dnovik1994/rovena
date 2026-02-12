from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class ErrorDetail(BaseModel):
    code: str
    message: str
    status: int
    details: Any | None = None


class ErrorResponse(BaseModel):
    error: ErrorDetail
