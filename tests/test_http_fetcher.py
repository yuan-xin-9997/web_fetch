from __future__ import annotations

import httpx
import pytest

from webfetch_service.core.config import FetchSettings, SecuritySettings
from webfetch_service.core.errors import WebFetchError
from webfetch_service.core.security import UrlGuard
from webfetch_service.fetch import HttpFetcher


async def public_resolve(host: str, port: int) -> set[str]:
    return {"93.184.216.34"}


async def test_http_fetcher_retries_status(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls < 3:
            return httpx.Response(503, headers={"Retry-After": "0"})
        return httpx.Response(200, headers={"Content-Type": "text/plain; charset=utf-8"}, content="成功".encode())

    guard = UrlGuard(SecuritySettings())
    monkeypatch.setattr(guard, "_resolve", public_resolve)
    fetcher = HttpFetcher(
        FetchSettings(max_attempts=3, retry_base_seconds=0), guard, transport=httpx.MockTransport(handler)
    )
    try:
        result = await fetcher.fetch("https://example.com/")
        assert result.status_code == 200
        assert calls == 3
        assert len(result.attempts) == 3
    finally:
        await fetcher.close()


async def test_redirect_target_is_guarded(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"Location": "http://127.0.0.1/private"})

    async def resolve(host: str, port: int) -> set[str]:
        return {"127.0.0.1"} if host == "127.0.0.1" else {"93.184.216.34"}

    guard = UrlGuard(SecuritySettings())
    monkeypatch.setattr(guard, "_resolve", resolve)
    fetcher = HttpFetcher(FetchSettings(max_attempts=1), guard, transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(WebFetchError) as caught:
            await fetcher.fetch("https://example.com/")
        assert caught.value.code == "DOMAIN_NOT_ALLOWED"
    finally:
        await fetcher.close()


async def test_response_size_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    guard = UrlGuard(SecuritySettings())
    monkeypatch.setattr(guard, "_resolve", public_resolve)
    fetcher = HttpFetcher(
        FetchSettings(max_attempts=1, max_response_bytes=1024),
        guard,
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b"x" * 1025)),
    )
    try:
        with pytest.raises(WebFetchError) as caught:
            await fetcher.fetch("https://example.com/")
        assert caught.value.code == "RESPONSE_TOO_LARGE"
    finally:
        await fetcher.close()
