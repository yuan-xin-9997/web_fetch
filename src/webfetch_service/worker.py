from __future__ import annotations

import asyncio
import logging
import os
import signal
import socket

from webfetch_service.core.errors import WebFetchError
from webfetch_service.main import create_app
from webfetch_service.schemas import FetchRequest

logger = logging.getLogger(__name__)


async def run_worker() -> None:
    app = create_app()
    if app.state.database is None or app.state.jobs is None:
        raise RuntimeError("database must be enabled for worker")
    if app.state.settings.database.create_schema_on_start:
        await app.state.database.create_schema()
    await app.state.artifacts.initialize()
    worker_id = os.getenv("WEBFETCH_WORKER_ID", f"{socket.gethostname()}-{os.getpid()}")
    queue = os.getenv("WEBFETCH_WORKER_QUEUE", "http")
    poll_seconds = float(os.getenv("WEBFETCH_WORKER_POLL_SECONDS", "1"))
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            pass
    logger.info("worker started", extra={"worker_id": worker_id})
    try:
        while not stop.is_set():
            item = await app.state.jobs.claim(worker_id, queue=queue)
            if item is None:
                try:
                    await asyncio.wait_for(stop.wait(), timeout=poll_seconds)
                except TimeoutError:
                    pass
                continue
            try:
                payload = FetchRequest.model_validate(item.payload)
                result = await app.state.fetch_service.fetch(payload)
                await app.state.jobs.complete(item.id, result.request_id, result.model_dump(mode="json"))
            except WebFetchError as exc:
                await app.state.jobs.fail(item.id, exc)
            except Exception:
                logger.exception("unhandled worker error", extra={"job_id": item.job_id})
                await app.state.jobs.fail(item.id, WebFetchError("INTERNAL_ERROR", "内部执行错误", 500, True))
    finally:
        await app.state.http_fetcher.close()
        await app.state.browser_fetcher.close()
        await app.state.cache.close()
        await app.state.database.close()


def main() -> None:
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
