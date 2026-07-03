from __future__ import annotations

import httpx
import pytest
from pydantic import SecretStr

from webfetch_service.core.config import (
    AuthSettings,
    DatabaseSettings,
    FetchSettings,
    SecuritySettings,
    Settings,
    StorageSettings,
)
from webfetch_service.main import create_app

API_KEY = "test-api-key-at-least-16"


def make_settings(tmp_path, database: bool = False) -> Settings:
    return Settings(
        auth=AuthSettings(bootstrap_api_key=SecretStr(API_KEY)),
        fetch=FetchSettings(default_domain_interval_seconds=0, auto_min_html_chars=10, retry_base_seconds=0),
        security=SecuritySettings(allowed_hosts=["test.local"]),
        storage=StorageSettings(artifact_root=tmp_path / "artifacts"),
        database=DatabaseSettings(
            enabled=database,
            url=SecretStr("sqlite+aiosqlite:///:memory:"),
            create_schema_on_start=database,
        ),
    )


def upstream(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        headers={"Content-Type": "text/html; charset=utf-8"},
        text="<html><head><title>T</title></head><body><article><h1>Hello</h1>World</article></body></html>",
    )


@pytest.mark.asyncio
async def test_fetch_auth_cache_artifact_and_extract(tmp_path) -> None:
    app = create_app(make_settings(tmp_path), httpx.MockTransport(upstream))

    async def resolve(host: str, port: int) -> set[str]:
        return {"127.0.0.1"}

    app.state.http_fetcher.guard._resolve = resolve
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://service") as client:
            unauthorized = await client.post("/v1/fetch", json={"url": "http://test.local/"})
            assert unauthorized.status_code == 401
            headers = {"Authorization": f"Bearer {API_KEY}"}
            payload = {"url": "http://test.local/", "mode": "http"}
            first = await client.post("/v1/fetch", json=payload, headers=headers)
            second = await client.post("/v1/fetch", json=payload, headers=headers)
            assert first.status_code == 200
            assert first.json()["artifact_id"].startswith("art_")
            assert second.json()["from_cache"] is True
            extracted = await client.post(
                "/v1/extract",
                headers=headers,
                json={"artifact_id": first.json()["artifact_id"], "adapter": "generic.article"},
            )
            assert extracted.status_code == 200
            assert extracted.json()["data"]["title"] == "Hello"
            extracted_from_url = await client.post(
                "/v1/extract",
                headers=headers,
                json={
                    "url": "http://test.local/",
                    "adapter": "generic.links",
                    "fetch_options": {"url": "http://test.local/", "mode": "http"},
                },
            )
            assert extracted_from_url.status_code == 200
            artifact = await client.get(f"/v1/artifacts/{first.json()['artifact_id']}", headers=headers)
            assert artifact.status_code == 200
            assert "World" in artifact.text
            forbidden_header = await client.post(
                "/v1/fetch",
                headers=headers,
                json={"url": "http://test.local/", "mode": "http", "headers": {"Host": "bad"}},
            )
            assert forbidden_header.status_code == 422
            assert forbidden_header.json()["error"]["code"] == "INVALID_REQUEST"


@pytest.mark.asyncio
async def test_health_and_persistent_job(tmp_path) -> None:
    app = create_app(make_settings(tmp_path, database=True), httpx.MockTransport(upstream))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://service") as client:
            assert (await client.get("/health/live")).status_code == 200
            assert (await client.get("/health/ready")).status_code == 200
            headers = {"Authorization": f"Bearer {API_KEY}"}
            created = await client.post(
                "/v1/jobs", headers=headers, json={"requests": [{"url": "http://test.local/", "mode": "http"}]}
            )
            assert created.status_code == 202
            result = await client.get(f"/v1/jobs/{created.json()['job_id']}", headers=headers)
            assert result.status_code == 200
            assert result.json()["state"] == "queued"
            cancelled = await client.post(f"/v1/jobs/{created.json()['job_id']}/cancel", headers=headers)
            assert cancelled.status_code == 200
            assert cancelled.json()["state"] == "cancelled"


@pytest.mark.asyncio
async def test_ready_reports_dependency_failure(tmp_path) -> None:
    app = create_app(make_settings(tmp_path), httpx.MockTransport(upstream))

    async def broken_ping() -> bool:
        raise RuntimeError("cache down")

    app.state.cache.ping = broken_ping
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://service") as client:
            response = await client.get("/health/ready")
            assert response.status_code == 503
            assert response.json()["checks"]["cache"] is False
