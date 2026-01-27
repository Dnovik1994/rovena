import html
import re
from typing import Any

from pydantic import BaseModel, ValidationInfo, field_validator

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
