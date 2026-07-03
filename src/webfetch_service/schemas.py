from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, HttpUrl


class FetchMode(StrEnum):
    AUTO = "auto"
    HTTP = "http"
    BROWSER = "browser"


class ProxyPolicy(StrEnum):
    AUTO = "auto"
    DIRECT = "direct"
    PROXY = "proxy"


class FetchRequest(BaseModel):
    url: HttpUrl
    mode: FetchMode = FetchMode.AUTO
    profile: str = Field(default="anonymous", min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9_.-]+$")
    proxy_policy: ProxyPolicy = ProxyPolicy.AUTO
    headers: dict[str, str] = Field(default_factory=dict)
    cache_ttl: int | None = Field(default=None, ge=0, le=2_592_000)
    force_refresh: bool = False
    save_artifact: bool | None = None
    timeout_seconds: float | None = Field(default=None, gt=0, le=300)
    required_selector: str | None = Field(default=None, max_length=500)


class AttemptInfo(BaseModel):
    sequence: int
    strategy: str
    status_code: int | None = None
    error_code: str | None = None
    elapsed_ms: int
    upgrade_reason: str | None = None


class FetchResponse(BaseModel):
    request_id: str
    success: bool
    requested_url: str
    final_url: str
    status_code: int
    strategy: str
    from_cache: bool = False
    stale: bool = False
    elapsed_ms: int
    content_type: str | None = None
    body: str | None = None
    artifact_id: str | None = None
    fetched_at: datetime
    attempts: list[AttemptInfo] = Field(default_factory=list)


class ErrorDetail(BaseModel):
    code: str
    message: str
    retryable: bool
    retry_after_seconds: float | None = None


class ErrorResponse(BaseModel):
    request_id: str
    success: bool = False
    error: ErrorDetail


class JobCreateRequest(BaseModel):
    requests: list[FetchRequest] = Field(min_length=1, max_length=1000)
    priority: str = Field(default="normal", pattern=r"^(low|normal|high)$")
    webhook_url: HttpUrl | None = None


class JobCreateResponse(BaseModel):
    job_id: str
    state: str
    item_count: int


class JobItemResponse(BaseModel):
    id: str
    position: int
    state: str
    request_id: str | None = None
    error_code: str | None = None


class JobResponse(BaseModel):
    job_id: str
    state: str
    item_count: int
    succeeded_count: int
    failed_count: int
    created_at: datetime
    items: list[JobItemResponse]


class ExtractRequest(BaseModel):
    url: HttpUrl | None = None
    artifact_id: str | None = None
    adapter: str = "generic.article"
    adapter_version: str = "latest"
    fetch_options: FetchRequest | None = None


class ExtractResponse(BaseModel):
    request_id: str
    adapter: str
    adapter_version: str
    artifact_id: str
    data: dict[str, Any]
