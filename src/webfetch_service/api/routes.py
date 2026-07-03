from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from webfetch_service.core.errors import WebFetchError
from webfetch_service.schemas import (
    ExtractRequest,
    ExtractResponse,
    FetchRequest,
    FetchResponse,
    JobCreateRequest,
    JobCreateResponse,
    JobItemResponse,
    JobResponse,
)

from .dependencies import Client, authenticated_client

router = APIRouter()


@router.get("/health/live")
async def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready")
async def ready(request: Request) -> JSONResponse:
    checks = {}
    try:
        checks["cache"] = await request.app.state.cache.ping()
    except Exception:
        checks["cache"] = False
    try:
        checks["artifact_store"] = await request.app.state.artifacts.is_ready()
    except Exception:
        checks["artifact_store"] = False
    if request.app.state.database is not None:
        try:
            checks["database"] = await request.app.state.database.ping()
        except Exception:
            checks["database"] = False
    ok = all(checks.values())
    return JSONResponse({"status": "ok" if ok else "not_ready", "checks": checks}, status_code=200 if ok else 503)


@router.get("/metrics")
async def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@router.post("/v1/fetch", response_model=FetchResponse)
async def fetch(
    payload: FetchRequest, request: Request, client: Client = Depends(authenticated_client)
) -> FetchResponse:
    del client
    return await request.app.state.fetch_service.fetch(payload, request.state.request_id)


@router.post("/v1/jobs", response_model=JobCreateResponse, status_code=202)
async def create_job(
    payload: JobCreateRequest, request: Request, client: Client = Depends(authenticated_client)
) -> JobCreateResponse:
    repository = request.app.state.jobs
    if repository is None:
        raise WebFetchError("QUEUE_UNAVAILABLE", "任务存储未启用", 503, True)
    job = await repository.create(client.id, payload)
    return JobCreateResponse(job_id=job.id, state=job.state, item_count=job.item_count)


@router.get("/v1/jobs/{job_id}", response_model=JobResponse)
async def get_job(job_id: str, request: Request, client: Client = Depends(authenticated_client)) -> JobResponse:
    repository = request.app.state.jobs
    if repository is None:
        raise WebFetchError("QUEUE_UNAVAILABLE", "任务存储未启用", 503, True)
    job = await repository.get(job_id, client.id)
    return _job_response(job)


@router.post("/v1/jobs/{job_id}/cancel", response_model=JobResponse)
async def cancel_job(job_id: str, request: Request, client: Client = Depends(authenticated_client)) -> JobResponse:
    repository = request.app.state.jobs
    if repository is None:
        raise WebFetchError("QUEUE_UNAVAILABLE", "任务存储未启用", 503, True)
    job = await repository.cancel(job_id, client.id)
    return _job_response(job)


@router.post("/v1/extract", response_model=ExtractResponse)
async def extract(
    payload: ExtractRequest, request: Request, client: Client = Depends(authenticated_client)
) -> ExtractResponse:
    del client
    request_id = request.state.request_id
    if bool(payload.url) == bool(payload.artifact_id):
        raise WebFetchError("INVALID_REQUEST", "url和artifact_id必须且只能提供一个", 422)
    if payload.artifact_id:
        artifact, body = await request.app.state.artifacts.load(payload.artifact_id)
        artifact_id = artifact.id
        base_url = ""
    else:
        options = payload.fetch_options or FetchRequest(url=payload.url)
        options.url = payload.url
        options.save_artifact = True
        fetched = await request.app.state.fetch_service.fetch(options, request_id)
        if not fetched.artifact_id:
            raise WebFetchError("STORAGE_UNAVAILABLE", "抓取结果未保存", 503)
        artifact, body = await request.app.state.artifacts.load(fetched.artifact_id)
        artifact_id = artifact.id
        base_url = fetched.final_url
    adapter = request.app.state.adapters.get(payload.adapter, payload.adapter_version)
    data = await adapter.extract(body, base_url)
    return ExtractResponse(
        request_id=request_id, adapter=adapter.name, adapter_version=adapter.version, artifact_id=artifact_id, data=data
    )


@router.get("/v1/artifacts/{artifact_id}")
async def artifact(artifact_id: str, request: Request, client: Client = Depends(authenticated_client)) -> Response:
    del client
    item, body = await request.app.state.artifacts.load(artifact_id)
    return Response(body, media_type=item.content_type, headers={"ETag": item.sha256, "X-Artifact-ID": item.id})


def _job_response(job) -> JobResponse:
    return JobResponse(
        job_id=job.id,
        state=job.state,
        item_count=job.item_count,
        succeeded_count=job.succeeded_count,
        failed_count=job.failed_count,
        created_at=job.created_at,
        items=[
            JobItemResponse(
                id=item.id,
                position=item.position,
                state=item.state,
                request_id=item.request_id,
                error_code=item.error_code,
            )
            for item in job.items
        ],
    )
