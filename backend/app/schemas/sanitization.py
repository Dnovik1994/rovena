import html
import re
from typing import Any

from pydantic import BaseModel, ValidationInfo, field_validator

# Detect suspicious SQL patterns more robustly:
# 1. SQL keywords combined with structural characters (quotes, comments, semicolons)
# 2. Catches common bypass attempts like UNION/**/SELECT, 0x hex encoding hints
_SQL_KEYWORDS = re.compile(
    r"\b(union|select|insert|update|delete|drop|alter|create|exec|execute|xp_|sp_|0x)\b",
    re.IGNORECASE,
)
_SQL_STRUCTURAL = re.compile(
    r"(--|;|/\*|\*/|\\x[0-9a-fA-F]{2}|['\"`])",
)

# Dangerous HTML/JS patterns (common XSS vectors)
_XSS_PATTERN = re.compile(
    r"(javascript\s*:|on\w+\s*=)",
    re.IGNORECASE,
)

# Null bytes (can cause truncation attacks)
_NULL_BYTE = re.compile(r"\x00")


def _sanitize_string(value: str, max_length: int) -> str:
    trimmed = value.strip()

    if _NULL_BYTE.search(trimmed):
        raise ValueError("Input contains null bytes")

    if len(trimmed) > max_length:
        raise ValueError("Value exceeds maximum length")

    # Block inputs that combine SQL keywords with structural injection characters
    if _SQL_KEYWORDS.search(trimmed) and _SQL_STRUCTURAL.search(trimmed):
        raise ValueError("Potentially unsafe input")

    # Block obvious XSS payloads before escaping
    if _XSS_PATTERN.search(trimmed):
        raise ValueError("Potentially unsafe HTML content")

    return html.escape(trimmed, quote=True)


class SanitizedModel(BaseModel):
    @field_validator("*", mode="before")
    def sanitize_fields(cls, value: Any, info: ValidationInfo):  # noqa: N805
        if value is None:
            return value
        field_name = info.field_name
        field = cls.model_fields.get(field_name) if field_name else None
        max_length = getattr(field, "max_length", None) if field else None
        skip_sanitize = False
        json_schema_extra = field.json_schema_extra if field else None
        if isinstance(json_schema_extra, dict):
            skip_sanitize = json_schema_extra.get("skip_sanitize", False)
        if field:
            for metadata in field.metadata:
                meta_max_length = getattr(metadata, "max_length", None)
                if meta_max_length is not None:
                    max_length = meta_max_length
        if skip_sanitize:
            return value
        max_length = max_length or 2048
        if isinstance(value, str):
            return _sanitize_string(value, max_length)
        if isinstance(value, list):
            return [
                _sanitize_string(item, max_length) if isinstance(item, str) else item
                for item in value
            ]
        return value
