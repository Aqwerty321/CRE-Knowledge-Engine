from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


SUPPORTED_SLACK_INGEST_POLICIES = {"evidence", "files_only", "listings_only", "disabled"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="CRE_", extra="ignore")

    app_name: str = "CRE Knowledge Engine"
    app_env: str = "dev"
    log_level: str = "INFO"
    host: str = "0.0.0.0"
    port: int = 8000

    database_url: str = "postgresql+asyncpg://cre:cre@localhost:5432/cre_knowledge_engine"
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "cre_chunks"
    vector_search_enabled: bool = False
    vector_index_on_import: bool = False
    embedding_url: str = "http://127.0.0.1:8001/v1/embeddings"
    embedding_model: str = "qwen3-embedding-0_6b-q8_0"
    embedding_dimension: int = 1024
    embedding_batch_size: int = 16
    embedding_request_timeout_seconds: float = 20.0
    rerank_url: str = "http://127.0.0.1:8002/v1/rerank"
    rerank_model: str = "qwen3-reranker-0.6b"
    rerank_request_timeout_seconds: float = 20.0
    retrieval_config_path: Path = Field(default_factory=lambda: Path("app/retrieval/retrieval_config.json"))
    ocr_enabled: bool = False
    ocr_backend_url: str = "http://127.0.0.1:5003"
    ocr_timeout_seconds: float = 1800.0
    ocr_poll_interval_seconds: float = 2.0
    sample_data_dir: Path = Field(default_factory=lambda: Path("sample-data"))
    configured_channel_ids: str = ""
    slack_ingest_channel_ids: str = ""
    slack_ingest_channel_policies_raw: str = ""
    slack_download_dir: Path = Field(default_factory=lambda: Path("downloads/slack-files"))
    slack_context_retention_days: int = 30
    slack_download_retention_days: int = 7

    slack_signing_secret: str | None = None
    slack_bot_token: str | None = None
    slack_app_token: str | None = None
    slack_worker_poll_interval_seconds: float = 2.0
    slack_worker_batch_limit: int = 10
    slack_storage_prune_interval_seconds: float = 3600.0
    toolhouse_api_key: str | None = None
    toolhouse_agent_id: str | None = "0c2c4555-5d96-47e4-8e05-f956de7a102e"
    toolhouse_mcp_bearer_token: str | None = None
    public_callback_url: str | None = Field(default=None, validation_alias="CLOUDFLARE_PUBLIC_CALLBACK_URL")

    @property
    def configured_channels(self) -> list[str]:
        return [item.strip() for item in self.configured_channel_ids.split(",") if item.strip()]

    @property
    def slack_ingest_channels(self) -> list[str]:
        configured = [item.strip() for item in self.slack_ingest_channel_ids.split(",") if item.strip()]
        return configured or self.configured_channels

    @property
    def slack_ingest_channel_policies(self) -> dict[str, str]:
        policies: dict[str, str] = {}
        for item in self.slack_ingest_channel_policies_raw.split(","):
            entry = item.strip()
            if not entry:
                continue
            channel_id, separator, policy = entry.partition("=")
            if not separator:
                raise ValueError(
                    "CRE_SLACK_INGEST_CHANNEL_POLICIES entries must use channel_id=policy format"
                )
            normalized_channel_id = channel_id.strip()
            normalized_policy = policy.strip().lower()
            if not normalized_channel_id:
                raise ValueError("CRE_SLACK_INGEST_CHANNEL_POLICIES cannot contain an empty channel id")
            if normalized_policy not in SUPPORTED_SLACK_INGEST_POLICIES:
                allowed = ", ".join(sorted(SUPPORTED_SLACK_INGEST_POLICIES))
                raise ValueError(
                    f"Unsupported Slack ingest policy '{normalized_policy}' for {normalized_channel_id}; allowed: {allowed}"
                )
            policies[normalized_channel_id] = normalized_policy
        return policies

    def slack_ingest_policy_for_channel(self, channel_id: str) -> str:
        return self.slack_ingest_channel_policies.get(channel_id, "evidence")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
