from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# app/config.py -> parents[0] = app/, [1] = backend/, [2] = hop/ (project root)
ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ENV_FILE, extra="ignore")

    database_url: str
    redis_url: str
    test_database_url: str | None = None

    smtp_host: str = "localhost"
    smtp_port: int = 1025
    mail_from: str = "Hop <no-reply@hop.local>"
    app_base_url: str = "http://localhost:5173"


settings = Settings()
