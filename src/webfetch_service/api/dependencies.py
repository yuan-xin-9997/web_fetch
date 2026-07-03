from __future__ import annotations

from dataclasses import dataclass

from fastapi import Header, Request

from webfetch_service.core.errors import authentication_failed
from webfetch_service.core.security import constant_time_key_matches


@dataclass(frozen=True, slots=True)
class Client:
    id: str
    scopes: frozenset[str]


async def authenticated_client(request: Request, authorization: str | None = Header(default=None)) -> Client:
    if not authorization or not authorization.startswith("Bearer "):
        raise authentication_failed()
    token = authorization.removeprefix("Bearer ").strip()
    if not constant_time_key_matches(token, request.app.state.api_key_digest):
        raise authentication_failed()
    return Client(request.app.state.settings.auth.bootstrap_client_name, frozenset({"fetch", "extract", "admin"}))
