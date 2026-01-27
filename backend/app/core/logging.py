import json
import logging
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any

import structlog

request_id_ctx_var: ContextVar[str | None] = ContextVar("request_id", default=None)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        request_id = request_id_ctx_var.get()
        if request_id:
            payload["request_id"] = request_id
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def _add_request_id(_, __, event_dict: dict[str, Any]) -> dict[str, Any]:
    request_id = request_id_ctx_var.get()
    if request_id:
        event_dict["request_id"] = request_id
    return event_dict


def configure_logging(production: bool = False) -> None:
    handler = logging.StreamHandler()
    if production:
        processor = structlog.processors.JSONRenderer()
        formatter = structlog.stdlib.ProcessorFormatter(
            processor=processor,
            foreign_pre_chain=[
                structlog.processors.TimeStamper(fmt="iso"),
                structlog.processors.add_log_level,
                _add_request_id,
            ],
        )
        handler.setFormatter(formatter)
        structlog.configure(
            processors=[
                structlog.processors.TimeStamper(fmt="iso"),
                structlog.processors.add_log_level,
                _add_request_id,
                structlog.processors.format_exc_info,
                structlog.processors.JSONRenderer(),
            ],
            logger_factory=structlog.stdlib.LoggerFactory(),
            wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
            cache_logger_on_first_use=True,
        )
    else:
        handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers = [handler]
