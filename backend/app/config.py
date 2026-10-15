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

    session_cookie_name: str = "hop_session"
    session_ttl_seconds: int = 7 * 24 * 60 * 60  # 7 days
    cookie_secure: bool = False  # set to true in production (HTTPS only)

    crawler_user_agent: str = "HopBot/0.1 (+https://github.com/tjonadibernice/hop)"
    crawl_delay_seconds: float = 1.0  # minimum gap between requests to one site
    # Lets the crawler fetch localhost and private addresses. Only for local
    # testing: never turn this on where the crawler can reach real services.
    crawl_allow_private_hosts: bool = False

    # Enrichment: LLM providers, tried in this order. Leave a key empty to skip
    # that provider. Ollama runs locally and needs no key.
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-3.1-flash-lite"
    openai_api_key: str | None = None
    openai_model: str = "gpt-5.6-luna"
    ollama_base_url: str | None = None  # e.g. http://localhost:11434/v1
    ollama_model: str = "llama3.2"

    # Embeddings (optional: without a key, pages are stored without one)
    voyage_api_key: str | None = None
    voyage_model: str = "voyage-4-lite"

    # Safety check (optional: without a key, pages can't be auto-approved)
    safe_browsing_api_key: str | None = None


settings = Settings()
