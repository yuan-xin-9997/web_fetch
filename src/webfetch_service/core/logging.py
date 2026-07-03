from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

SENSITIVE_HEADERS = {"authorization", "cookie", "proxy-authorization", "set-cookie", "x-api-key"}


def redact_headers(headers: dict[str, str]) -> dict[str, str]:
    return {key: "[REDACTED]" if key.lower() in SENSITIVE_HEADERS else value for key, value in headers.items()}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        data = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key in ("request_id", "job_id", "error_code", "domain", "elapsed_ms"):
            value = getattr(record, key, None)
            if value is not None:
                data[key] = value
        return json.dumps(data, ensure_ascii=False)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())
