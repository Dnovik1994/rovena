import html
import re
from typing import Any

from pydantic import BaseModel, validator

SQLI_PATTERN = re.compile(
    r"(--|;|/\*|\*/|\bunion\b|\bselect\b|\binsert\b|\bupdate\b|\bdelete\b|\bdrop\b|\balter\b|\bcreate\b|\bexec\b)",
    re.IGNORECASE,
)


def _sanitize_string(value: str, max_length: int) -> str:
    trimmed = value.strip()
    if len(trimmed) > max_length:
        raise ValueError("Value exceeds maximum length")
    if SQLI_PATTERN.search(trimmed) and re.search(r"(--|;|/\*|\*/|['\"])", trimmed):
        raise ValueError("Potentially unsafe input")
    return html.escape(trimmed, quote=True)


class SanitizedModel(BaseModel):
    @validator("*", pre=True)
    def sanitize_fields(cls, value: Any, field):  # noqa: N805
        if value is None:
            return value
        if field.field_info.extra.get("skip_sanitize"):
            return value
        max_length = field.field_info.max_length or 2048
        if isinstance(value, str):
            return _sanitize_string(value, max_length)
        if isinstance(value, list):
            return [
                _sanitize_string(item, max_length) if isinstance(item, str) else item
                for item in value
            ]
        return value
