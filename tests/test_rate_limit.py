from __future__ import annotations

import asyncio
import time

from webfetch_service.services.rate_limit import DomainRateLimiter


async def test_domain_rate_interval() -> None:
    limiter = DomainRateLimiter(0.03, 2)
    starts: list[float] = []

    async def work() -> None:
        async with limiter.slot("example.com"):
            starts.append(time.monotonic())

    await asyncio.gather(work(), work())
    assert starts[1] - starts[0] >= 0.025
