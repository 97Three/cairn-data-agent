from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .resources import built_in_resources_root


class Settings(BaseSettings):
    """Runtime configuration with safe, offline-friendly defaults."""

    model_config = SettingsConfigDict(
        env_prefix="CAIRN_",
        extra="ignore",
    )

    model_mode: Literal["fake", "openai-compatible"] = "fake"
    model_base_url: str = "http://127.0.0.1:8001/v1"
    model_id: str = "local-model"
    model_api_key: str = ""
    database_url: str = "sqlite:///./runtime-data/cairn.db"
    storage_root: Path = Path("runtime-data")
    scenarios_root: Path = Field(default_factory=lambda: built_in_resources_root() / "scenarios")
    skills_root: Path = Field(default_factory=lambda: built_in_resources_root() / "skills")
    max_upload_bytes: int = 25 * 1024 * 1024
    preview_rows: int = 50
    cors_origins: list[str] = ["http://127.0.0.1:5173", "http://localhost:5173"]

    @field_validator("cors_origins", mode="before")
    @classmethod
    def split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
