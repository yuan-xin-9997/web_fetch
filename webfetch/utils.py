"""工具函数 — UA 轮换、重试、URL 处理。"""

from __future__ import annotations

import random
import time
import logging
from typing import Callable, Any, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

# 常用 User-Agent 池
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
]


def get_random_ua() -> str:
    """随机返回一个 User-Agent。"""
    return random.choice(USER_AGENTS)


def get_default_headers(url: str | None = None) -> dict[str, str]:
    """返回带随机 UA 的默认请求头。"""
    headers = {
        "User-Agent": get_random_ua(),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }
    if url:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        if parsed.netloc:
            headers["Referer"] = f"{parsed.scheme}://{parsed.netloc}/"
    return headers


def retry(
    fn: Callable[..., T],
    max_attempts: int = 3,
    delay: float = 1.0,
    backoff: float = 2.0,
    exceptions: tuple = (Exception,),
) -> T:
    """带指数退避的重试。

    Args:
        fn: 要执行的函数
        max_attempts: 最大尝试次数
        delay: 首次重试延迟（秒）
        backoff: 退避倍数
        exceptions: 触发重试的异常类型

    Returns:
        fn 的返回值
    """
    last_exc: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return fn()
        except exceptions as e:
            last_exc = e
            if attempt == max_attempts:
                logger.error("重试 %d 次后失败: %s", max_attempts, e)
                raise
            wait = delay * (backoff ** (attempt - 1))
            # 加点随机抖动
            wait += random.uniform(0, 0.5)
            logger.warning("第 %d 次尝试失败 (%s)，%.1fs 后重试", attempt, e, wait)
            time.sleep(wait)
    # 不会执行到这里，但让类型检查满意
    raise last_exc  # type: ignore[misc]
