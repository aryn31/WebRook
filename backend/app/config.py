from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://hookflow:hookflow@localhost:5432/hookflow"
    redis_url: str = "redis://localhost:6379/0"

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

    # Delivery
    delivery_timeout_seconds: float = 10.0
    delivery_connect_timeout_seconds: float = 5.0
    delivery_max_attempts: int = 5
    retry_base_delay_seconds: float = 30.0
    retry_max_delay_seconds: float = 6 * 3600.0
    delivery_lease_seconds: int = 60
    response_body_max_bytes: int = 4096
    sweep_interval_seconds: float = 5.0

    # Block deliveries to loopback/private/link-local addresses (SSRF protection).
    # Turn off only for local development, where test receivers run on private networks.
    block_private_destinations: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()
