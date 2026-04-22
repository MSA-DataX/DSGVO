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

    @property
    def allowed_origins_list(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]


settings = Settings()
