from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://hookflow:hookflow@localhost:5432/hookflow"
    redis_url: str = "redis://localhost:6379/0"

    @field_validator("database_url")
    @classmethod
    def _use_psycopg3(cls, v: str) -> str:
        # Hosts like Render give "postgres://" or "postgresql://" URLs; SQLAlchemy needs the driver named.
        for prefix in ("postgres://", "postgresql://"):
            if v.startswith(prefix):
                return "postgresql+psycopg://" + v[len(prefix):]
        return v

    # Fernet key used to encrypt endpoint signing secrets at rest.
    # Generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    secret_encryption_key: str

    # Session cookie
    session_cookie_name: str = "hf_session"
    session_ttl_hours: int = 24 * 7
    cookie_secure: bool = False

    # Limits
    max_payload_bytes: int = 1024 * 1024
    max_endpoints_per_account: int = 50
    auth_rate_limit_per_minute: int = 10
    # Manual replays per account per minute. Each delivery replayed counts once.
    replay_rate_limit_per_minute: int = 60
    # How long an Idempotency-Key on POST /v1/events is remembered.
    idempotency_key_ttl_hours: int = 24
    # Default ingestion limits per account. A user row can override either one; 0 means unlimited.
    event_rate_limit_per_minute: int = 600
    daily_event_quota: int = 10_000

    # Number of proxies in front of the API that append to X-Forwarded-For (e.g. 1 for Render's load
    # balancer). 0 ignores the header and uses the connection's address. Used for audit-log IPs.
    trusted_proxy_count: int = 0

    # Delivery
    delivery_timeout_seconds: float = 10.0
    delivery_connect_timeout_seconds: float = 5.0
    delivery_max_attempts: int = 5
    retry_base_delay_seconds: float = 30.0
    retry_max_delay_seconds: float = 6 * 3600.0
    delivery_lease_seconds: int = 60
    response_body_max_bytes: int = 4096
    sweep_interval_seconds: float = 5.0
    # How often the outbox publisher moves unpublished queue messages to Redis.
    outbox_poll_interval_seconds: float = 1.0
    # Default grace period when rotating a signing secret (the old secret keeps signing too).
    secret_rotation_grace_seconds: int = 24 * 3600
    # Most requests in flight to one endpoint at a time, across all workers. Extra deliveries wait briefly.
    endpoint_max_concurrency: int = 10

    # Retention. Events older than this (and their deliveries and attempts) are deleted once nothing about
    # them is still in progress. 0 keeps them forever.
    event_retention_days: int = 30
    audit_log_retention_days: int = 365

    # Monitoring. If METRICS_TOKEN is set, GET /metrics requires "Authorization: Bearer <token>".
    metrics_token: str | None = None
    # Alert (an ERROR log line) when due work has waited longer than this, or the worker goes quiet.
    alert_queue_delay_seconds: int = 300
    alert_worker_silence_seconds: int = 120

    # Block deliveries to loopback/private/link-local addresses (SSRF protection).
    # Turn off only for local development, where test receivers run on private networks.
    block_private_destinations: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()
