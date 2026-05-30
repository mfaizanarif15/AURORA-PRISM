from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


BACKEND_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = BACKEND_ROOT.parent


class Settings(BaseSettings):
    app_name: str = "AURORA PRISM"
    environment: str = "local"
    api_v1_prefix: str = "/api"
    database_url: str = Field(
        default="postgresql+asyncpg://aurora:aurora@postgres:5432/aurora_prism"
    )
    frontend_origin: str = "http://localhost:6173"
    storage_root: Path = Path("./storage")
    ai_provider: str = Field(default="azure_openai", validation_alias=AliasChoices("AI_PROVIDER", "OPENAI_PROVIDER"))
    openai_api_key: str | None = None
    openai_model: str = "gpt-4.1-mini"
    azure_openai_endpoint: str | None = None
    azure_openai_api_key: str | None = None
    azure_openai_api_version: str | None = "2025-03-01-preview"
    azure_openai_chat_deployment: str | None = None
    azure_openai_embedding_deployment: str | None = "text-embedding-3-large"
    azure_api_base: str | None = None
    azure_api_key: str | None = None
    azure_api_version: str | None = None
    azure_deployment: str | None = None
    analysis_mode: bool = True
    langfuse_enabled: bool = False
    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None
    langfuse_base_url: str = "https://cloud.langfuse.com"
    langfuse_environment: str | None = None
    langfuse_release: str | None = "aurora-prism-mvp"
    langfuse_capture_llm_io: bool = True
    langfuse_max_llm_io_chars: int = 250000
    log_level: str = "INFO"
    log_to_file: bool = True
    log_file: Path | None = None
    max_upload_mb: int = 2048
    auth_enabled: bool = True
    auth_username: str = "admin"
    auth_password: str = "aurora-admin"
    auth_display_name: str = "AURORA Operator"
    auth_role: str = "Content Operations"
    auth_session_secret: str = "aurora-prism-local-session-secret"
    auth_token_ttl_minutes: int = 480

    model_config = SettingsConfigDict(
        env_file=(PROJECT_ROOT / ".env", BACKEND_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    @field_validator("ai_provider")
    @classmethod
    def normalize_ai_provider(cls, value: str) -> str:
        normalized = value.strip().lower().replace("-", "_")
        if normalized in {"azure", "azure_openai"}:
            return "azure_openai"
        if normalized == "openai":
            return "openai"
        return "azure_openai"

    @field_validator("analysis_mode", mode="before")
    @classmethod
    def normalize_analysis_mode(cls, value: object) -> bool:
        if isinstance(value, bool):
            return value
        if value is None:
            return True
        normalized = str(value).strip().lower().replace("-", "_")
        if normalized in {"true", "1", "yes", "y", "on", "mock", "mock_mode"}:
            return True
        if normalized in {"false", "0", "no", "n", "off", "live", "openai", "azure_openai"}:
            return False
        return True

    @field_validator("storage_root")
    @classmethod
    def resolve_storage_root(cls, value: Path) -> Path:
        if value.is_absolute():
            return value
        return PROJECT_ROOT / value

    @field_validator("log_level")
    @classmethod
    def normalize_log_level(cls, value: str) -> str:
        normalized = value.strip().upper()
        if normalized in {"TRACE", "DEBUG", "INFO", "SUCCESS", "WARNING", "ERROR", "CRITICAL"}:
            return normalized
        return "INFO"

    @field_validator("log_file", mode="before")
    @classmethod
    def normalize_log_file(cls, value: object) -> object:
        if value is None or str(value).strip() == "":
            return None
        return value

    @field_validator("auth_session_secret")
    @classmethod
    def normalize_auth_session_secret(cls, value: str) -> str:
        normalized = value.strip()
        return normalized or "aurora-prism-local-session-secret"

    @field_validator("auth_token_ttl_minutes")
    @classmethod
    def normalize_auth_token_ttl_minutes(cls, value: int) -> int:
        return max(5, value)

    @field_validator("langfuse_max_llm_io_chars")
    @classmethod
    def normalize_langfuse_max_llm_io_chars(cls, value: int) -> int:
        return max(1000, value)

    @property
    def uploads_dir(self) -> Path:
        return self.storage_root / "uploads"

    @property
    def exports_dir(self) -> Path:
        return self.storage_root / "exports"

    @property
    def ai_provider_options(self) -> list[str]:
        return ["azure_openai", "openai"]

    @property
    def resolved_azure_openai_endpoint(self) -> str | None:
        return self.azure_openai_endpoint or self.azure_api_base

    @property
    def resolved_azure_openai_api_key(self) -> str | None:
        return self.azure_openai_api_key or self.azure_api_key

    @property
    def resolved_azure_openai_api_version(self) -> str:
        return self.azure_openai_api_version or self.azure_api_version or "2025-03-01-preview"

    @property
    def resolved_azure_openai_chat_deployment(self) -> str | None:
        return self.azure_openai_chat_deployment or self.azure_deployment

    @property
    def langfuse_configured(self) -> bool:
        return bool(self.langfuse_public_key and self.langfuse_secret_key and self.langfuse_base_url)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.uploads_dir.mkdir(parents=True, exist_ok=True)
    settings.exports_dir.mkdir(parents=True, exist_ok=True)
    return settings
