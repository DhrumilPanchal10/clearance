from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central configuration. Never hardcode model names or secrets elsewhere."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Database (Postgres + pgvector). FHIR resources stored as JSONB here.
    database_url: str = Field(
        default="postgresql+psycopg://clearance:clearance@localhost:5432/clearance"
    )

    # Redis
    redis_url: str = Field(default="redis://localhost:6379/0")

    # LLM model tiers (never hardcode — always read from config)
    model_small: str = Field(default="gemini/gemini-3.1-flash-lite")
    model_strong: str = Field(default="gemini/gemini-3.8-flash")
    model_judge: str = Field(default="gemini/gemini-3.1-flash-lite")

    # LLM provider API keys
    gemini_api_key: str = Field(default="")
    groq_api_key: str = Field(default="")

    # Auth — Clerk OIDC
    clerk_secret_key: str = Field(default="")
    clerk_jwks_url: str = Field(default="")

    # Tracing — Langfuse / Phoenix via OTLP
    otlp_endpoint: str = Field(default="")
    langfuse_public_key: str = Field(default="")
    langfuse_secret_key: str = Field(default="")

    # Temporal (durable workflow engine) — dev server by default
    temporal_host: str = Field(default="localhost:7233")
    temporal_namespace: str = Field(default="default")
    temporal_task_queue: str = Field(default="clearance-prior-auth")

    # Payer service (separate FastAPI app with injected failures)
    payer_base_url: str = Field(default="http://localhost:8081")

    # Offline mode: set OFFLINE=1 in CI / unit tests
    offline: bool = Field(default=False)

    # Per-run LLM budget ceiling (USD)
    budget_usd_max: float = Field(default=0.10)

    # LLM call timeout (seconds)
    llm_timeout: int = Field(default=30)


settings: Settings = Settings()
