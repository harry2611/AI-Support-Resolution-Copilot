from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "AI Support Resolution Copilot API"
    environment: str = "development"
    api_prefix: str = "/api"

    database_url: str = "postgresql+psycopg://copilot:copilot@db:5432/copilot"
    openai_api_key: str | None = None
    chat_model: str = "gpt-4.1-mini"
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = 1536

    chunk_size: int = 900
    chunk_overlap: int = 150
    upload_max_file_mb: int = 10

    web_fallback_enabled: bool = True
    web_fallback_confidence_threshold: float = 0.35
    web_fallback_max_references: int = 5
    minimum_grounded_confidence: float = 0.32
    minimum_ticket_grounded_confidence: float = 0.28

    sync_scheduler_enabled: bool = True
    sync_interval_minutes: int = 60
    sync_on_startup: bool = False

    confluence_enabled: bool = False
    confluence_base_url: str | None = None
    confluence_email: str | None = None
    confluence_api_token: str | None = None
    confluence_space_keys: str = ""
    confluence_page_limit: int = 25

    notion_enabled: bool = False
    notion_api_token: str | None = None
    notion_database_ids: str = ""
    notion_page_limit: int = 25

    connector_request_timeout_seconds: int = 20

    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])

    def confluence_space_key_list(self) -> list[str]:
        return [value.strip() for value in self.confluence_space_keys.split(",") if value.strip()]

    def notion_database_id_list(self) -> list[str]:
        return [value.strip() for value in self.notion_database_ids.split(",") if value.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
