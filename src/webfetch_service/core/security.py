from __future__ import annotations

import asyncio
import hashlib
import hmac
import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

from .config import SecuritySettings
from .errors import WebFetchError


def api_key_digest(api_key: str) -> str:
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


def constant_time_key_matches(provided: str, expected_digest: str) -> bool:
    return hmac.compare_digest(api_key_digest(provided), expected_digest)


@dataclass(frozen=True, slots=True)
class GuardedUrl:
    normalized: str
    host: str
    port: int
    addresses: tuple[str, ...]


class UrlGuard:
    def __init__(self, settings: SecuritySettings) -> None:
        self.settings = settings
        self._allowed_networks = tuple(ipaddress.ip_network(item) for item in settings.allowed_cidrs)
        self._allowed_hosts = {host.lower().rstrip(".") for host in settings.allowed_hosts}
        self._blocked_hosts = {host.lower().rstrip(".") for host in settings.blocked_hosts}

    async def validate(self, url: str) -> GuardedUrl:
        parsed = urlsplit(url)
        if parsed.scheme.lower() not in {"http", "https"}:
            raise WebFetchError("INVALID_REQUEST", "只允许http和https URL", 422)
        if not parsed.hostname or parsed.username or parsed.password:
            raise WebFetchError("INVALID_REQUEST", "URL主机无效或包含用户信息", 422)

        host = parsed.hostname.lower().rstrip(".")
        if host in self._blocked_hosts:
            raise WebFetchError("DOMAIN_NOT_ALLOWED", "目标主机不允许访问", 403)
        port = parsed.port or (443 if parsed.scheme.lower() == "https" else 80)
        addresses = await self._resolve(host, port)
        if not addresses:
            raise WebFetchError("DNS_FAILED", "目标主机无法解析", 502, True)
        for address in addresses:
            if not self._address_allowed(host, ipaddress.ip_address(address)):
                raise WebFetchError("DOMAIN_NOT_ALLOWED", "目标地址不允许访问", 403)

        default_port = 443 if parsed.scheme.lower() == "https" else 80
        netloc = host if port == default_port else f"{host}:{port}"
        normalized = urlunsplit((parsed.scheme.lower(), netloc, parsed.path or "/", parsed.query, ""))
        return GuardedUrl(normalized, host, port, tuple(sorted(addresses)))

    async def _resolve(self, host: str, port: int) -> set[str]:
        try:
            literal = ipaddress.ip_address(host)
            return {str(literal)}
        except ValueError:
            pass
        loop = asyncio.get_running_loop()
        try:
            infos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        except socket.gaierror:
            return set()
        return {item[4][0] for item in infos}

    def _address_allowed(self, host: str, address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
        if host in self._allowed_hosts or any(address in network for network in self._allowed_networks):
            return True
        if self.settings.allow_private_networks:
            return not (address.is_loopback or address.is_link_local or address.is_multicast or address.is_unspecified)
        return not (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_multicast
            or address.is_unspecified
            or address.is_reserved
        )
