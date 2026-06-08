import json
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # LLM — OpenRouter (OpenAI-compatible) or direct Anthropic
    anthropic_api_key: str = ""          # accepts OpenRouter key (sk-or-v1-...)
    generation_model: str = "anthropic/claude-sonnet-4-6"
    llm_base_url: str = "https://openrouter.ai/api/v1"

    # Google
    google_service_account_json: str = ""  # base64-encoded

    # Database — app uses asyncpg; Alembic strips +asyncpg at migration time
    database_url: str = "postgresql+asyncpg://rmg:rmg@localhost:5432/rmgdb"

    # Redis
    redis_url: str = "redis://localhost:6379/0"
    redis_pool_max_connections: int = 20
    redis_image_pool_max_connections: int = 10
    vision_cache_ttl: int = 604800  # 7 days in seconds

    # Circuit breaker
    max_retries: int = 3

    # Pattern memory promotion gate
    pattern_confidence_threshold: float = 0.75
    min_examples_constant: int = 20

    # Shadow A/B
    shadow_promotion_margin: float = 0.05
    shadow_min_slides: int = 50
    shadow_config_json: str = "{}"

    # Embeddings
    embedding_model: str = "text-embedding-3-small"
    openai_api_key: str = ""

    # CORS — comma-separated origins, e.g. https://rmg-frontend.onrender.com
    cors_origins: str = "*"

    # Server
    app_host: str = "0.0.0.0"
    app_port: int = 8000

    @property
    def cors_origins_list(self) -> list[str]:
        if self.cors_origins == "*":
            return ["*"]
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def shadow_config(self) -> dict:
        return json.loads(self.shadow_config_json)

    @property
    def async_database_url(self) -> str:
        """Ensure the URL uses the asyncpg driver (Render provides plain postgresql://)."""
        url = self.database_url
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql+asyncpg://", 1)
        elif url.startswith("postgresql://") and "+asyncpg" not in url:
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        return url

    @property
    def sync_database_url(self) -> str:
        """Synchronous URL for Alembic (psycopg2, not asyncpg)."""
        return self.async_database_url.replace("postgresql+asyncpg://", "postgresql://")

    @property
    def pattern_promotion_threshold(self) -> int:
        """Minimum example_count before a pattern candidate is promoted."""
        import math
        return math.ceil(self.pattern_confidence_threshold * self.min_examples_constant)


settings = Settings()
