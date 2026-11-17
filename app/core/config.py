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

    # AI Provider configuration (uses OpenAI when key is set, local deterministic engine otherwise)
    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    openai_chat_model: str = Field(default="gpt-4o-mini", alias="OPENAI_CHAT_MODEL")
    openai_embedding_model: str = Field(
        default="text-embedding-3-small", alias="OPENAI_EMBEDDING_MODEL"
    )

    # Task queue / Caching (optional Redis + Celery for distributed scale)
    redis_url: str | None = Field(default=None, alias="REDIS_URL")
    use_celery: bool = Field(default=False, alias="USE_CELERY")
    rate_limit_per_minute: int = Field(default=120, alias="RATE_LIMIT_PER_MINUTE")

    @property
    def ai_mode(self) -> str:
        return "openai" if self.openai_api_key else "local"

    def ensure_dirs(self) -> None:
        Path(self.upload_dir).mkdir(parents=True, exist_ok=True)
        if self.database_url.startswith("sqlite:///"):
            sqlite_path = self.database_url.replace("sqlite:///", "", 1)
            if sqlite_path and sqlite_path != ":memory:":
                Path(sqlite_path).parent.mkdir(parents=True, exist_ok=True)


def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_dirs()
    return settings
