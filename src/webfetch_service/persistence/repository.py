from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import selectinload

from webfetch_service.core.errors import WebFetchError
from webfetch_service.core.ids import new_id
from webfetch_service.schemas import JobCreateRequest

from .database import Database
from .models import Job, JobItem


class JobRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def create(self, client_id: str, request: JobCreateRequest) -> Job:
        job = Job(
            id=new_id("job"),
            client_id=client_id,
            state="queued",
            priority=request.priority,
            webhook_url=str(request.webhook_url) if request.webhook_url else None,
            item_count=len(request.requests),
        )
        job.items = [
            JobItem(
                id=new_id("item"),
                position=index,
                payload=item.model_dump(mode="json"),
                queue="http" if item.mode.value == "http" else "browser",
                state="queued",
            )
            for index, item in enumerate(request.requests)
        ]
        async with self.database.sessions() as session:
            session.add(job)
            await session.commit()
            await session.refresh(job, attribute_names=["items"])
        return job

    async def get(self, job_id: str, client_id: str | None = None) -> Job:
        statement = select(Job).where(Job.id == job_id).options(selectinload(Job.items))
        if client_id:
            statement = statement.where(Job.client_id == client_id)
        async with self.database.sessions() as session:
            job = (await session.execute(statement)).scalar_one_or_none()
        if job is None:
            raise WebFetchError("JOB_NOT_FOUND", "任务不存在", 404)
        return job

    async def cancel(self, job_id: str, client_id: str) -> Job:
        async with self.database.sessions() as session:
            statement = select(Job).where(Job.id == job_id, Job.client_id == client_id).options(selectinload(Job.items))
            job = (await session.execute(statement)).scalar_one_or_none()
            if job is None:
                raise WebFetchError("JOB_NOT_FOUND", "任务不存在", 404)
            for item in job.items:
                if item.state == "queued":
                    item.state = "cancelled"
            if all(item.state in {"succeeded", "failed", "cancelled"} for item in job.items):
                job.state = "cancelled"
            await session.commit()
            return job

    async def claim(self, worker_id: str, queue: str = "http", lease_seconds: int = 120) -> JobItem | None:
        now = datetime.now(UTC)
        async with self.database.sessions() as session:
            async with session.begin():
                statement = (
                    select(JobItem)
                    .where(
                        JobItem.queue == queue,
                        JobItem.next_run_at <= now,
                        or_(JobItem.state == "queued", (JobItem.state == "running") & (JobItem.leased_until < now)),
                    )
                    .order_by(JobItem.next_run_at, JobItem.created_at)
                    .limit(1)
                    .with_for_update(skip_locked=True)
                )
                item = (await session.execute(statement)).scalar_one_or_none()
                if item is None:
                    return None
                item.state = "running"
                item.worker_id = worker_id
                item.leased_until = now + timedelta(seconds=lease_seconds)
                item.attempts += 1
                job = await session.get(Job, item.job_id)
                if job:
                    job.state = "running"
            await session.refresh(item)
            return item

    async def complete(self, item_id: str, request_id: str, result: dict) -> None:
        async with self.database.sessions() as session:
            item = await session.get(JobItem, item_id)
            if not item:
                return
            item.state = "succeeded"
            item.request_id = request_id
            item.result = result
            item.leased_until = None
            await self._refresh_job(session, item.job_id)
            await session.commit()

    async def fail(self, item_id: str, error: WebFetchError, max_attempts: int = 3) -> None:
        async with self.database.sessions() as session:
            item = await session.get(JobItem, item_id)
            if not item:
                return
            item.error_code = error.code
            item.error_message = error.message
            item.leased_until = None
            if error.retryable and item.attempts < max_attempts:
                item.state = "queued"
                delay = error.retry_after_seconds or 2**item.attempts
                item.next_run_at = datetime.now(UTC) + timedelta(seconds=delay)
            else:
                item.state = "failed"
            await self._refresh_job(session, item.job_id)
            await session.commit()

    async def _refresh_job(self, session, job_id: str) -> None:
        job = (await session.execute(select(Job).where(Job.id == job_id).options(selectinload(Job.items)))).scalar_one()
        states = [item.state for item in job.items]
        job.succeeded_count = states.count("succeeded")
        job.failed_count = states.count("failed")
        if all(state in {"succeeded", "failed", "cancelled"} for state in states):
            job.state = "failed" if job.failed_count else "succeeded"
        elif "running" in states:
            job.state = "running"
