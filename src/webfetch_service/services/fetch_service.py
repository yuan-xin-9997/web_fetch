from __future__ import annotations

import asyncio
import hashlib
import json
import time
from datetime import UTC, datetime
from urllib.parse import urlsplit

import lxml.html

from webfetch_service.core.config import Settings
from webfetch_service.core.errors import WebFetchError
from webfetch_service.core.ids import new_id
from webfetch_service.fetch import BrowserFetcher, HttpFetcher, RawFetchResult
from webfetch_service.schemas import FetchMode, FetchRequest, FetchResponse, ProxyPolicy

from .artifacts import ArtifactStore
from .cache import Cache, CachedFetch
from .rate_limit import DomainRateLimiter

FORBIDDEN_HEADERS = {"host", "content-length", "connection", "proxy-authorization"}
CHALLENGE_MARKERS = ("enable javascript", "javascript is required", "cf-chl-", "just a moment...")


class FetchService:
    def __init__(
        self,
        settings: Settings,
        http_fetcher: HttpFetcher,
        browser_fetcher: BrowserFetcher,
        cache: Cache,
        artifacts: ArtifactStore,
        rate_limiter: DomainRateLimiter,
    ) -> None:
        self.settings = settings
        self.http_fetcher = http_fetcher
        self.browser_fetcher = browser_fetcher
        self.cache = cache
        self.artifacts = artifacts
        self.rate_limiter = rate_limiter
        self._singleflight: dict[str, asyncio.Lock] = {}
        self._singleflight_guard = asyncio.Lock()

    async def fetch(self, request: FetchRequest, request_id: str | None = None) -> FetchResponse:
        request_id = request_id or new_id("req")
        self._validate_headers(request.headers)
        fetch_key = self._fetch_key(request)
        ttl = self.settings.fetch.default_cache_ttl if request.cache_ttl is None else request.cache_ttl
        if not request.force_refresh and ttl > 0:
            if cached := await self.cache.get(fetch_key):
                return self._cached_response(request_id, request, cached)
        lock = await self._lock_for(fetch_key)
        async with lock:
            if not request.force_refresh and ttl > 0:
                if cached := await self.cache.get(fetch_key):
                    return self._cached_response(request_id, request, cached)
            response = await self._perform(request_id, request)
            if response.success and ttl > 0:
                await self.cache.set(
                    fetch_key,
                    CachedFetch(
                        final_url=response.final_url,
                        status_code=response.status_code,
                        headers={"content-type": response.content_type or ""},
                        body=response.body or "",
                        strategy=response.strategy,
                        artifact_id=response.artifact_id,
                        fetched_at=response.fetched_at.isoformat(),
                    ),
                    ttl,
                )
            return response

    async def _perform(self, request_id: str, request: FetchRequest) -> FetchResponse:
        started = time.monotonic()
        url = str(request.url)
        domain = (urlsplit(url).hostname or "").lower()
        use_proxy = request.proxy_policy == ProxyPolicy.PROXY or (
            request.proxy_policy == ProxyPolicy.AUTO and self.settings.proxy.default_policy == "proxy"
        )
        async with self.rate_limiter.slot(domain):
            if request.mode == FetchMode.BROWSER:
                raw = await self.browser_fetcher.fetch(url, request.headers, request.profile)
            else:
                raw = await self.http_fetcher.fetch(url, request.headers, request.timeout_seconds, use_proxy)
                reason = self._browser_upgrade_reason(raw, request)
                if request.mode == FetchMode.AUTO and reason:
                    http_attempts = raw.attempts
                    raw = await self.browser_fetcher.fetch(url, request.headers, request.profile)
                    if http_attempts:
                        http_attempts[-1].upgrade_reason = reason
                    raw.attempts = http_attempts + raw.attempts
        artifact_id = None
        save = (
            self.settings.storage.save_artifacts_by_default if request.save_artifact is None else request.save_artifact
        )
        fetched_at = datetime.now(UTC)
        if save:
            artifact = await self.artifacts.save(
                raw.body,
                raw.content_type,
                {
                    "request_id": request_id,
                    "requested_url": url,
                    "final_url": raw.final_url,
                    "status_code": raw.status_code,
                    "content_type": raw.content_type,
                    "headers": raw.headers,
                    "strategy": raw.strategy,
                    "fetched_at": fetched_at.isoformat(),
                },
            )
            artifact_id = artifact.id
        return FetchResponse(
            request_id=request_id,
            success=200 <= raw.status_code < 400,
            requested_url=url,
            final_url=raw.final_url,
            status_code=raw.status_code,
            strategy=raw.strategy,
            elapsed_ms=int((time.monotonic() - started) * 1000),
            content_type=raw.content_type,
            body=self._decode(raw.body, raw.content_type),
            artifact_id=artifact_id,
            fetched_at=fetched_at,
            attempts=raw.attempts,
        )

    async def _lock_for(self, key: str) -> asyncio.Lock:
        async with self._singleflight_guard:
            return self._singleflight.setdefault(key, asyncio.Lock())

    def _browser_upgrade_reason(self, result: RawFetchResult, request: FetchRequest) -> str | None:
        if result.status_code in {403, 429, 503}:
            return f"status_{result.status_code}"
        if "html" not in result.content_type.lower():
            return None
        body = self._decode(result.body, result.content_type)
        if len(body.strip()) < self.settings.fetch.auto_min_html_chars:
            return "html_too_short"
        if any(marker in body.lower() for marker in CHALLENGE_MARKERS):
            return "javascript_challenge"
        if request.required_selector:
            try:
                if not lxml.html.fromstring(result.body).cssselect(request.required_selector):
                    return "required_selector_missing"
            except (ValueError, lxml.etree.ParserError):
                return "invalid_html"
        return None

    @staticmethod
    def _validate_headers(headers: dict[str, str]) -> None:
        forbidden = FORBIDDEN_HEADERS.intersection(key.lower() for key in headers)
        if forbidden:
            raise WebFetchError("INVALID_REQUEST", f"禁止设置请求头: {sorted(forbidden)[0]}", 422)

    @staticmethod
    def _fetch_key(request: FetchRequest) -> str:
        headers: dict[str, str] = {}
        for key, value in request.headers.items():
            lowered = key.lower()
            if lowered in {"authorization", "cookie", "x-api-key"}:
                headers[lowered] = "sha256:" + hashlib.sha256(value.encode()).hexdigest()
            elif lowered in {"accept", "accept-language", "content-type"}:
                headers[lowered] = value
        data = {
            "method": "GET",
            "url": str(request.url),
            "mode": request.mode.value,
            "profile": request.profile,
            "proxy_policy": request.proxy_policy.value,
            "headers": headers,
            "save_artifact": request.save_artifact,
        }
        return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    @staticmethod
    def _decode(body: bytes, content_type: str) -> str:
        charset = "utf-8"
        if "charset=" in content_type.lower():
            charset = content_type.lower().split("charset=", 1)[1].split(";", 1)[0].strip()
        try:
            return body.decode(charset, errors="replace")
        except LookupError:
            return body.decode("utf-8", errors="replace")

    @staticmethod
    def _cached_response(request_id: str, request: FetchRequest, cached: CachedFetch) -> FetchResponse:
        return FetchResponse(
            request_id=request_id,
            success=200 <= cached.status_code < 400,
            requested_url=str(request.url),
            final_url=cached.final_url,
            status_code=cached.status_code,
            strategy=cached.strategy,
            from_cache=True,
            elapsed_ms=0,
            content_type=cached.headers.get("content-type"),
            body=cached.body,
            artifact_id=cached.artifact_id,
            fetched_at=datetime.fromisoformat(cached.fetched_at),
        )
