"""核心抓取器 — 统一抓取接口。

自动选择策略：优先简单 HTTP 请求，需要时降级到浏览器渲染。
内置缓存、限速、重试、UA 轮换。
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from .cache import CacheEntry, create_cache, FileCache, RedisCache
from .rate_limit import RateLimiter
from .utils import get_default_headers, get_random_ua, retry

logger = logging.getLogger(__name__)


@dataclass
class FetchResult:
    """抓取结果。"""

    url: str
    status_code: int
    headers: dict[str, str]
    body: str
    from_cache: bool = False
    elapsed: float = 0.0
    rendered_js: bool = False
    error: str | None = None

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 400 and self.error is None

    def __repr__(self) -> str:
        cached = " [cached]" if self.from_cache else ""
        js = " [JS]" if self.rendered_js else ""
        return f"<FetchResult {self.status_code} {self.url}{cached}{js} {self.elapsed:.2f}s>"


class Fetcher:
    """通用网页抓取器。

    Args:
        cache_backend: 缓存后端 ("file" 或 "redis")
        cache_dir: 文件缓存目录
        redis_url: Redis 连接地址
        cache_ttl: 默认缓存有效期（秒），默认 1 小时
        rate_interval: 默认限速间隔（秒），同域名两次请求最小间隔
        rate_per_domain: 按域名自定义限速 {"example.com": 3.0}
        timeout: 请求超时（秒）
        max_retries: 最大重试次数
        proxy: 代理地址
        default_headers: 默认请求头（会与自动生成的合并）
        verify_ssl: 是否验证 SSL 证书
    """

    def __init__(
        self,
        cache_backend: str = "file",
        cache_dir: str | None = None,
        redis_url: str | None = None,
        cache_ttl: int = 3600,
        rate_interval: float = 1.0,
        rate_per_domain: dict[str, float] | None = None,
        timeout: int = 20,
        max_retries: int = 3,
        proxy: str | None = None,
        default_headers: dict[str, str] | None = None,
        verify_ssl: bool = True,
    ) -> None:
        self.cache = create_cache(
            backend=cache_backend,
            cache_dir=cache_dir,
            redis_url=redis_url,
        )
        self.cache_ttl = cache_ttl
        self.rate_limiter = RateLimiter(rate_interval, rate_per_domain)
        self.timeout = timeout
        self.max_retries = max_retries
        self.proxy = proxy
        self.default_headers = default_headers or {}
        self.verify_ssl = verify_ssl

        # 浏览器渲染器（懒加载）
        self._browser: Any = None

    # ------------------------------------------------------------------
    # 主接口
    # ------------------------------------------------------------------

    def get(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
        use_cache: bool = True,
        force_refresh: bool = False,
        render_js: bool = False,
        cache_ttl: int | None = None,
    ) -> FetchResult:
        """抓取一个 URL。

        Args:
            url: 目标 URL
            headers: 额外请求头（会与默认头合并）
            params: 查询参数
            use_cache: 是否使用缓存
            force_refresh: 强制刷新（忽略缓存）
            render_js: 是否用浏览器渲染（慢，仅必要时用）
            cache_ttl: 本次缓存 TTL（覆盖默认值）

        Returns:
            FetchResult
        """
        # 规范化 URL（含查询参数）
        final_url = self._normalize_url(url, params)

        # 1. 检查缓存
        if use_cache and not force_refresh:
            ttl = cache_ttl if cache_ttl is not None else self.cache_ttl
            cached = self.cache.get(final_url, ttl)
            if cached is not None:
                logger.debug("缓存命中: %s", final_url)
                return FetchResult(
                    url=cached.url,
                    status_code=cached.status_code,
                    headers=cached.headers,
                    body=cached.body,
                    from_cache=True,
                )

        # 2. 限速
        waited = self.rate_limiter.wait(final_url)
        if waited > 0:
            logger.debug("限速等待 %.1fs: %s", waited, final_url)

        # 3. 抓取
        start = time.time()
        if render_js:
            result = self._fetch_with_browser(final_url, headers)
        else:
            result = self._fetch_simple(final_url, headers)
        result.elapsed = time.time() - start

        # 4. 缓存成功的响应
        if use_cache and result.ok:
            self.cache.set(CacheEntry(
                url=final_url,
                status_code=result.status_code,
                headers=dict(result.headers),
                body=result.body,
                fetched_at=time.time(),
            ))

        return result

    def get_many(
        self,
        urls: list[str],
        concurrency: int = 5,
        **kwargs: Any,
    ) -> list[FetchResult]:
        """并发抓取多个 URL。

        Args:
            urls: URL 列表
            concurrency: 并发数
            **kwargs: 传给 get() 的额外参数

        Returns:
            与 urls 等长的结果列表（顺序对应）
        """
        import concurrent.futures

        results: list[FetchResult | None] = [None] * len(urls)

        def _fetch(idx: int, url: str) -> tuple[int, FetchResult]:
            return idx, self.get(url, **kwargs)

        with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
            futures = {pool.submit(_fetch, i, u): i for i, u in enumerate(urls)}
            for future in concurrent.futures.as_completed(futures):
                idx, result = future.result()
                results[idx] = result

        return [r for r in results if r is not None]  # type: ignore[list-item]

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _fetch_simple(
        self,
        url: str,
        extra_headers: dict[str, str] | None = None,
    ) -> FetchResult:
        """用 httpx 抓取（无 JS 渲染）。"""
        headers = get_default_headers(url)
        headers.update(self.default_headers)
        if extra_headers:
            headers.update(extra_headers)

        try:
            def _do_request() -> FetchResult:
                with httpx.Client(
                    timeout=self.timeout,
                    proxy=self.proxy,
                    verify=self.verify_ssl,
                    follow_redirects=True,
                ) as client:
                    resp = client.get(url, headers=headers)
                    # 尝试检测编码
                    encoding = resp.encoding or "utf-8"
                    body = resp.content.decode(encoding, errors="replace")
                    return FetchResult(
                        url=str(resp.url),
                        status_code=resp.status_code,
                        headers=dict(resp.headers),
                        body=body,
                    )

            return retry(_do_request, max_attempts=self.max_retries)

        except Exception as e:
            logger.error("抓取失败: %s: %s", url, e)
            return FetchResult(
                url=url,
                status_code=0,
                headers={},
                body="",
                error=str(e),
            )

    def _fetch_with_browser(
        self,
        url: str,
        extra_headers: dict[str, str] | None = None,
    ) -> FetchResult:
        """用 Playwright 抓取（JS 渲染）。"""
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            logger.warning("Playwright 未安装，回退到简单抓取")
            return self._fetch_simple(url, extra_headers)

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=True,
                    proxy={"server": self.proxy} if self.proxy else None,
                )
                context = browser.new_context(
                    user_agent=get_random_ua(),
                    ignore_https_errors=not self.verify_ssl,
                )
                page = context.new_page()
                resp = page.goto(url, wait_until="networkidle", timeout=self.timeout * 1000)

                body = page.content()
                status = resp.status if resp else 200
                headers = dict(resp.headers) if resp else {}

                browser.close()

                return FetchResult(
                    url=url,
                    status_code=status,
                    headers=headers,
                    body=body,
                    rendered_js=True,
                )

        except Exception as e:
            logger.error("浏览器渲染失败: %s: %s", url, e)
            # 降级到简单抓取
            logger.info("降级到简单抓取: %s", url)
            return self._fetch_simple(url, extra_headers)

    @staticmethod
    def _normalize_url(url: str, params: dict[str, Any] | None = None) -> str:
        """规范化 URL（合并查询参数）。"""
        if not params:
            return url
        # httpx 会自动处理，但缓存 key 需要稳定
        from urllib.parse import urlparse, urlencode, parse_qs, urlunparse
        parsed = urlparse(url)
        existing = parse_qs(parsed.query)
        existing.update({k: [str(v)] for k, v in params.items()})
        new_query = urlencode(existing, doseq=True)
        return urlunparse(parsed._replace(query=new_query))

    # ------------------------------------------------------------------
    # 管理方法
    # ------------------------------------------------------------------

    def clear_cache(self) -> int:
        """清空缓存，返回删除数量。"""
        return self.cache.clear()

    def cache_stats(self) -> dict[str, int]:
        """返回缓存统计。"""
        return self.cache.stats()

    def close(self) -> None:
        """清理资源。"""
        if self._browser:
            try:
                self._browser.close()
            except Exception:
                pass
            self._browser = None
