from __future__ import annotations

import pytest

from webfetch_service.core.config import SecuritySettings
from webfetch_service.core.errors import WebFetchError
from webfetch_service.core.security import UrlGuard, api_key_digest, constant_time_key_matches


def test_api_key_digest_matching() -> None:
    digest = api_key_digest("a-long-test-api-key")
    assert constant_time_key_matches("a-long-test-api-key", digest)
    assert not constant_time_key_matches("wrong-test-api-key", digest)


@pytest.mark.asyncio
async def test_url_guard_rejects_private_address(monkeypatch: pytest.MonkeyPatch) -> None:
    guard = UrlGuard(SecuritySettings())

    async def resolve(host: str, port: int) -> set[str]:
        return {"127.0.0.1"}

    monkeypatch.setattr(guard, "_resolve", resolve)
    with pytest.raises(WebFetchError, match="不允许") as caught:
        await guard.validate("http://internal.example/path")
    assert caught.value.code == "DOMAIN_NOT_ALLOWED"


@pytest.mark.asyncio
async def test_url_guard_allows_explicit_host(monkeypatch: pytest.MonkeyPatch) -> None:
    guard = UrlGuard(SecuritySettings(allowed_hosts=["internal.example"]))

    async def resolve(host: str, port: int) -> set[str]:
        return {"10.0.0.2"}

    monkeypatch.setattr(guard, "_resolve", resolve)
    result = await guard.validate("https://internal.example:8443/path#fragment")
    assert result.normalized == "https://internal.example:8443/path"


@pytest.mark.asyncio
async def test_url_guard_rejects_credentials() -> None:
    guard = UrlGuard(SecuritySettings())
    with pytest.raises(WebFetchError) as caught:
        await guard.validate("https://user:password@example.com/")
    assert caught.value.code == "INVALID_REQUEST"
