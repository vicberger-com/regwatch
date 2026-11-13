"""Application settings read from the environment (docs/contracts/env.example).

Every variable in the contract has a field here. Required variables have no default, so
``Settings()`` raises ``ValidationError`` at start-up when one is missing or empty.
"""

from __future__ import annotations

import ipaddress
import re
from functools import lru_cache
from typing import Annotated, Literal

from pydantic import AnyHttpUrl, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

_HEX64 = re.compile(r"^[0-9a-fA-F]{64}$")

IPNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network


class Settings(BaseSettings):
    """Typed view of the ``REGWATCH_*`` environment variables."""

    model_config = SettingsConfigDict(
        env_prefix="REGWATCH_",
        env_ignore_empty=True,  # an empty value counts as unset, so required ones fail fast
        extra="ignore",
        frozen=True,
    )

    # --- core (required) ---
    secret_key: SecretStr
    secret_key_previous: SecretStr | None = None
    database_url: SecretStr
    # Owner login for Alembic only; the API runs as a member of regwatch_app (BL-61).
    migration_database_url: SecretStr | None = None
    queue_url: SecretStr
    object_store_path: str = "/data/objectstore"
    base_url: AnyHttpUrl

    # --- core (optional) ---
    env: Literal["development", "production", "test"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    trusted_proxies: Annotated[tuple[IPNetwork, ...], NoDecode] = (
        ipaddress.IPv4Network("10.0.0.0/8"),
    )
    session_cookie_name: str = Field(default="rw_session", pattern=r"^[A-Za-z0-9_-]{1,64}$")
    object_store_s3_endpoint: AnyHttpUrl | None = None
    object_store_s3_bucket: str | None = None
    object_store_s3_access_key: SecretStr | None = None
    object_store_s3_secret_key: SecretStr | None = None

    # --- email ---
    smtp_host: str = "mailpit"
    smtp_port: int = Field(default=1025, ge=1, le=65535)
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    smtp_starttls: bool = False
    smtp_from: str = "regwatch@example.com"

    # --- sidecar services (internal fixed-URL client, ADR-0001) ---
    pdf_url: AnyHttpUrl = AnyHttpUrl("http://pdf:3000")
    search_url: AnyHttpUrl = AnyHttpUrl("http://search:8080")
    search_api_key: SecretStr | None = None
    search_api_url: AnyHttpUrl | None = None
    translate_url: AnyHttpUrl = AnyHttpUrl("http://translate:5000")
    translate_api_key: SecretStr | None = None
    translate_api_url: AnyHttpUrl | None = None
    model_url: AnyHttpUrl = AnyHttpUrl("http://ollama:11434")
    model_api_key: SecretStr | None = None
    model_api_url: AnyHttpUrl | None = None
    print_bridge_url: AnyHttpUrl = AnyHttpUrl("http://print-bridge:7000")

    # --- identity (M1b) ---
    oidc_issuer: AnyHttpUrl | None = None
    oidc_client_id: str | None = None
    oidc_client_secret: SecretStr | None = None

    # --- observability ---
    metrics_enabled: bool = True
    otel_exporter_otlp_endpoint: AnyHttpUrl | None = None

    @field_validator("secret_key", "secret_key_previous")
    @classmethod
    def _secret_is_64_hex(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None and not _HEX64.match(value.get_secret_value()):
            raise ValueError("must be 64 hexadecimal characters")
        return value

    @field_validator("database_url", "migration_database_url")
    @classmethod
    def _database_is_postgresql(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None and not value.get_secret_value().startswith(
            ("postgresql://", "postgresql+psycopg://")
        ):
            raise ValueError("must be a postgresql:// or postgresql+psycopg:// URL")
        return value

    @field_validator("queue_url")
    @classmethod
    def _queue_is_valkey(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().startswith(("valkey://", "redis://")):
            raise ValueError("must be a valkey:// or redis:// URL")
        return value

    @field_validator("trusted_proxies", mode="before")
    @classmethod
    def _split_cidrs(cls, value: object) -> object:
        if isinstance(value, str):
            return tuple(
                ipaddress.ip_network(part.strip(), strict=True)
                for part in value.split(",")
                if part.strip()
            )
        return value


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings, read once."""
    return Settings()
