from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from prometheus_client import Counter, Histogram
from redis.asyncio import Redis

from webfetch_service.adapters import AdapterRegistry
from webfetch_service.api.routes import router
from webfetch_service.core.config import Settings, get_settings
from webfetch_service.core.errors import WebFetchError
from webfetch_service.core.ids import new_id
from webfetch_service.core.logging import configure_logging
from webfetch_service.core.security import UrlGuard, api_key_digest
from webfetch_service.fetch import BrowserFetcher, HttpFetcher
from webfetch_service.persistence import Database, JobRepository
from webfetch_service.services.artifacts import ArtifactStore
from webfetch_service.services.cache import MemoryCache, RedisCache
from webfetch_service.services.fetch_service import FetchService
from webfetch_service.services.rate_limit import DomainRateLimiter

REQUESTS = Counter("webfetch_http_requests_total", "HTTP requests", ["method", "path", "status"])
DURATION = Histogram("webfetch_http_request_duration_seconds", "HTTP request duration", ["path"])
logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None, transport: httpx.AsyncBaseTransport | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.server.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await app.state.artifacts.initialize()
        if app.state.database and settings.database.create_schema_on_start:
            await app.state.database.create_schema()
        yield
        await app.state.http_fetcher.close()
        await app.state.browser_fetcher.close()
        await app.state.cache.close()
        if app.state.database:
            await app.state.database.close()

    app = FastAPI(title="WebFetch Service", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.api_key_digest = api_key_digest(settings.auth.bootstrap_api_key.get_secret_value())
    guard = UrlGuard(settings.security)
    proxy_url = settings.proxy.http_url.get_secret_value() if settings.proxy.http_url else None
    app.state.http_fetcher = HttpFetcher(settings.fetch, guard, proxy_url, transport)
    app.state.browser_fetcher = BrowserFetcher(settings.browser, guard, proxy_url)
    if settings.redis.enabled and settings.redis.url:
        redis = Redis.from_url(settings.redis.url.get_secret_value(), decode_responses=True)
        app.state.cache = RedisCache(redis, settings.redis.key_prefix)
    else:
        app.state.cache = MemoryCache()
    app.state.artifacts = ArtifactStore(settings.storage.artifact_root)
    app.state.database = Database(settings.database.url.get_secret_value()) if settings.database.enabled else None
    app.state.jobs = JobRepository(app.state.database) if app.state.database else None
    app.state.adapters = AdapterRegistry()
    limiter = DomainRateLimiter(
        settings.fetch.default_domain_interval_seconds, settings.fetch.default_domain_concurrency
    )
    app.state.fetch_service = FetchService(
        settings, app.state.http_fetcher, app.state.browser_fetcher, app.state.cache, app.state.artifacts, limiter
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or new_id("req")
        request.state.request_id = request_id[:128]
        started = time.monotonic()
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        path = request.scope.get("route").path if request.scope.get("route") else request.url.path
        REQUESTS.labels(request.method, path, response.status_code).inc()
        DURATION.labels(path).observe(time.monotonic() - started)
        return response

    @app.exception_handler(WebFetchError)
    async def domain_error(request: Request, exc: WebFetchError):
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "request_id": getattr(request.state, "request_id", new_id("req")),
                "success": False,
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "retryable": exc.retryable,
                    "retry_after_seconds": exc.retry_after_seconds,
                },
            },
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        logger.info("request validation failed", extra={"request_id": request.state.request_id})
        return JSONResponse(
            status_code=422,
            content={
                "request_id": request.state.request_id,
                "success": False,
                "error": {
                    "code": "INVALID_REQUEST",
                    "message": "请求参数无效",
                    "retryable": False,
                },
            },
        )

    app.include_router(router)
    return app


app = create_app()
