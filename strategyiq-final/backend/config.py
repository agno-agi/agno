from pydantic_settings import BaseSettings

INSECURE_JWT_SECRETS = frozenset(
    {
        "",
        "change_this_64_random_chars",
        "changeme",
        "secret",
        "dev-secret",
    }
)


def validate_jwt_secret(secret: str) -> None:
    """Reject missing or known-insecure JWT secrets at startup."""
    trimmed = (secret or "").strip()
    if len(trimmed) < 16:
        raise ValueError("JWT_SECRET must be set to at least 16 characters")
    if trimmed in INSECURE_JWT_SECRETS:
        raise ValueError("JWT_SECRET uses an insecure default value")


class Settings(BaseSettings):
    pinecone_api_key: str = ""
    pinecone_index: str = "strategyiq-docs"
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    xai_api_key: str = ""
    polygon_api_key: str = ""
    finnhub_api_key: str = ""
    coingecko_api_key: str = ""
    fmp_api_key: str = ""
    benzinga_api_key: str = ""
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_price_pro: str = ""
    stripe_price_elite: str = ""
    database_url: str = "postgresql+psycopg2://strategy:pass@localhost:5432/strategyiq"
    redis_url: str = "redis://localhost:6379/0"
    jwt_secret: str = ""
    jwt_algorithm: str = "HS256"
    screener_cache_ttl: int = 900
    # Comma-separated browser origins. Never use "*" with credentials.
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    class Config:
        env_file = ".env"
        extra = "ignore"

    def parsed_cors_origins(self) -> list[str]:
        origins = [o.strip() for o in self.cors_origins.split(",") if o.strip()]
        return origins or ["http://localhost:3000"]


settings = Settings()
