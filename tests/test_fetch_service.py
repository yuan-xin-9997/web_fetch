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
