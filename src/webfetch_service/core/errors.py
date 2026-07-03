from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class WebFetchError(Exception):
    code: str
    message: str
    status_code: int = 500
    retryable: bool = False
    retry_after_seconds: float | None = None

    def __str__(self) -> str:
        return self.message


def invalid_request(message: str) -> WebFetchError:
    return WebFetchError("INVALID_REQUEST", message, 422)


def authentication_failed() -> WebFetchError:
    return WebFetchError("AUTHENTICATION_FAILED", "API key无效", 401)
