from __future__ import annotations

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
