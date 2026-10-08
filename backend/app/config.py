from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# app/config.py -> parents[0] = app/, [1] = backend/, [2] = hop/ (project root)
ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ENV_FILE, extra="ignore")

    database_url: str
    redis_url: str


settings = Settings()
