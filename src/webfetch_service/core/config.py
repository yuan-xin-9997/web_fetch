from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ServerSettings(BaseModel):
    host: str = "127.0.0.1"
    port: int = Field(default=33333, ge=1, le=65535)
    log_level: str = "INFO"
    sync_timeout_seconds: float = Field(default=30, gt=0, le=300)


class AuthSettings(BaseModel):
    bootstrap_api_key: SecretStr = SecretStr("change-me-before-production")
    bootstrap_client_name: str = "bootstrap"
    allow_default_key: bool = False

    @field_validator("bootstrap_api_key")
    @classmethod
    def validate_key(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value()) < 16:
            raise ValueError("bootstrap API key must contain at least 16 characters")
        return value


class FetchSettings(BaseModel):
    timeout_seconds: float = Field(default=20, gt=0, le=300)
    max_attempts: int = Field(default=3, ge=1, le=10)
    max_redirects: int = Field(default=10, ge=0, le=30)
    max_response_bytes: int = Field(default=10 * 1024 * 1024, ge=1024)
    default_cache_ttl: int = Field(default=3600, ge=0)
    default_domain_interval_seconds: float = Field(default=1.0, ge=0)
    default_domain_concurrency: int = Field(default=4, ge=1, le=100)
    auto_min_html_chars: int = Field(default=300, ge=0)
    retry_base_seconds: float = Field(default=0.25, ge=0, le=60)


class SecuritySettings(BaseModel):
    allow_private_networks: bool = False
    allowed_hosts: list[str] = Field(default_factory=list)
    allowed_cidrs: list[str] = Field(default_factory=list)
    blocked_hosts: list[str] = Field(default_factory=list)


class StorageSettings(BaseModel):
    artifact_root: Path = Path("./data/artifacts")
    save_artifacts_by_default: bool = True


class RedisSettings(BaseModel):
    url: SecretStr | None = None
    enabled: bool = False
    key_prefix: str = "webfetch:"


class DatabaseSettings(BaseModel):
    url: SecretStr = SecretStr("sqlite+aiosqlite:///./data/webfetch.db")
    enabled: bool = True
    create_schema_on_start: bool = False


class ProxySettings(BaseModel):
    http_url: SecretStr | None = None
    default_policy: str = "direct"

    @field_validator("default_policy")
    @classmethod
    def validate_policy(cls, value: str) -> str:
        if value not in {"direct", "proxy", "auto"}:
            raise ValueError("proxy policy must be direct, proxy, or auto")
        return value


class BrowserSettings(BaseModel):
    enabled: bool = False
    concurrency: int = Field(default=2, ge=1, le=20)
    navigation_timeout_seconds: float = Field(default=30, gt=0, le=300)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="WEBFETCH_",
        env_nested_delimiter="__",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: str = "development"
    server: ServerSettings = Field(default_factory=ServerSettings)
    auth: AuthSettings = Field(default_factory=AuthSettings)
    fetch: FetchSettings = Field(default_factory=FetchSettings)
    security: SecuritySettings = Field(default_factory=SecuritySettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)
    redis: RedisSettings = Field(default_factory=RedisSettings)
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    proxy: ProxySettings = Field(default_factory=ProxySettings)
    browser: BrowserSettings = Field(default_factory=BrowserSettings)

    def validate_production(self) -> None:
        key = self.auth.bootstrap_api_key.get_secret_value()
        if self.environment == "production" and key == "change-me-before-production":
            raise ValueError("default bootstrap API key is forbidden in production")


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.validate_production()
    return settings
