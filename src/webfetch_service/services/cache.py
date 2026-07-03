from __future__ import annotations

import asyncio
import json
import time
from collections import OrderedDict
from dataclasses import asdict, dataclass
from typing import Protocol

from redis.asyncio import Redis


@dataclass(slots=True)
class CachedFetch:
    final_url: str
    status_code: int
    headers: dict[str, str]
    body: str
    strategy: str
    artifact_id: str | None
    fetched_at: str


class Cache(Protocol):
    async def get(self, key: str) -> CachedFetch | None: ...
    async def set(self, key: str, value: CachedFetch, ttl: int) -> None: ...
    async def ping(self) -> bool: ...
    async def close(self) -> None: ...


class MemoryCache:
    def __init__(self, max_entries: int = 1024) -> None:
        self.max_entries = max_entries
        self._items: OrderedDict[str, tuple[float, CachedFetch]] = OrderedDict()
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> CachedFetch | None:
        async with self._lock:
            item = self._items.get(key)
            if item is None:
                return None
            expires_at, value = item
            if expires_at <= time.monotonic():
                self._items.pop(key, None)
                return None
            self._items.move_to_end(key)
            return value

    async def set(self, key: str, value: CachedFetch, ttl: int) -> None:
        if ttl <= 0:
            return
        async with self._lock:
            self._items[key] = (time.monotonic() + ttl, value)
            self._items.move_to_end(key)
            while len(self._items) > self.max_entries:
                self._items.popitem(last=False)

    async def ping(self) -> bool:
        return True

    async def close(self) -> None:
        return None


class RedisCache:
    def __init__(self, redis: Redis, prefix: str = "webfetch:") -> None:
        self.redis = redis
        self.prefix = prefix

    def _key(self, key: str) -> str:
        return f"{self.prefix}cache:{key}"

    async def get(self, key: str) -> CachedFetch | None:
        raw = await self.redis.get(self._key(key))
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        return CachedFetch(**json.loads(raw))

    async def set(self, key: str, value: CachedFetch, ttl: int) -> None:
        if ttl > 0:
            await self.redis.set(self._key(key), json.dumps(asdict(value), ensure_ascii=False), ex=ttl)

    async def ping(self) -> bool:
        return bool(await self.redis.ping())

    async def close(self) -> None:
        await self.redis.aclose()
