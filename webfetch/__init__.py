"""webfetch — 通用网页抓取共享库。

提供统一的网页抓取接口，内置缓存、限速、重试、UA 轮换、
JS 渲染降级等能力。所有项目共享同一份代码和缓存。
"""

from .fetcher import Fetcher, FetchResult
from .cache import FileCache, RedisCache, create_cache, CacheEntry

__version__ = "0.1.0"

__all__ = [
    "Fetcher",
    "FetchResult",
    "FileCache",
    "RedisCache",
    "create_cache",
    "CacheEntry",
]
