"""限速器 — 按域名独立限速，避免被封。"""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from urllib.parse import urlparse


class RateLimiter:
    """按域名限速器。

    每个域名独立计数，超过限制的请求会等待。
    线程安全。

    Args:
        default_interval: 默认同域名两次请求最小间隔（秒）
        per_domain: 按域名自定义间隔 {"example.com": 2.0}
    """

    def __init__(
        self,
        default_interval: float = 1.0,
        per_domain: dict[str, float] | None = None,
    ) -> None:
        self.default_interval = default_interval
        self.per_domain = per_domain or {}
        self._last_request: dict[str, float] = defaultdict(float)
        self._lock = threading.Lock()

    def _get_domain(self, url: str) -> str:
        parsed = urlparse(url)
        return parsed.netloc.lower()

    def _get_interval(self, domain: str) -> float:
        return self.per_domain.get(domain, self.default_interval)

    def wait(self, url: str) -> float:
        """如果需要等待则阻塞，返回实际等待的秒数。"""
        domain = self._get_domain(url)
        interval = self._get_interval(domain)

        with self._lock:
            now = time.time()
            elapsed = now - self._last_request[domain]
            if elapsed < interval:
                sleep_time = interval - elapsed
                # 释放锁后 sleep
                pass
            else:
                sleep_time = 0
            self._last_request[domain] = now + sleep_time

        if sleep_time > 0:
            time.sleep(sleep_time)

        return sleep_time
