from __future__ import annotations

from webfetch_service.core.errors import WebFetchError
from webfetch_service.persistence import Database, JobRepository
from webfetch_service.schemas import JobCreateRequest


async def test_job_claim_complete_fail_and_cancel() -> None:
    database = Database("sqlite+aiosqlite:///:memory:")
    await database.create_schema()
    repository = JobRepository(database)
    try:
        request = JobCreateRequest(
            requests=[
                {"url": "https://example.com/1", "mode": "http"},
                {"url": "https://example.com/2", "mode": "http"},
            ]
        )
        job = await repository.create("client", request)
        first = await repository.claim("worker")
        assert first is not None
        await repository.complete(first.id, "req_done", {"success": True})
        second = await repository.claim("worker")
        assert second is not None
        await repository.fail(
            second.id,
            WebFetchError("UPSTREAM_BLOCKED", "blocked", 502, retryable=False),
        )
        finished = await repository.get(job.id, "client")
        assert finished.state == "failed"
        assert finished.succeeded_count == 1
        assert finished.failed_count == 1

        queued = await repository.create(
            "client",
            JobCreateRequest(requests=[{"url": "https://example.com/3", "mode": "http"}]),
        )
        cancelled = await repository.cancel(queued.id, "client")
        assert cancelled.state == "cancelled"
        assert cancelled.items[0].state == "cancelled"
    finally:
        await database.close()


async def test_retryable_job_is_requeued() -> None:
    database = Database("sqlite+aiosqlite:///:memory:")
    await database.create_schema()
    repository = JobRepository(database)
    try:
        job = await repository.create(
            "client",
            JobCreateRequest(requests=[{"url": "https://example.com/", "mode": "http"}]),
        )
        item = await repository.claim("worker")
        assert item is not None
        await repository.fail(
            item.id,
            WebFetchError("READ_TIMEOUT", "timeout", 504, retryable=True, retry_after_seconds=0),
        )
        requeued = await repository.get(job.id, "client")
        assert requeued.items[0].state == "queued"
    finally:
        await database.close()
