from __future__ import annotations

import asyncio
import email.utils
import random
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from urllib.parse import urljoin

import httpx

from webfetch_service.core.config import FetchSettings
from webfetch_service.core.errors import WebFetchError
from webfetch_service.core.security import UrlGuard
from webfetch_service.schemas import AttemptInfo

RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}
REDIRECT_STATUS = {301, 302, 303, 307, 308}


@dataclass(slots=True)
class RawFetchResult:
    final_url: str
    status_code: int
    headers: dict[str, str]
    body: bytes
    strategy: str
    attempts: list[AttemptInfo] = field(default_factory=list)

    @property
    def content_type(self) -> str:
        return self.headers.get("content-type", "application/octet-stream")


class HttpFetcher:
    def __init__(
        self,
        settings: FetchSettings,
        guard: UrlGuard,
        proxy_url: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.settings = settings
        self.guard = guard
        options = {
            "timeout": settings.timeout_seconds,
            "follow_redirects": False,
            "transport": transport,
            "headers": {
                "User-Agent": "WebFetch/0.1 (+shared-fetch-service)",
                "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
            },
        }
        self.direct_client = httpx.AsyncClient(**options)
        self.proxy_client = httpx.AsyncClient(proxy=proxy_url, **options) if proxy_url else None

    async def close(self) -> None:
        await self.direct_client.aclose()
        if self.proxy_client:
            await self.proxy_client.aclose()

    async def fetch(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        timeout_seconds: float | None = None,
        use_proxy: bool = False,
    ) -> RawFetchResult:
        attempts: list[AttemptInfo] = []
        for attempt in range(1, self.settings.max_attempts + 1):
            started = time.monotonic()
            try:
                result = await self._request_with_redirects(url, headers or {}, timeout_seconds, use_proxy)
                attempts.append(
                    AttemptInfo(
                        sequence=attempt,
                        strategy="http",
                        status_code=result.status_code,
                        elapsed_ms=int((time.monotonic() - started) * 1000),
                    )
                )
                if result.status_code not in RETRYABLE_STATUS or attempt == self.settings.max_attempts:
                    result.attempts = attempts
                    return result
                await asyncio.sleep(self._retry_delay(attempt, result.headers.get("retry-after")))
            except WebFetchError:
                raise
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                code = "READ_TIMEOUT" if isinstance(exc, httpx.TimeoutException) else "CONNECT_FAILED"
                attempts.append(
                    AttemptInfo(
                        sequence=attempt,
                        strategy="http",
                        error_code=code,
                        elapsed_ms=int((time.monotonic() - started) * 1000),
                    )
                )
                if attempt == self.settings.max_attempts:
                    raise WebFetchError(code, "目标网站访问失败", 504, True) from exc
                await asyncio.sleep(self._retry_delay(attempt, None))
        raise AssertionError("retry loop exhausted")

    async def _request_with_redirects(
        self, url: str, headers: dict[str, str], timeout_seconds: float | None, use_proxy: bool
    ) -> RawFetchResult:
        client = self.proxy_client if use_proxy and self.proxy_client else self.direct_client
        current = url
        visited: set[str] = set()
        for _ in range(self.settings.max_redirects + 1):
            guarded = await self.guard.validate(current)
            if guarded.normalized in visited:
                raise WebFetchError("REDIRECT_LOOP", "目标网站重定向循环", 502)
            visited.add(guarded.normalized)
            async with client.stream("GET", guarded.normalized, headers=headers, timeout=timeout_seconds) as response:
                if response.status_code in REDIRECT_STATUS and response.headers.get("location"):
                    current = urljoin(guarded.normalized, response.headers["location"])
                    continue
                chunks: list[bytes] = []
                size = 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > self.settings.max_response_bytes:
                        raise WebFetchError("RESPONSE_TOO_LARGE", "目标响应超过大小限制", 413)
                    chunks.append(chunk)
                return RawFetchResult(
                    final_url=str(response.url),
                    status_code=response.status_code,
                    headers={k.lower(): v for k, v in response.headers.items()},
                    body=b"".join(chunks),
                    strategy="http",
                )
        raise WebFetchError("TOO_MANY_REDIRECTS", "目标网站重定向次数过多", 502)

    def _retry_delay(self, attempt: int, retry_after: str | None) -> float:
        if retry_after:
            try:
                return min(float(retry_after), 300.0)
            except ValueError:
                try:
                    date = email.utils.parsedate_to_datetime(retry_after)
                    return max(0.0, min((date - datetime.now(UTC)).total_seconds(), 300.0))
                except (TypeError, ValueError):
                    pass
        return self.settings.retry_base_seconds * (2 ** (attempt - 1)) + random.uniform(0, 0.1)
