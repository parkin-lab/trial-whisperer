from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Trial Whisperer API"
    app_version: str = Field(default="1.0.0", alias="APP_VERSION")
    environment: str = "development"

    database_url: str = Field(default="postgresql+asyncpg://postgres:postgres@localhost:5432/trialwhisperer", alias="DATABASE_URL")
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")

    secret_key: str = Field(default="change-me", alias="SECRET_KEY")
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7
    verify_token_expire_hours: int = 24

    email_from: str = Field(default="noreply@trial-whisperer.local", alias="EMAIL_FROM")
    smtp_host: str | None = Field(default=None, alias="SMTP_HOST")
    smtp_port: int = Field(default=587, alias="SMTP_PORT")
    smtp_user: str | None = Field(default=None, alias="SMTP_USER")
    smtp_pass: str | None = Field(default=None, alias="SMTP_PASS")

    frontend_url: str = Field(default="http://localhost:3000", alias="FRONTEND_URL")
    uploads_dir: str = Field(default="./uploads", alias="UPLOADS_DIR")
    openclaw_gateway_url: str = Field(default="http://host.docker.internal:18789", alias="OPENCLAW_GATEWAY_URL")
    openclaw_gateway_token: str = Field(default="", alias="OPENCLAW_GATEWAY_TOKEN")
    llm_model: str = Field(default="anthropic/claude-haiku-4-5", alias="LLM_MODEL")
    qa_model: str = Field(default="anthropic/claude-sonnet-4-6", alias="QA_MODEL")
    initial_owner_email: str | None = Field(default=None, alias="INITIAL_OWNER_EMAIL")
    initial_owner_password: str | None = Field(default=None, alias="INITIAL_OWNER_PASSWORD")
    initial_owner_domain: str | None = Field(default=None, alias="INITIAL_OWNER_DOMAIN")


@lru_cache
def get_settings() -> Settings:
    return Settings()
