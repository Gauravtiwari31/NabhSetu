from decimal import Decimal
from enum import Enum
from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class DataMode(str, Enum):
    MOCK = "mock"
    LIVE = "live"


class EgressMode(str, Enum):
    DIRECT = "direct"
    STATIC_PROXY = "static_proxy"
    PROXY_POOL = "proxy_pool"
    REGION_PINNED = "region_pinned"
    FAILOVER = "failover"


class Settings(BaseSettings):
    """Runtime configuration loaded from APIX_* environment variables."""

    model_config = SettingsConfigDict(
        env_prefix="APIX_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "Nabhsetu Backend"
    environment: str = "development"
    log_level: str = "INFO"
    data_mode: DataMode = DataMode.MOCK
    egress_mode: EgressMode = EgressMode.DIRECT

    # Credentials and other secrets deliberately have no code defaults.
    database_url: SecretStr | None = None
    api_key: SecretStr | None = None
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    index_config_dir: str = ""
    scheduler_interval_seconds: int = Field(default=300, ge=5)
    scheduler_source_names: str = ""
    worker_poll_seconds: int = Field(default=2, ge=1)
    publisher_interval_seconds: int = Field(default=60, ge=5)
    index_freshness_hours: int = Field(default=36, ge=1)

    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    def scheduler_source_allowlist(self) -> tuple[str, ...]:
        return tuple(part.strip() for part in self.scheduler_source_names.split(",") if part.strip())

    circuit_failure_threshold: int = Field(default=5, ge=1)
    circuit_cooldown_seconds: int = Field(default=60, ge=1)
    compliance_lease_seconds: int = Field(default=30, ge=1)
    max_adapter_retries: int = Field(default=2, ge=0)
    observation_bucket_seconds: int = Field(default=60, ge=1)
    terms_review_max_age_days: int = Field(default=365, ge=1)
    robots_review_max_age_days: int = Field(default=30, ge=1)

    identified_user_agent: str = (
        "Nabhsetu-Research-Bot/0.1 (+https://www.mospi.gov.in; SIH26056 airfare index research)"
    )
    http_timeout_seconds: float = Field(default=20.0, ge=1)
    http_connect_timeout_seconds: float = Field(default=10.0, ge=1)
    playwright_timeout_ms: int = Field(default=25000, ge=1000)
    live_payload_max_bytes: int = Field(default=524288, ge=1024)

    confidence_mock: Decimal = Decimal("0.90")
    confidence_public_api: Decimal = Decimal("0.99")
    confidence_structured_feed: Decimal = Decimal("0.98")
    confidence_static_html: Decimal = Decimal("0.94")
    confidence_embedded_json: Decimal = Decimal("0.96")
    confidence_playwright_network: Decimal = Decimal("0.97")
    confidence_playwright_dom: Decimal = Decimal("0.93")
    confidence_document: Decimal = Decimal("0.92")
    confidence_visual: Decimal = Decimal("0.75")

    def require_database_url(self) -> str:
        if self.database_url is None:
            raise RuntimeError("APIX_DATABASE_URL must be set for database operations")
        return self.database_url.get_secret_value()

    def require_api_key(self) -> str:
        if self.api_key is None:
            raise RuntimeError("APIX_API_KEY must be set for restricted endpoints")
        return self.api_key.get_secret_value()


@lru_cache
def get_settings() -> Settings:
    return Settings()
