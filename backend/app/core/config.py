"""Application configuration.

Every tunable lives here and is loaded from the environment (or ``.env``).
Nothing else in the codebase is allowed to read ``os.environ`` directly --
that rule is what keeps configuration auditable as the app grows.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any, Literal

from pydantic import computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="ignore",
    )

    # ---------------------------------------------------------------- app ---
    app_name: str = "CineAI"
    environment: Literal["local", "test", "staging", "production"] = "local"
    debug: bool = True
    api_v1_prefix: str = "/api/v1"
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    # ----------------------------------------------------------- database ---
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_user: str = "cineai"
    postgres_password: str = "cineai_dev_pw"
    postgres_db: str = "cineai"
    db_echo: bool = False

    # TLS. Managed providers (Aiven, Neon, RDS) require it; a local socket does
    # not. "require" encrypts but does not verify the server's identity;
    # "verify-full" also checks the certificate chain and hostname and is what
    # you want in production -- it needs POSTGRES_SSLROOTCERT to point at the
    # provider's CA bundle.
    postgres_sslmode: Literal[
        "disable", "allow", "prefer", "require", "verify-ca", "verify-full"
    ] = "prefer"
    postgres_sslrootcert: str = ""

    # Pool sizing is bounded by the *server's* connection limit, not by what the
    # app would like. Managed plans are often capped low (Aiven's smallest is
    # 20), and that budget is shared with migrations, psql sessions and any
    # other client. pool_size + max_overflow is the ceiling this process can
    # reach; keep it well under the server cap.
    db_pool_size: int = 5
    db_max_overflow: int = 5
    db_pool_recycle_seconds: int = 1800   # managed proxies drop idle connections
    db_connect_timeout_seconds: int = 10

    @computed_field  # type: ignore[prop-decorator]
    @property
    def database_url(self) -> str:
        """A correctly escaped DSN.

        Built with SQLAlchemy's ``URL.create`` rather than string formatting:
        provider-generated passwords routinely contain ``@``, ``/``, ``?`` and
        other characters that silently corrupt a hand-built URL. This escapes
        them properly.
        """
        return URL.create(
            drivername="postgresql+psycopg",
            username=self.postgres_user,
            password=self.postgres_password,
            host=self.postgres_host,
            port=self.postgres_port,
            database=self.postgres_db,
        ).render_as_string(hide_password=False)

    @property
    def db_connect_args(self) -> dict[str, Any]:
        """libpq options passed per-connection rather than in the URL."""
        args: dict[str, Any] = {
            "sslmode": self.postgres_sslmode,
            "connect_timeout": self.db_connect_timeout_seconds,
            # Shows up in pg_stat_activity, so it is obvious which client holds
            # a connection when you are near the cap.
            "application_name": f"{self.app_name.lower()}-{self.environment}",
        }
        if self.postgres_sslrootcert:
            args["sslrootcert"] = self.postgres_sslrootcert
        return args

    @computed_field  # type: ignore[prop-decorator]
    @property
    def database_host_summary(self) -> str:
        """Host and TLS mode, safe to log -- never the password."""
        return f"{self.postgres_user}@{self.postgres_host}:{self.postgres_port}/{self.postgres_db} (sslmode={self.postgres_sslmode})"

    # --------------------------------------------------------------- auth ---
    jwt_secret: str = "dev-only-secret-change-me-32-bytes-minimum-length"
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 30
    refresh_token_ttl_days: int = 30

    # ------------------------------------------------------- booking rules ---
    # Two different holds, because they answer two different questions.
    #
    # A *selection* hold is short: it only has to survive filling in the
    # checkout form. Making it long means a customer who backs out silently
    # sits on seats nobody else can buy for eight minutes.
    #
    # A *kept* hold is the long one, and it is opt-in -- the customer presses
    # "keep these seats" and takes responsibility for the countdown.
    seat_selection_ttl_seconds: int = 180     # 3 minutes to reach payment
    seat_hold_ttl_seconds: int = 480          # 8 minutes once explicitly kept
    max_seats_per_booking: int = 10
    booking_cutoff_minutes: int = 20          # no booking within N min of showtime
    # Tiered cancellation, in the shape Indian multiplexes actually use: the
    # closer to showtime, the less comes back, and inside the cutoff nothing
    # can be cancelled at all because the seat can no longer be resold.
    # The convenience fee is never refunded on a *voluntary* cancellation --
    # that is near-universal, and it is stated up front rather than discovered
    # afterwards. An operator-cancelled show refunds everything, fee included.
    cancellation_cutoff_minutes: int = 120        # no cancellation inside this
    cancellation_full_refund_minutes: int = 1440  # >24h before: full ticket value
    cancellation_partial_refund_minutes: int = 240  # >4h before: partial
    cancellation_partial_refund_percent: str = "50.00"
    convenience_fee_percent: str = "8.00"     # of ticket subtotal
    convenience_fee_cap_minor: int = 6000     # Rs 60.00 cap, in paise
    gst_percent_low: str = "12.00"            # tickets priced <= threshold
    gst_percent_high: str = "18.00"
    gst_threshold_minor: int = 10000          # Rs 100.00
    currency: str = "INR"
    ticket_qr_secret: str = "dev-only-ticket-secret-change-me-32-bytes-min"

    # ------------------------------------------------------------ payments ---
    payment_gateway: Literal["mock", "stripe", "razorpay"] = "mock"
    mock_gateway_failure_rate: float = 0.0    # 0.0-1.0, for chaos testing
    mock_gateway_latency_ms: int = 250
    payment_webhook_secret: str = "dev-only-webhook-secret"

    # ------------------------------------------------------------------ ai ---
    anthropic_api_key: str = ""
    llm_provider: Literal["anthropic", "echo"] = "echo"
    # Model ids are complete as written -- never append a date suffix.
    # Tiering is a cost lever: cheap models for high-volume mechanical work,
    # the strong model for the agent that can actually reason about a booking.
    llm_model_fast: str = "claude-haiku-4-5"        # $1 / $5 per Mtok
    llm_model_balanced: str = "claude-sonnet-5"     # $3 / $15 per Mtok
    llm_model_deep: str = "claude-opus-5"           # $5 / $25 per Mtok
    llm_effort: str = "medium"                      # low|medium|high|xhigh|max
    llm_max_tokens: int = 2048
    llm_timeout_seconds: float = 60.0
    llm_daily_token_budget: int = 2_000_000

    embedding_provider: Literal["hash", "local", "voyage"] = "hash"
    embedding_model_local: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_model_voyage: str = "voyage-3.5-lite"
    voyage_api_key: str = ""
    embedding_dimensions: int = 384           # must match the pgvector column

    # ----------------------------------------------------------- workers ---
    enable_scheduler: bool = True
    hold_sweeper_interval_seconds: int = 60

    # ------------------------------------------------------ rate limiting ---
    rate_limit_default_per_minute: int = 120
    rate_limit_ai_per_minute: int = 20

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_local(self) -> bool:
        return self.environment in ("local", "test")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
