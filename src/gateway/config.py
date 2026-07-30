"""Environment-backed application settings."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration with safe local defaults."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "development"
    database_url: str = "postgresql+asyncpg://gateway:gateway@localhost:5432/gateway"
    redis_url: str = "redis://localhost:6379/0"
    api_keys: Annotated[tuple[str, ...], NoDecode] = ("local-development-key",)
    log_level: str = "INFO"
    rate_limit_requests: int = 100
    rate_limit_window_seconds: int = 60
    job_max_attempts: int = 3
    job_lease_seconds: int = 300
    default_route: str = "deterministic"
    routes_config: Path = Path("config/routes.yaml")
    dispatcher_batch_size: int = 100
    dispatcher_poll_seconds: float = 0.25
    taskiq_stream: str = "model-gateway-jobs"
    taskiq_consumer_group: str = "taskiq"

    @field_validator("api_keys", mode="before")
    @classmethod
    def split_keys(cls, value: object) -> object:
        if isinstance(value, str):
            return tuple(item.strip() for item in value.split(",") if item.strip())
        return value


@lru_cache
def get_settings() -> Settings:
    """Return one immutable settings instance per process."""
    return Settings()
