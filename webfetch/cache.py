"""缓存层 — 避免重复抓取相同 URL。

支持文件缓存（默认）和 Redis 缓存（可选）。
缓存的不仅是 HTML，还有状态码、响应头和时间戳，
过期后自动失效。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class CacheEntry:
    """单条缓存记录。"""

    __slots__ = ("url", "status_code", "headers", "body", "fetched_at", "encoding")

    def __init__(
        self,
        url: str,
        status_code: int,
        headers: dict[str, str],
        body: str,
        fetched_at: float,
        encoding: str = "utf-8",
    ) -> None:
        self.url = url
        self.status_code = status_code
        self.headers = headers
        self.body = body
        self.fetched_at = fetched_at
        self.encoding = encoding

    def is_expired(self, ttl: int) -> bool:
        """是否已过期。ttl <= 0 表示永不过期。"""
        if ttl <= 0:
            return False
        return time.time() - self.fetched_at > ttl

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "status_code": self.status_code,
            "headers": self.headers,
            "body": self.body,
            "fetched_at": self.fetched_at,
            "encoding": self.encoding,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> CacheEntry:
        return cls(**d)


class FileCache:
    """文件缓存 — 默认后端，零依赖。"""

    def __init__(self, cache_dir: str | Path) -> None:
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _url_to_hash(url: str) -> str:
        return hashlib.sha256(url.encode()).hexdigest()

    def _cache_path(self, url: str) -> Path:
        h = self._url_to_hash(url)
        # 用前2位做子目录，避免单目录文件过多
        sub = self.cache_dir / h[:2]
        sub.mkdir(exist_ok=True)
        return sub / f"{h}.json"

    def get(self, url: str, ttl: int) -> CacheEntry | None:
        """读取缓存。ttl 为缓存有效期（秒），<=0 永不过期。"""
        path = self._cache_path(url)
        if not path.exists():
            return None
        try:
            entry = CacheEntry.from_dict(json.loads(path.read_text()))
            if entry.is_expired(ttl):
                logger.debug("缓存过期: %s", url)
                return None
            logger.debug("缓存命中: %s", url)
            return entry
        except Exception as e:
            logger.warning("读取缓存失败: %s: %s", url, e)
            return None

    def set(self, entry: CacheEntry) -> None:
        """写入缓存。"""
        path = self._cache_path(entry.url)
        try:
            path.write_text(json.dumps(entry.to_dict(), ensure_ascii=False))
        except Exception as e:
            logger.warning("写入缓存失败: %s: %s", entry.url, e)

    def delete(self, url: str) -> None:
        """删除指定 URL 的缓存。"""
        path = self._cache_path(url)
        if path.exists():
            path.unlink()

    def clear(self) -> int:
        """清空所有缓存，返回删除数量。"""
        count = 0
        for f in self.cache_dir.rglob("*.json"):
            f.unlink()
            count += 1
        return count

    def stats(self) -> dict[str, int]:
        """返回缓存统计。"""
        files = list(self.cache_dir.rglob("*.json"))
        total_size = sum(f.stat().st_size for f in files)
        return {"entries": len(files), "size_bytes": total_size}


class RedisCache:
    """Redis 缓存 — 可选后端，适合多进程共享。"""

    def __init__(self, redis_url: str, prefix: str = "webfetch:") -> None:
        import redis  # 延迟导入
        self.r = redis.from_url(redis_url, decode_responses=True)
        self.prefix = prefix
        self._test_connection()

    def _test_connection(self) -> None:
        try:
            self.r.ping()
        except Exception as e:
            raise RuntimeError(f"Redis 连接失败: {e}") from e

    def _key(self, url: str) -> str:
        h = hashlib.sha256(url.encode()).hexdigest()
        return f"{self.prefix}{h}"

    def get(self, url: str, ttl: int) -> CacheEntry | None:
        raw = self.r.get(self._key(url))
        if not raw:
            return None
        try:
            entry = CacheEntry.from_dict(json.loads(raw))
            if entry.is_expired(ttl):
                self.r.delete(self._key(url))
                return None
            return entry
        except Exception:
            return None

    def set(self, entry: CacheEntry) -> None:
        ttl = 0  # Redis 自带 TTL，但这里用 fetched_at 自己管
        self.r.set(self._key(entry.url), json.dumps(entry.to_dict(), ensure_ascii=False))

    def delete(self, url: str) -> None:
        self.r.delete(self._key(url))

    def clear(self) -> int:
        keys = self.r.keys(f"{self.prefix}*")
        if keys:
            self.r.delete(*keys)
        return len(keys)

    def stats(self) -> dict[str, int]:
        keys = self.r.keys(f"{self.prefix}*")
        return {"entries": len(keys), "size_bytes": 0}


def create_cache(
    backend: str = "file",
    cache_dir: str | Path | None = None,
    redis_url: str | None = None,
) -> FileCache | RedisCache:
    """工厂函数，创建缓存后端。"""
    if backend == "redis":
        if not redis_url:
            raise ValueError("Redis 后端需要 redis_url 参数")
        return RedisCache(redis_url)
    # 默认文件缓存
    if cache_dir is None:
        cache_dir = Path.home() / ".cache" / "webfetch"
    return FileCache(cache_dir)
