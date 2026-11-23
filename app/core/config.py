from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "AI-Powered Vault Document System"
    app_version: str = "1.0.0"
    environment: str = Field(default="local", alias="ENVIRONMENT")

    # Database: PostgreSQL in production (e.g. postgresql+psycopg://...), SQLite locally by default
    database_url: str = Field(default="sqlite:///./data/vault.db", alias="DATABASE_URL")

    # Local filesystem storage
    upload_dir: str = Field(default="data/uploads", alias="UPLOAD_DIR")
    max_upload_size_mb: int = Field(default=25, alias="MAX_UPLOAD_SIZE_MB")

    # Chunking parameters
    chunk_size_chars: int = Field(default=900, alias="CHUNK_SIZE_CHARS")
    chunk_overlap_chars: int = Field(default=150, alias="CHUNK_OVERLAP_CHARS")
    top_k_chunks: int = Field(default=5, alias="TOP_K_CHUNKS")

    # AI Provider configuration (OpenRouter, OpenAI, or local deterministic fallback)
    openrouter_api_key: str | None = Field(default=None, alias="OPENROUTER_API_KEY")
    openrouter_base_url: str = Field(
        default="https://openrouter.ai/api/v1", alias="OPENROUTER_BASE_URL"
    )
    openrouter_chat_model: str = Field(
        default="openai/gpt-4o", alias="OPENROUTER_CHAT_MODEL"
    )
    openrouter_embedding_model: str = Field(
        default="openai/text-embedding-3-small", alias="OPENROUTER_EMBEDDING_MODEL"
    )
    openrouter_site_url: str = Field(
        default="http://127.0.0.1:8000", alias="OPENROUTER_SITE_URL"
    )
    openrouter_site_name: str = Field(
        default="Vault AI Document System", alias="OPENROUTER_SITE_NAME"
    )

    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    openai_chat_model: str = Field(default="gpt-4o-mini", alias="OPENAI_CHAT_MODEL")
    openai_embedding_model: str = Field(
        default="text-embedding-3-small", alias="OPENAI_EMBEDDING_MODEL"
    )

    # Task queue / Caching (optional Redis + Celery for distributed scale)
    redis_url: str | None = Field(default=None, alias="REDIS_URL")
    use_celery: bool = Field(default=False, alias="USE_CELERY")
    cache_db_path: str = Field(default="data/cache.db", alias="CACHE_DB_PATH")
    cache_ttl_seconds: int = Field(default=3600, alias="CACHE_TTL_SECONDS")
    rate_limit_per_minute: int = Field(default=120, alias="RATE_LIMIT_PER_MINUTE")

    # Local quota management
    max_documents: int = Field(default=500, alias="MAX_DOCUMENTS")
    max_total_storage_mb: int = Field(default=500, alias="MAX_TOTAL_STORAGE_MB")
    max_daily_tokens: int = Field(default=1_000_000, alias="MAX_DAILY_TOKENS")
    max_daily_cost_usd: float = Field(default=10.0, alias="MAX_DAILY_COST_USD")
    max_batch_upload_files: int = Field(default=20, alias="MAX_BATCH_UPLOAD_FILES")

    @property
    def has_llm(self) -> bool:
        return bool(self.openrouter_api_key or self.openai_api_key)

    @property
    def ai_mode(self) -> str:
        if self.openrouter_api_key:
            return "openrouter"
        if self.openai_api_key:
            return "openai"
        return "local"

    @property
    def active_chat_model(self) -> str:
        if self.openrouter_api_key:
            return self.openrouter_chat_model
        if self.openai_api_key:
            return self.openai_chat_model
        return "local-rag-v1"

    @property
    def active_embedding_model(self) -> str:
        if self.openrouter_api_key:
            return self.openrouter_embedding_model
        if self.openai_api_key:
            return self.openai_embedding_model
        return "local-hash-256"

    def ensure_dirs(self) -> None:
        Path(self.upload_dir).mkdir(parents=True, exist_ok=True)
        if self.cache_db_path and self.cache_db_path != ":memory:":
            Path(self.cache_db_path).parent.mkdir(parents=True, exist_ok=True)
        if self.database_url.startswith("sqlite:///"):
            sqlite_path = self.database_url.replace("sqlite:///", "", 1)
            if sqlite_path and sqlite_path != ":memory:":
                Path(sqlite_path).parent.mkdir(parents=True, exist_ok=True)


def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_dirs()
    return settings
