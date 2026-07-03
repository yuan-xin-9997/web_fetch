from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from contextlib import asynccontextmanager


class DomainRateLimiter:
    def __init__(self, interval_seconds: float, concurrency: int) -> None:
        self.interval_seconds = interval_seconds
        self.concurrency = concurrency
        self._next_slot: dict[str, float] = defaultdict(float)
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._semaphores: dict[str, asyncio.Semaphore] = defaultdict(lambda: asyncio.Semaphore(self.concurrency))

    @asynccontextmanager
    async def slot(self, domain: str):
        semaphore = self._semaphores[domain]
        await semaphore.acquire()
        try:
            async with self._locks[domain]:
                now = time.monotonic()
                wait = max(0.0, self._next_slot[domain] - now)
                self._next_slot[domain] = max(now, self._next_slot[domain]) + self.interval_seconds
            if wait:
                await asyncio.sleep(wait)
            yield
        finally:
            semaphore.release()
