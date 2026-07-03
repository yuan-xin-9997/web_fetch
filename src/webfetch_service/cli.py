from __future__ import annotations

import uvicorn

from .core.config import get_settings


def api() -> None:
    settings = get_settings()
    uvicorn.run("webfetch_service.main:app", host=settings.server.host, port=settings.server.port, log_config=None)
