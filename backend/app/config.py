from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    scan_max_depth: int = 1
    scan_max_pages: int = 8
    scan_page_timeout_ms: int = 20000
    scan_user_agent: str = "GDPR-Scanner/0.1 (+compliance audit)"

    ai_provider: str = "openai"          # openai | azure | none
    ai_max_policy_chars: int = 24000
    ai_request_timeout_s: int = 60

    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"

    azure_openai_api_key: str | None = None
    azure_openai_endpoint: str | None = None
    azure_openai_deployment: str | None = None
    azure_openai_api_version: str = "2024-08-01-preview"

    host: str = "0.0.0.0"
    port: int = 8000

    # Comma-separated list. "*" allows any origin (dev only).
    # In production set e.g. ALLOWED_ORIGINS=https://scanner.example.com
    allowed_origins: str = "*"

    # Persistence. Default keeps single-file SQLite for zero-config local dev;
    # production should set DATABASE_URL to a Postgres DSN, e.g.
    #   postgresql+asyncpg://user:pw@localhost:5432/scanner
    # The same SQLAlchemy code path serves both — only the URL changes.
    database_url: str = "sqlite+aiosqlite:///scans.db"

    # Auth (Phase 1.2). The dev default is a deterministic insecure secret so
    # the app boots without configuration; production MUST override JWT_SECRET
    # with a strong random value (≥ 32 random bytes, e.g.
    # `python -c "import secrets; print(secrets.token_urlsafe(48))"`).
    jwt_secret: str = "dev-only-insecure-replace-in-production"
    jwt_algorithm: str = "HS256"
    jwt_ttl_minutes: int = 60 * 24 * 7      # 7 days — refresh on activity later

    # Background jobs (Phase 3). When unset, the app runs in "sync mode":
    # /scan and /scan/stream execute inline on the HTTP worker, just like
    # before. Set REDIS_URL to enable the Arq-backed /scan/jobs endpoints
    # and start `arq app.worker.WorkerSettings` in a second process.
    # Example: REDIS_URL=redis://localhost:6379
    redis_url: str | None = None

    # Billing (Phase 5b). All three must be set to enable Mollie checkout
    # / cancel / webhooks. Without them the /billing/checkout endpoint
    # returns 503 — the tier scaffolding (Phase 5a) still works, admins
    # just assign plans manually via /admin/organizations/{id}/set-plan.
    #
    # MOLLIE_API_KEY          — "test_..." or "live_..."; mode auto-detected by Mollie.
    # APP_BASE_URL            — public origin of THIS backend; used to build
    #                           Mollie's webhook + redirect URLs. Must be https
    #                           in production — Mollie refuses http webhooks in live mode.
    # MOLLIE_WEBHOOK_TOKEN    — random path segment so only Mollie knows where
    #                           to POST. Rotate alongside the API key.
    mollie_api_key: str | None = None
    app_base_url: str | None = None
    mollie_webhook_token: str | None = None

    # Observability (Phase 7). Everything below is opt-in: no env var →
    # behaviour is identical to pre-Phase-7. Sentry reports nothing,
    # logs stay human-readable, /metrics still works (Prometheus just
    # shows zeros).
    #
    # LOG_FORMAT             — "text" (dev default, readable) or "json"
    #                           (prod — one line of JSON per record, ready
    #                           for Loki / CloudWatch / any log shipper).
    # LOG_LEVEL              — DEBUG / INFO / WARNING / ERROR (default INFO).
    # APP_VERSION            — stamped onto /health + every Sentry event so
    #                           you can tell which deploy emitted what. Set
    #                           from the CI pipeline (git sha) in prod.
    # SENTRY_DSN             — opt-in: when set, uncaught exceptions + 5xx
    #                           responses ship to Sentry. No PII beyond
    #                           what FastAPI already logs.
    # SENTRY_TRACES_SAMPLE_RATE — 0.0 (off) to 1.0 (every request). 0.1 is
    #                           a sane default for moderate traffic.
    log_format: str = "text"
    log_level: str = "INFO"
    app_version: str = "dev"
    sentry_dsn: str | None = None
    sentry_traces_sample_rate: float = 0.0

    @property
    def allowed_origins_list(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]


settings = Settings()
