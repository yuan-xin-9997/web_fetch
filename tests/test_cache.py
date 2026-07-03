from __future__ import annotations

from webfetch_service.services.cache import CachedFetch, MemoryCache


async def test_memory_cache_hit_and_expiry(monkeypatch) -> None:
    cache = MemoryCache(max_entries=2)
    value = CachedFetch("https://example.com/", 200, {}, "body", "http", None, "2026-01-01T00:00:00+00:00")
    await cache.set("key", value, 10)
    assert await cache.get("key") == value
    await cache.set("disabled", value, 0)
    assert await cache.get("disabled") is None


async def test_memory_cache_is_bounded() -> None:
    cache = MemoryCache(max_entries=1)
    value = CachedFetch("https://example.com/", 200, {}, "body", "http", None, "2026-01-01T00:00:00+00:00")
    await cache.set("first", value, 10)
    await cache.set("second", value, 10)
    assert await cache.get("first") is None
    assert await cache.get("second") is not None
