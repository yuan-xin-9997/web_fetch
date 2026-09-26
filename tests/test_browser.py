from __future__ import annotations

import sys
from types import ModuleType
from unittest.mock import AsyncMock

import pytest

from webfetch_service.core.config import BrowserSettings, SecuritySettings
from webfetch_service.core.errors import WebFetchError
from webfetch_service.core.security import UrlGuard
from webfetch_service.fetch import BrowserFetcher


async def test_disabled_browser_is_explicit_error() -> None:
    fetcher = BrowserFetcher(BrowserSettings(enabled=False), UrlGuard(SecuritySettings()))
    with pytest.raises(WebFetchError) as caught:
        await fetcher.fetch("https://example.com/")
    assert caught.value.code == "BROWSER_UNAVAILABLE"


@pytest.mark.asyncio
async def test_startup_failure_is_reported_and_readiness_recovers(monkeypatch) -> None:
    fetcher = BrowserFetcher(BrowserSettings(enabled=True), UrlGuard(SecuritySettings()))
    playwright = AsyncMock()
    playwright.chromium.launch.side_effect = RuntimeError("chromium missing")

    class FakePlaywright:
        async def start(self):
            return playwright

    package = ModuleType("playwright")
    module = ModuleType("playwright.async_api")
    module.async_playwright = FakePlaywright
    monkeypatch.setitem(sys.modules, "playwright", package)
    monkeypatch.setitem(sys.modules, "playwright.async_api", module)
    assert await fetcher.is_ready() is False
    assert fetcher._playwright is None
    assert await fetcher.is_ready() is False
    assert playwright.chromium.launch.await_count == 2
