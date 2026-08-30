from __future__ import annotations

from pydantic import SecretStr

from webfetch_service.core.config import AuthSettings, Settings
from webfetch_service.schemas import FetchRequest
from webfetch_service.services.fetch_service import FetchService


def test_fetch_key_separates_identity_and_mode() -> None:
    base = FetchRequest(url="https://example.com/", mode="http", headers={"Authorization": "Bearer first"})
    other_auth = FetchRequest(url="https://example.com/", mode="http", headers={"Authorization": "Bearer second"})
    browser = FetchRequest(url="https://example.com/", mode="browser", headers={"Authorization": "Bearer first"})
    assert FetchService._fetch_key(base) != FetchService._fetch_key(other_auth)
    assert FetchService._fetch_key(base) != FetchService._fetch_key(browser)
    assert "first" not in FetchService._fetch_key(base)


def test_fetch_key_separates_artifact_requirement() -> None:
    default_artifact = FetchRequest(url="https://example.com/", mode="auto", save_artifact=None)
    without_artifact = FetchRequest(url="https://example.com/", mode="auto", save_artifact=False)
    with_artifact = FetchRequest(url="https://example.com/", mode="auto", save_artifact=True)

    assert FetchService._fetch_key(default_artifact) != FetchService._fetch_key(without_artifact)
    assert FetchService._fetch_key(default_artifact) != FetchService._fetch_key(with_artifact)
    assert FetchService._fetch_key(without_artifact) != FetchService._fetch_key(with_artifact)


def test_production_rejects_default_key() -> None:
    settings = Settings(
        environment="production", auth=AuthSettings(bootstrap_api_key=SecretStr("change-me-before-production"))
    )
    try:
        settings.validate_production()
    except ValueError as exc:
        assert "forbidden" in str(exc)
    else:
        raise AssertionError("default key accepted")


def _fallback_service(http_fetcher, browser_fetcher) -> FetchService:
    from webfetch_service.services.cache import MemoryCache
    from webfetch_service.services.rate_limit import DomainRateLimiter

    return FetchService(
        settings=Settings(),
        http_fetcher=http_fetcher,
        browser_fetcher=browser_fetcher,
        cache=MemoryCache(),
        artifacts=None,
        rate_limiter=DomainRateLimiter(interval_seconds=0, concurrency=4),
    )


async def test_browser_mode_falls_back_to_http_when_allowed(tmp_path) -> None:
    from unittest.mock import AsyncMock

    from webfetch_service.core.errors import WebFetchError
    from webfetch_service.fetch.http import RawFetchResult

    raw_http = RawFetchResult(
        final_url="https://example.com/list",
        status_code=200,
        headers={"content-type": "text/html; charset=utf-8"},
        body=b"<html><body>rendered-fallback</body></html>",
        strategy="http",
    )
    browser = AsyncMock()
    browser.fetch = AsyncMock(side_effect=WebFetchError("BROWSER_FAILED", "浏览器抓取失败", 502, True))
    http = AsyncMock()
    http.fetch = AsyncMock(return_value=raw_http)
    service = _fallback_service(http, browser)

    response = await service.fetch(
        FetchRequest(
            url="https://example.com/list",
            mode="browser",
            http_fallback=True,
            save_artifact=False,
            cache_ttl=0,
        ),
        "req-fallback",
    )

    assert response.strategy == "http"
    assert response.body == "<html><body>rendered-fallback</body></html>"
    browser.fetch.assert_awaited_once()
    http.fetch.assert_awaited_once()


async def test_browser_mode_failure_propagates_without_fallback(tmp_path) -> None:
    from unittest.mock import AsyncMock

    import pytest

    from webfetch_service.core.errors import WebFetchError
    from webfetch_service.fetch.http import RawFetchResult

    browser = AsyncMock()
    browser.fetch = AsyncMock(side_effect=WebFetchError("BROWSER_FAILED", "浏览器抓取失败", 502, True))
    http = AsyncMock()
    http.fetch = AsyncMock(
        return_value=RawFetchResult(
            final_url="https://example.com/list",
            status_code=200,
            headers={"content-type": "text/html"},
            body=b"<html></html>",
            strategy="http",
        )
    )
    service = _fallback_service(http, browser)

    with pytest.raises(WebFetchError) as caught:
        await service.fetch(
            FetchRequest(
                url="https://example.com/list",
                mode="browser",
                save_artifact=False,
                cache_ttl=0,
            ),
            "req-no-fallback",
        )

    assert caught.value.code == "BROWSER_FAILED"
    http.fetch.assert_not_awaited()
