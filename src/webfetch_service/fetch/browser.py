from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from webfetch_service.core.config import BrowserSettings
from webfetch_service.core.errors import WebFetchError
from webfetch_service.core.security import UrlGuard
from webfetch_service.schemas import AttemptInfo

from .http import RawFetchResult

logger = logging.getLogger(__name__)


class BrowserFetcher:
    def __init__(self, settings: BrowserSettings, guard: UrlGuard, proxy_url: str | None = None) -> None:
        self.settings = settings
        self.guard = guard
        self.proxy_url = proxy_url
        self._playwright: Any = None
        self._browser: Any = None
        self._lock = asyncio.Lock()
        self._semaphore = asyncio.Semaphore(settings.concurrency)

    async def start(self) -> None:
        if not self.settings.enabled:
            return
        async with self._lock:
            if self._browser is not None and self._browser.is_connected():
                return
            await self.close()
            try:
                from playwright.async_api import async_playwright
            except ImportError as exc:
                raise WebFetchError("BROWSER_UNAVAILABLE", "浏览器运行依赖未安装", 503) from exc
            try:
                self._playwright = await async_playwright().start()
                self._browser = await self._playwright.chromium.launch(headless=True)
            except Exception as exc:
                logger.exception("browser startup failed")
                await self.close()
                raise WebFetchError("BROWSER_UNAVAILABLE", "浏览器启动失败", 503, True) from exc

    async def is_ready(self) -> bool:
        if not self.settings.enabled:
            return True
        try:
            await self.start()
            return bool(self._browser and self._browser.is_connected())
        except WebFetchError:
            return False

    async def close(self) -> None:
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None

    async def fetch(
        self, url: str, headers: dict[str, str] | None = None, profile: str = "anonymous", use_proxy: bool = False
    ) -> RawFetchResult:
        del profile
        if not self.settings.enabled:
            raise WebFetchError("BROWSER_UNAVAILABLE", "浏览器抓取未启用", 503)
        await self.guard.validate(url)
        await self.start()
        started = time.monotonic()
        async with self._semaphore:
            options: dict[str, Any] = {"extra_http_headers": headers or {}}
            if use_proxy and self.proxy_url:
                options["proxy"] = {"server": self.proxy_url}
            try:
                context = await self._browser.new_context(**options)
            except Exception as exc:
                logger.exception("browser context creation failed")
                raise WebFetchError("BROWSER_FAILED", "浏览器抓取失败", 502, True) from exc
            try:
                page = await context.new_page()

                async def guarded_route(route) -> None:
                    try:
                        await self.guard.validate(route.request.url)
                    except WebFetchError:
                        await route.abort("blockedbyclient")
                    else:
                        await route.continue_()

                await page.route("**/*", guarded_route)
                response = await page.goto(
                    url, wait_until="networkidle", timeout=int(self.settings.navigation_timeout_seconds * 1000)
                )
                final = await self.guard.validate(page.url)
                body = (await page.content()).encode("utf-8")
                status = response.status if response else 200
                response_headers = await response.all_headers() if response else {}
                elapsed = int((time.monotonic() - started) * 1000)
                return RawFetchResult(
                    final_url=final.normalized,
                    status_code=status,
                    headers={k.lower(): v for k, v in response_headers.items()},
                    body=body,
                    strategy="browser",
                    attempts=[AttemptInfo(sequence=1, strategy="browser", status_code=status, elapsed_ms=elapsed)],
                )
            except WebFetchError:
                raise
            except Exception as exc:
                logger.exception("browser navigation failed")
                raise WebFetchError("BROWSER_FAILED", "浏览器抓取失败", 502, True) from exc
            finally:
                await context.close()
